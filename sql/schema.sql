CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS outreach_catalog_versions (
    catalog_version TEXT PRIMARY KEY,
    generated_from TEXT NOT NULL,
    catalog_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS outreach_offers (
    offer_key TEXT PRIMARY KEY,
    catalog_version TEXT NOT NULL REFERENCES outreach_catalog_versions(catalog_version),
    offer_json JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outreach_prospects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name TEXT,
    website TEXT NOT NULL,
    domain TEXT NOT NULL UNIQUE,
    source_query TEXT,
    source_url TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    research_json JSONB,
    contact_email TEXT,
    contact_email_source_url TEXT,
    selected_offer_key TEXT,
    fit_score INTEGER,
    fit_json JSONB,
    scored_catalog_version TEXT,
    last_contacted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS outreach_prospects_status_idx
    ON outreach_prospects(status, updated_at);
CREATE INDEX IF NOT EXISTS outreach_prospects_score_idx
    ON outreach_prospects(fit_score DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS outreach_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prospect_id UUID NOT NULL REFERENCES outreach_prospects(id) ON DELETE CASCADE,
    catalog_version TEXT NOT NULL,
    offer_key TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    text_body TEXT NOT NULL,
    html_body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'drafted',
    provider_message_id TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outreach_events (
    id BIGSERIAL PRIMARY KEY,
    message_id UUID REFERENCES outreach_messages(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    event_json JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outreach_suppressions (
    email TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outreach_job_runs (
    id BIGSERIAL PRIMARY KEY,
    job_name TEXT NOT NULL,
    status TEXT NOT NULL,
    details JSONB,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);
