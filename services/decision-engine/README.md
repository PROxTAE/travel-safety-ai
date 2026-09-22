# `services/decision-engine/`

**เจ้าของ:** คนที่ 7 · 07-decision-engine

deterministic policy เลือก NORMAL/CHANGE_ROUTE/DELAY/AVOID + LLM explanation

อ่านแผน: [`IMPLEMENTATION_PLANS/07_DECISION_LLM_ENGINE_IMPLEMENTATION.md`](../../IMPLEMENTATION_PLANS/07_DECISION_LLM_ENGINE_IMPLEMENTATION.md)

## Runtime

The service loads only an `APPROVED` policy from `policies/v1/decision-table.yaml`.
It locks the action before any explanation step and exposes:

- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`
- `GET /internal/v1/policy`
- `POST /internal/v1/decisions`

In development, internal authentication is optional. Production requires
`INTERNAL_SERVICE_TOKEN`; readiness remains `not_ready` without it or without an
approved policy. The deterministic explanation is used when an LLM is unavailable,
so no mock provider data is returned.

Run the focused checks from the repository root:

```powershell
docker compose build decision-engine
docker compose -f compose.yaml -f compose.dev.yaml --profile app up decision-engine
```
