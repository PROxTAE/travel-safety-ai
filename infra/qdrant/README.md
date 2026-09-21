# `infra/qdrant/`

**เจ้าของ:** lead + คนที่ 6

config / collection bootstrap ของ Qdrant

อ่านแผน: [`IMPLEMENTATION_PLANS/06_RISK_KNOWLEDGE_SERVICES_IMPLEMENTATION.md`](../../IMPLEMENTATION_PLANS/06_RISK_KNOWLEDGE_SERVICES_IMPLEMENTATION.md)

Module 06 uses versioned collection names and the alias configured by
`RISK_KNOWLEDGE_QDRANT_ACTIVE_ALIAS`. A collection is created as `DRAFT`; the
CLI refuses to switch the alias until PostgreSQL records an approved manifest,
evaluation checksum, approver, and approval timestamp.

```bash
docker compose run --rm risk-knowledge risk-knowledge-qdrant prepare --version 1.0.0
docker compose run --rm risk-knowledge risk-knowledge-qdrant activate --version 1.0.0
```

The second command is expected to fail until the Phase 5 knowledge evaluation
and approval workflow marks that exact version `APPROVED`. The previous
collection remains available for rollback; do not delete Qdrant volumes during
normal rollback.
