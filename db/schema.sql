-- Voting Platform — Core Schema (PostgreSQL)
--
-- Ballot secrecy by design:
--   `ballots` has NO reference to `users`.
--
-- `eligibility` tracks WHO has voted.
-- `ballots` tracks WHAT was voted for.
--
-- There is intentionally no relational path that joins a user
-- to the option they selected.

CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- ============================================================
-- USERS
-- ============================================================

CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               TEXT NOT NULL UNIQUE,
    oauth_provider      TEXT NOT NULL,
    provider_user_id    TEXT NOT NULL,

    role                TEXT NOT NULL DEFAULT 'voter'
                        CHECK (role IN ('voter', 'admin')),

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (oauth_provider, provider_user_id)
);


-- ============================================================
-- POLLS
-- ============================================================

CREATE TABLE polls (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    title               TEXT NOT NULL,
    description         TEXT,

    start_time          TIMESTAMPTZ NOT NULL,
    end_time            TIMESTAMPTZ NOT NULL,

    status              TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'open', 'closed')),

    created_by          UUID NOT NULL
                        REFERENCES users(id),

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (end_time > start_time)
);


-- ============================================================
-- POLL OPTIONS
-- ============================================================

CREATE TABLE options (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    poll_id             UUID NOT NULL
                        REFERENCES polls(id)
                        ON DELETE CASCADE,

    label               TEXT NOT NULL,

    display_order       INTEGER NOT NULL DEFAULT 0,

    -- Supports the composite FK from ballots and guarantees
    -- that a ballot option belongs to the same poll.
    UNIQUE (poll_id, id)
);


-- ============================================================
-- ELIGIBILITY
-- ============================================================
--
-- Tracks WHO has voted for a poll.
-- Deliberately contains no selected option.

CREATE TABLE eligibility (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id             UUID NOT NULL
                        REFERENCES users(id),

    poll_id             UUID NOT NULL
                        REFERENCES polls(id)
                        ON DELETE CASCADE,

    has_voted            BOOLEAN NOT NULL DEFAULT FALSE,

    voted_at             TIMESTAMPTZ,

    UNIQUE (user_id, poll_id),

    -- If the user has voted, we must have a timestamp.
    CHECK (
        (has_voted = FALSE AND voted_at IS NULL)
        OR
        (has_voted = TRUE AND voted_at IS NOT NULL)
    )
);


-- ============================================================
-- BALLOT CHAIN STATE
-- ============================================================
--
-- One row per poll.
--
-- This row is the synchronization point for advancing the
-- ballot hash chain.
--
-- Vote submission should lock this row with:
--
--     SELECT latest_hash
--     FROM poll_ballot_state
--     WHERE poll_id = :poll_id
--     FOR UPDATE;
--
-- That serializes ballot-chain advancement for a single poll.

CREATE TABLE poll_ballot_state (
    poll_id             UUID PRIMARY KEY
                        REFERENCES polls(id)
                        ON DELETE CASCADE,

    latest_hash         TEXT,

    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ============================================================
-- BALLOTS
-- ============================================================
--
-- Records WHAT was voted for.
--
-- IMPORTANT:
--   There is intentionally NO user_id column.
--
-- `id` is client-generated and acts as the idempotency key.
--
-- `prev_hash` points to the previous ballot in this poll's
-- chain. NULL represents the genesis ballot.
--
-- `record_hash` is computed by the application from the
-- previous hash and ballot contents.

CREATE TABLE ballots (
    id                  UUID PRIMARY KEY,

    poll_id             UUID NOT NULL
                        REFERENCES polls(id)
                        ON DELETE CASCADE,

    option_id           UUID NOT NULL,

    prev_hash           TEXT,

    record_hash         TEXT NOT NULL,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Guarantees that the option belongs to this poll.
    FOREIGN KEY (poll_id, option_id)
        REFERENCES options (poll_id, id)
);


-- ============================================================
-- ADMIN AUDIT LOG
-- ============================================================

CREATE TABLE admin_audit_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    actor_id            UUID NOT NULL
                        REFERENCES users(id),

    action              TEXT NOT NULL,

    payload             JSONB,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ============================================================
-- INDEXES
-- ============================================================

-- Eligibility lookups:
-- "Who is eligible / who has voted in this poll?"
CREATE INDEX idx_eligibility_poll
    ON eligibility (poll_id);

-- Ballot aggregation:
-- "How many votes did each option receive in this poll?"
CREATE INDEX idx_ballots_poll_option
    ON ballots (poll_id, option_id);

-- Chain traversal / reconciliation:
-- Ballots in chronological order within a poll.
CREATE INDEX idx_ballots_poll_created_at
    ON ballots (poll_id, created_at);

-- Options belonging to a poll.
CREATE INDEX idx_options_poll
    ON options (poll_id);

-- Audit history for an administrator / actor.
CREATE INDEX idx_admin_audit_actor
    ON admin_audit_log (actor_id, created_at);


-- ============================================================
-- APPLICATION-LEVEL TRANSACTION CONTRACT
-- ============================================================
--
-- The database schema cannot express the complete vote operation.
-- The application MUST perform the vote as ONE database transaction.
--
-- Recommended sequence:
--
--   1. Verify the poll is OPEN and within its voting window.
--
--   2. Atomically claim eligibility:
--
--        UPDATE eligibility
--        SET
--            has_voted = TRUE,
--            voted_at = now()
--        WHERE user_id = :user_id
--          AND poll_id = :poll_id
--          AND has_voted = FALSE
--        RETURNING id;
--
--      Exactly one returned row means this transaction successfully
--      claimed the user's vote.
--
--   3. Lock the poll's ballot-state row:
--
--        SELECT latest_hash
--        FROM poll_ballot_state
--        WHERE poll_id = :poll_id
--        FOR UPDATE;
--
--      This serializes ballot-chain updates for this poll.
--
--   4. Compute the new ballot record_hash from:
--
--        prev_hash || poll_id || option_id || created_at
--
--   5. Insert the ballot.
--
--   6. Update poll_ballot_state.latest_hash with the new hash.
--
--   7. COMMIT.
--
-- If any step fails, ROLLBACK the entire transaction.
--
-- IMPORTANT:
-- `ON CONFLICT (id) DO NOTHING` alone does not fully define
-- idempotency semantics. The API must decide how to handle:
--
--   a) same id + same payload
--   b) same id + different payload
--
-- Ideally:
--
--   same id + same request  -> return the original result
--   same id + different request -> reject as idempotency conflict