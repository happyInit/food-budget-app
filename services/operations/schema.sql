-- Apply with: psql "$DATABASE_URL" -f schema.sql
-- This DDL is idempotent and belongs to the Operations service.

create schema if not exists operations;

create table if not exists operations.alerts (
    alert_id text primary key,
    source text not null,
    status text not null check (status in ('firing', 'resolved')),
    alert_name text not null,
    service text not null,
    severity text not null,
    starts_at timestamptz not null,
    ends_at timestamptz,
    received_at timestamptz not null,
    pod text,
    container text,
    labels jsonb not null,
    annotations jsonb not null,
    generator_url text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists alerts_firing_starts_at_idx
    on operations.alerts (starts_at)
    where status = 'firing';

create table if not exists operations.incidents (
    incident_id text primary key,
    status text not null check (status in ('open')),
    title text not null,
    first_seen_at timestamptz not null,
    last_seen_at timestamptz not null,
    earliest_alert_id text not null,
    earliest_alert_name text not null,
    suspected_origin_service text not null,
    affected_services jsonb not null,
    alert_count integer not null check (alert_count > 0),
    grouping_reasons jsonb not null,
    alerts jsonb not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists incidents_open_last_seen_at_idx
    on operations.incidents (last_seen_at desc)
    where status = 'open';
