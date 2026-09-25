-- XData CI Agent - database bootstrap for docker compose (dev / pilot).
-- Executed once by the postgres image entrypoint, as the superuser, on first init of
-- the data volume.
--
-- The application role is deliberately NOT a superuser and has NO BYPASSRLS:
-- tenant isolation relies on PostgreSQL Row-Level Security, which superusers bypass.
-- Extensions are created here by the superuser so the app role never needs elevated rights.
--
-- The password is read from the container env ($XDATA_DB_PASSWORD) with psql's \getenv
-- (psql >= 15), so no secret is stored in this file.

\set ON_ERROR_STOP on
\getenv xdata_password XDATA_DB_PASSWORD

CREATE ROLE xdata LOGIN PASSWORD :'xdata_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

CREATE DATABASE xdata OWNER xdata;

\c xdata

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Only the owner role may create objects in public (PG15+ default, stated explicitly).
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO xdata;
