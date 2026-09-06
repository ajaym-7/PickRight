# Voting Platform — Project Scope (v1)

## Goal
A large-scale, secure voting platform designed for practicing distributed-systems thinking and as an interview-ready portfolio project — not for running a real election.

## Core requirements
- OAuth (Google) login only — no anonymous voting
- One vote per user per poll, enforced at the database level
- Live results, updated in real time as votes come in
- Ballot secrecy — no stored link between a voter's identity and their choice
- Tamper-evident ballot log (hash-chained)
- Designed to scale; graceful degradation under partial failure

## Tech stack
- Backend: Python + FastAPI
- Database: PostgreSQL
- Cache / counters / event stream: Redis (Redis Streams)
- Realtime delivery: FastAPI WebSockets (SSE fallback)
- Frontend: React (or plain HTML/JS)
- Local dev: Docker Compose

## MVP — what actually gets built
- [ ] Google OAuth login → short-lived JWT issued by our own auth layer
- [ ] Poll creation (admin role) and voting (voter role)
- [ ] Vote submission with a client-supplied idempotency key, eligibility/ballots split schema
- [ ] Phase A: synchronous walking-skeleton results (`SELECT COUNT`)
- [ ] Phase B: event-driven live results — Redis Streams → aggregator → sharded Redis counters → WebSocket
- [ ] Periodic reconciliation job (Redis counts vs. Postgres, the source of truth)
- [ ] Hash-chained ballots + a background integrity checker
- [ ] Rate limiting, CSRF protection, CAPTCHA on vote submission
- [ ] Health checks, structured logs, a `/metrics` endpoint
- [ ] Load test (Locust) for real throughput numbers
- [ ] README documenting the architecture and trade-offs

## Explicitly out of scope (discuss, don't build)
- A real Kafka cluster — Redis Streams stands in locally; Kafka is the stated production answer
- Postgres read replicas / sharding — described, not implemented
- Redis Sentinel/Cluster HA — Redis is treated as a disposable, rebuildable cache
- Multi-region / multi-AZ deployment
- Phone-verification identity binding — domain-restricted OAuth is enough for a demo
- Automated chaos engineering — one manual "kill a container and observe recovery" test is enough

## Definition of done
1. A user logs in with Google, votes once, and a duplicate attempt is rejected
2. A second open browser tab sees results update live
3. README explains the CP/AP split, the ballot-secrecy schema, and walks through one failure mode
