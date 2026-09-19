# `infra/postgres/init/`

**เจ้าของ:** lead

SQL init: extension PostGIS, schema ต่อ service (api, integration, knowledge, decision, recommendation)

อ่านแผน: [`IMPLEMENTATION_PLANS/00_GIT_DOCKER_DELIVERY_RULES.md`](../../../IMPLEMENTATION_PLANS/00_GIT_DOCKER_DELIVERY_RULES.md)

`00-schemas.sql` creates shared extensions and one schema per service on a new
PostgreSQL volume. `01-risk-knowledge-role.sh` then creates the Module 06 login,
makes it owner of only `knowledge`, revokes public schema access, and sets
restrictive default privileges.

The init scripts run only when PostgreSQL initializes an empty data directory.
Existing local volumes must provision the same role before running Module 06
migrations; do not delete a volume to force re-initialization. The required
credentials are `RISK_KNOWLEDGE_DB_USER` and the secret
`RISK_KNOWLEDGE_DB_PASSWORD` from the deployment secret store or local `.env`.
Because PostgreSQL is shared infrastructure, the role script exits successfully
without making Module 06 changes when `RISK_KNOWLEDGE_DB_PASSWORD` is absent.
The risk-knowledge service then reports database configuration as unavailable;
it does not substitute a default credential.
