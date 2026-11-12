-- ReMind by Her: sign-ups (SQLite, the zero-config default).
-- The PostgreSQL twin is schema.postgres.sql; columns and rules match 1:1.

CREATE TABLE IF NOT EXISTS registrations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name           TEXT    NOT NULL CHECK (length(full_name) BETWEEN 2 AND 60),
    whatsapp_normalized TEXT    NOT NULL UNIQUE CHECK (whatsapp_normalized GLOB '+91[6-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
    email               TEXT    CHECK (email IS NULL OR length(email) <= 120),
    age_range           TEXT    NOT NULL CHECK (age_range IN ('Under 40', '40–44', '45–49', '50–54', '55–59', '60+')),
    city                TEXT    NOT NULL CHECK (length(city) BETWEEN 2 AND 60),
    preferred_language  TEXT    CHECK (preferred_language IS NULL OR preferred_language IN ('English', 'Hindi', 'Kannada', 'Other')),
    heard_from          TEXT    CHECK (heard_from IS NULL OR length(heard_from) <= 40),
    consent_community   INTEGER NOT NULL CHECK (consent_community = 1),
    consent_text        TEXT    NOT NULL,
    utm_source          TEXT    CHECK (utm_source IS NULL OR length(utm_source) <= 200),
    utm_medium          TEXT    CHECK (utm_medium IS NULL OR length(utm_medium) <= 200),
    utm_campaign        TEXT    CHECK (utm_campaign IS NULL OR length(utm_campaign) <= 200),
    utm_term            TEXT    CHECK (utm_term IS NULL OR length(utm_term) <= 200),
    utm_content         TEXT    CHECK (utm_content IS NULL OR length(utm_content) <= 200),
    page_url            TEXT,
    consultation_status TEXT    NOT NULL DEFAULT 'PENDING_WHATSAPP',
    submitted_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_registrations_status       ON registrations (consultation_status);
CREATE INDEX IF NOT EXISTS idx_registrations_submitted_at ON registrations (submitted_at);
