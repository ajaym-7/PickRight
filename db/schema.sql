-- Voting Platform — Core Schema (PostgreSQL)
--
-- Ballot secrecy by design: `ballots` has NO reference to `users`.
-- `eligibility` tracks WHO has voted; `ballots` tracks WHAT was voted for.
-- Nothing in this schema lets you join the two back together.

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- provides gen_random_uuid()

CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               TEXT NOT NULL UNIQUE,
    oauth_provider      TEXT NOT NULL,              -- e.g. 'google'
    provider_user_id    TEXT NOT NULL,
    role                TEXT NOT NULL DEFAULT 'voter' CHECK (role IN ('voter', 'admin')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (oauth_provider, provider_user_id)
);

CREATE TABLE polls (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title               TEXT NOT NULL,
    description         TEXT,
    start_time          TIMESTAMPTZ NOT NULL,
    end_time            TIMESTAMPTZ NOT NULL,
    status              TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'open', 'closed')),
    created_by          UUID NOT NULL REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_time > start_time)
);

CREATE TABLE options (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    poll_id             UUID NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    label               TEXT NOT NULL,
    display_order       INTEGER NOT NULL DEFAULT 0
);

-- Tracks WHO has voted, per poll — never what they voted for.
CREATE TABLE eligibility (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id),
    poll_id             UUID NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    has_voted           BOOLEAN NOT NULL DEFAULT FALSE,
    voted_at            TIMESTAMPTZ,
    UNIQUE (user_id, poll_id)                        -- the hard one-vote-per-user backstop
);

-- Records WHAT was voted for — deliberately has no user_id column.
-- `id` doubles as the client-generated idempotency key sent with the
-- submission, so a retried request can never create a second row.
CREATE TABLE ballots (
    id                  UUID PRIMARY KEY,             -- client-generated idempotency key
    poll_id             UUID NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    option_id           UUID NOT NULL REFERENCES options(id),
    prev_hash           TEXT,                          -- hash of the previous ballot row; NULL = genesis
    record_hash         TEXT NOT NULL,                 -- hash(prev_hash || poll_id || option_id || created_at)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE admin_audit_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id            UUID NOT NULL REFERENCES users(id),
    action              TEXT NOT NULL,                 -- e.g. 'poll.create', 'poll.close'
    payload             JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Read / aggregation indexes
CREATE INDEX idx_eligibility_poll    ON eligibility (poll_id);
CREATE INDEX idx_ballots_poll_option ON ballots (poll_id, option_id);
CREATE INDEX idx_ballots_created_at  ON ballots (created_at);   -- chain traversal / reconciliation
CREATE INDEX idx_options_poll        ON options (poll_id);

-- Application-level note (not enforceable in SQL):
-- On vote submission: 1) transactionally check + set eligibility.has_voted,
-- 2) read the latest ballot's record_hash for this poll as the new prev_hash,
-- 3) INSERT INTO ballots ... ON CONFLICT (id) DO NOTHING — the client's
-- idempotency key makes a retried submission a safe no-op.
