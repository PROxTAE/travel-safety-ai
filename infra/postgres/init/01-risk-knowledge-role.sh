#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -z "${RISK_KNOWLEDGE_DB_PASSWORD:-}" ]]; then
  echo "Skipping Module 06 role bootstrap: RISK_KNOWLEDGE_DB_PASSWORD is not set"
  exit 0
fi

RISK_KNOWLEDGE_DB_USER="${RISK_KNOWLEDGE_DB_USER:-risk_knowledge}"

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=risk_user="$RISK_KNOWLEDGE_DB_USER" \
  --set=risk_password="$RISK_KNOWLEDGE_DB_PASSWORD" \
  --set=database_name="$POSTGRES_DB" <<'EOSQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'risk_user', :'risk_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'risk_user')
\gexec

SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'risk_user', :'risk_password')
\gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'database_name', :'risk_user')
\gexec

SELECT format('ALTER SCHEMA knowledge OWNER TO %I', :'risk_user')
\gexec

REVOKE ALL ON SCHEMA knowledge FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA knowledge TO :"risk_user";

SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA knowledge REVOKE ALL ON TABLES FROM PUBLIC',
  :'risk_user'
)
\gexec

SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA knowledge REVOKE ALL ON SEQUENCES FROM PUBLIC',
  :'risk_user'
)
\gexec
EOSQL
