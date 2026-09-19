#!/usr/bin/env bash
# One-shot GitHub repo setup for the SafetyTravel Assistant team (run by the lead, re-runnable).
#
#   1. push Discord ids / webhook URLs from ops/discord/out/discord-ids.json into Actions secrets+variables
#   2. repo settings: squash-merge only, auto-delete head branches
#   3. ruleset 'protect-main' per IMPLEMENTATION_PLANS/00_GIT_DOCKER_DELIVERY_RULES.md §1 (repo uses Rulesets, not classic protection)
#
# Usage:
#   bash ops/scripts/github_setup.sh <owner>/<repo> [--codeowners] [--checks "lint,typecheck,unit"]
#
#   --codeowners   also require CODEOWNERS review. Turn this on ONLY after every member has
#                  accepted the collaborator invite and CODEOWNERS has real usernames.
#   --checks       comma-separated required status-check names (job names from the CI workflow).
#                  Default: ci (the job in .github/workflows/ci.yml).
#
# Needs: gh (logged in as an admin of the repo), jq, python3
set -euo pipefail

REPO="${1:?usage: github_setup.sh <owner>/<repo> [--codeowners] [--checks a,b,c]}"; shift
CODEOWNERS=false; CHECKS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --codeowners) CODEOWNERS=true ;;
    --checks) CHECKS="$2"; shift ;;
    *) echo "unknown arg $1"; exit 2 ;;
  esac
  shift
done

HERE="$(cd "$(dirname "$0")" && pwd)"
IDS="${HERE}/../discord/out/discord-ids.json"

echo "== 1) Actions secrets / variables"
if [ -f "${IDS}" ]; then
  gh variable set DISCORD_GUILD_ID    -R "${REPO}" -b "$(jq -r '.guild_id' "${IDS}")"
  gh variable set DISCORD_ROLE_IDS    -R "${REPO}" -b "$(jq -c '.role_ids' "${IDS}")"
  gh variable set DISCORD_CHANNEL_IDS -R "${REPO}" -b "$(jq -c '.channel_ids' "${IDS}")"
  gh variable set DISCORD_MODULE_MAP  -R "${REPO}" -b "$(jq -c '.module_map' "${IDS}")"
  for pair in "pull-requests:DISCORD_WEBHOOK_PR" "ci-status:DISCORD_WEBHOOK_CI" \
              "api-contracts:DISCORD_WEBHOOK_CONTRACT" "merge-conflicts:DISCORD_WEBHOOK_CONFLICTS" \
              "announcements:DISCORD_WEBHOOK_ANNOUNCE"; do
    ch="${pair%%:*}"; name="${pair##*:}"
    url="$(jq -r --arg c "${ch}" '.webhooks[$c] // empty' "${IDS}")"
    if [ -n "${url}" ]; then gh secret set "${name}" -R "${REPO}" -b "${url}"; echo "  secret ${name} <- #${ch}"
    else echo "  (no webhook for #${ch} in discord-ids.json - skipped ${name})"; fi
  done
  # ภาพ embed ใน webhook ใช้ได้เฉพาะ repo public (raw.githubusercontent.com)
  if [ "$(gh repo view "${REPO}" --json isPrivate --jq .isPrivate)" = "false" ]; then
    gh variable set DISCORD_EMBED_BASE_URL -R "${REPO}" -b "https://raw.githubusercontent.com/${REPO}/main/assets/safetytravel-discord"
  else
    echo "  repo is private -> DISCORD_EMBED_BASE_URL not set (embeds will have no image)"
  fi
else
  echo "  ${IDS} not found - run: python ops/discord/setup_discord.py"
fi

echo "== 2) Repo merge settings"
gh api -X PATCH "repos/${REPO}" --silent \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true -F squash_merge_commit_title=PR_TITLE -F squash_merge_commit_message=PR_BODY
echo "  squash-only, auto-delete branches"

echo "== 3) Branch protection: main (Ruleset 'protect-main')"
CHECKS_JSON="$(python3 -c 'import json,sys; s=sys.argv[1]; print(json.dumps([{"context": c.strip()} for c in s.split(",") if c.strip()] or [{"context": "ci"}]))' "${CHECKS}")"
RULESET_ID="$(gh api "repos/${REPO}/rulesets" --jq '.[] | select(.name=="protect-main") | .id')"
jq -nc --argjson checks "${CHECKS_JSON}" --argjson co "${CODEOWNERS}" '{
  name: "protect-main", target: "branch", enforcement: "active",
  conditions: {ref_name: {include: ["refs/heads/main"], exclude: []}},
  bypass_actors: [],
  rules: [
    {type: "deletion"}, {type: "non_fast_forward"}, {type: "required_linear_history"},
    {type: "pull_request", parameters: {
        required_approving_review_count: 1, dismiss_stale_reviews_on_push: true,
        require_code_owner_review: $co, require_last_push_approval: true,
        required_review_thread_resolution: true, allowed_merge_methods: ["squash"]}},
    {type: "required_status_checks", parameters: {
        strict_required_status_checks_policy: true, do_not_enforce_on_create: false,
        required_status_checks: $checks}}
  ]}' > "${TMPDIR:-/tmp}/protect-main.json"
if [ -n "${RULESET_ID}" ]; then
  gh api -X PUT "repos/${REPO}/rulesets/${RULESET_ID}" --input "${TMPDIR:-/tmp}/protect-main.json" --silent && echo "  updated ruleset ${RULESET_ID}"
else
  gh api -X POST "repos/${REPO}/rulesets" --input "${TMPDIR:-/tmp}/protect-main.json" --silent && echo "  created ruleset"
fi
echo "  1 approval (2 for safety-critical = reviewer discipline, see rules §1), dismiss stale, last-push approval, no force-push/delete,"
echo "  no bypass actors (lead cannot push to main either), conversation resolution, linear history, squash only"
echo "  code owner reviews: ${CODEOWNERS}   required checks: ${CHECKS:-ci}"

echo
echo "Done. Test a webhook:  curl -X POST -H 'Content-Type: application/json' -d '{\"content\":\"ทดสอบ webhook\"}' \"\$(jq -r '.webhooks[\"pull-requests\"]' ${IDS})\""
