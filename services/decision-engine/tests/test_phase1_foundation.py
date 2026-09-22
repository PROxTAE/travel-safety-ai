from pathlib import Path

import yaml

SERVICE_ROOT = Path(__file__).parents[1]


def test_migrations_define_tracking_and_registry_tables() -> None:
    migration_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((SERVICE_ROOT / "migrations").glob("*.sql"))
    )
    runner_text = (SERVICE_ROOT / "app/repositories/migrations.py").read_text(encoding="utf-8")
    assert "decision.schema_migrations" in runner_text
    for table in ("decision.audit_events", "decision.policy_versions", "decision.prompt_versions"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration_text


def test_registry_metadata_has_a_rollback_pointer_and_explicit_approval_state() -> None:
    registry = yaml.safe_load((SERVICE_ROOT / "policies/registry.yaml").read_text(encoding="utf-8"))
    assert registry["active"]["approval_status"] in {"PENDING_REVIEW", "APPROVED"}
    assert "rollback" in registry
    assert "procedure" in registry["rollback"]
