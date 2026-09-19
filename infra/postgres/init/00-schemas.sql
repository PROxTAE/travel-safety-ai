-- รันครั้งเดียวตอนสร้าง volume ใหม่ (docker-entrypoint-initdb.d)
-- แต่ละ service มี schema ของตัวเอง + Alembic version table แยก (00_GIT_DOCKER_DELIVERY_RULES §10)
-- ห้าม service อ่าน/เขียน table ของ schema อื่นตรง ๆ (00_SHARED_PROJECT_CONTEXT §6)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE SCHEMA IF NOT EXISTS keycloak;        -- Keycloak (KC_DB_SCHEMA)
CREATE SCHEMA IF NOT EXISTS api;             -- module 02
CREATE SCHEMA IF NOT EXISTS agent;           -- module 03 (checkpoints)
CREATE SCHEMA IF NOT EXISTS provider;        -- module 04 (contract §8: providers, fetch_log, health)
CREATE SCHEMA IF NOT EXISTS integration;     -- module 05
CREATE SCHEMA IF NOT EXISTS knowledge;       -- module 06
CREATE SCHEMA IF NOT EXISTS decision;        -- module 07
CREATE SCHEMA IF NOT EXISTS recommendation;  -- module 08
