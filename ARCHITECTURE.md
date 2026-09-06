# Voting Platform — Architecture Notes

Consolidated design reference. See `voting-app-scope.md` for MVP scope/phases and `schema.sql` for the runnable schema.

## 1. Write path (vote submission)
```
Voter (Google OAuth) → API gateway (validates token, rate limits)
  → Vote service (checks idempotency key)
  → Event queue (Redis Streams now, Kafka/Redpanda in Phase 7)
  → Vote database (Postgres, append-only, source of truth)
```

## 2. Live-results path
```
Event queue → Aggregator (dedups by vote id via SETNX)
  → Counter cache (Redis, sharded per option to avoid hot-key contention)
  → Realtime gateway (WebSocket/SSE, pub/sub backplane so it fans out across instances)
  → Voter's browser
```
Periodic reconciliation job recomputes counts from Postgres and corrects Redis, so drift never compounds.

## 3. Data model & ballot secrecy
Tables: `users`, `polls`, `options`, `eligibility`, `ballots`, `admin_audit_log` (full DDL in `schema.sql`).

Core principle: `eligibility` tracks **who** voted — identity-linked on purpose, enforces one-vote-per-user via `UNIQUE(user_id, poll_id)`. `ballots` tracks **what** was voted for — no `user_id` column, so no join can ever connect a person to their choice. Double-vote prevention and ballot secrecy are solved by two different tables, not the same mechanism.

`ballots` is hash-chained (`prev_hash` / `record_hash`): each row hashes the previous one, so editing any past record breaks every hash after it — tamper-evidence independent of identity.

## 4. Anti-cheating & security
- **Identity-binding ladder**: OAuth baseline → domain-restricted OAuth for closed elections → phone verification (Twilio, Phase 7) for open ones
- **Bot/fraud**: rate limiting, CAPTCHA (Turnstile), device fingerprint + anomaly flags for manual review — never auto-block on IP alone
- **Manipulation detection**: lives at the submission-event/metadata layer (IP, device, timestamps, rate-limit counters) — separate from ballot content, so abuse detection never needs to see vote choice
- **Standard hardening**: TLS everywhere; OAuth with PKCE and full claim validation (`aud`/`iss`/`exp`); session in httpOnly+secure cookies, never localStorage; CSRF tokens + `SameSite=strict`; parameterized queries only; least-privilege DB roles; secrets in vault/env; dependency scanning
- **RBAC**: `voter` vs `admin` role on `users`; only admin can create/edit polls

## 5. Consistency model — CAP, applied per subsystem
Not a single global choice — different subsystems make different trade-offs:
- **Vote write path (Postgres) = CP**: on a partition, reject or queue a vote attempt rather than risk a duplicate or lost ballot. Correctness over uptime — a wrong vote can never be un-cast.
- **Live-results path (Redis + WebSocket) = AP**: on a partition, show slightly stale numbers rather than block voting. Uptime over freshness — it self-heals via reconciliation against Postgres.

## 6. Scalability techniques
- Stateless services (vote, aggregator, gateway) horizontally scaled behind a load balancer
- Sharded Redis counters per option (write to a random shard, sum on read) to avoid hot-key contention on a viral poll
- Idempotent aggregator survives at-least-once queue delivery
- Pub/sub backplane for realtime fan-out, so no single WebSocket server is a bottleneck
- Postgres read replicas / sharding by `poll_id` — described now, implemented in Phase 7

## 7. Reliability & failure modes
| If this fails | System's response |
|---|---|
| A service instance crashes | Health checks + LB route around it, auto-restart — stateless, no data loss |
| Redis dies entirely | Results service falls back to `COUNT()` from Postgres — slower, still correct |
| Queue backs up | Vote writes still succeed synchronously; only aggregation lags |
| Postgres primary fails | Standby replica promotes automatically (Phase 7) |
| WebSocket gateway down | Client falls back to polling a REST endpoint |
| Aggregator crashes mid-batch | Consumer offsets + idempotent dedupe resume safely, no double count |

## 8. Tech stack
Python + FastAPI · PostgreSQL · Redis (Streams for MVP, Kafka/Redpanda in Phase 7) · FastAPI native WebSockets (SSE fallback) · React or plain HTML/JS frontend · Docker Compose for local dev · Prometheus + Grafana for observability · Locust for load testing.

## 9. Build roadmap
1. Lock scope & schema
2. Scaffold & auth (OAuth + own JWT)
3. Walking skeleton — vote straight to Postgres, synchronous `COUNT()` result, no queue yet
4. Event-driven + live results — add queue, aggregator, sharded Redis, WebSocket
5. Harden security — rate limits, CSRF, hash-chained ballots
6. Test & document — load test, chaos test, README
7. Production-depth (post-MVP) — Kafka/Redpanda swap, Postgres replication, Redis Sentinel, phone verification, scripted chaos testing, scoped multi-region deploy (two app instances via Fly.io, one central DB)

## 10. Open decisions
- Exact API endpoint contracts — define in phase 2/3
- Frontend framework — leaning React, not locked
- Public demo deploy target — Fly.io / Railway / Render, not chosen

## 11. Interview talking points
Why an internal JWT layer instead of passing Google's token around · idempotency as the exactly-once mechanism · CAP applied per subsystem, not globally · ballot-secrecy schema (no ballots-to-user join is possible) · hash-chained tamper-evident ledger · hot-key mitigation via counter sharding · the failure-mode table above · real throughput numbers from an actual load test.
