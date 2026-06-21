# Sprint 5 — Coder Blockers (please respond before ACP runs)

**Date:** 2026-06-21
**Project:** FlowWatch (`/root/.openclaw/workspace-coder/flowwatch`)
**Last verified QA:** Sprint 4 PASS, 520/520 tests green (qa-sprint4-20260620.md)

I checked the workspace before delegating to ACP and found **three premises in the Sprint 5 task that don't match reality**. Need your decisions before I burn ACP tokens on the wrong direction.

---

## 1. Branch state — there's no `feature/sprint5-integration`

- Repo currently checked out on `feature/sprint4-dag-realtime` (working tree clean, last commit `105eed0 Sprint 4: DAG...`).
- That branch has **not been merged to `main`** — main is still at `c846f8a feat(sprint2): WebSocket trace ingestion`.
- Sprint 3 (`feature/sprint3-thresholds-alerts`) is also unmerged on the remote.

**Question:** Branch from `main` (skipping unmerged Sprints 3 & 4) or branch from `feature/sprint4-dag-realtime` (so Sprint 5 builds on Sprint 4's DAG/trace work, which is what the E2E test path probably needs)?

## 2. CI Postgres — already present

`.github/workflows/ci.yml` already has:
- `postgres:16` service on port 5432 with healthcheck
- `redis:7` service on port 6379 with healthcheck
- `alembic upgrade head` step before pytest
- 520 tests passing on this exact CI config per Sprint 4 QA

**Question:** Do you still want me to "update" CI? Options:
- (a) Leave it alone — already works.
- (b) Pin a newer postgres/redis image version.
- (c) Add a TimescaleDB service container — Sprint 2 added a TimescaleDB hypertable migration (`migrations/` / `alembic/versions/`) and the existing CI uses plain `postgres:16`. If Sprint 5 E2E touches trace storage, this gap matters.

## 3. Staging deploy — no infrastructure exists

I searched for any deploy target and found none:
- No `Procfile`, `render.yaml`, `fly.toml`, `railway.json`, `vercel.json`, `netlify.toml`.
- No `deploy/` scripts directory.
- No staging URL, no hosting account tokens in `secrets/`.
- Only `docker-compose.yml` for local dev.

**Question:** What does "deploy to staging" mean here?
- (a) Add `render.yaml` / `fly.toml` blueprint to the repo — still needs an account to actually deploy, so I'd be writing config without proof it works.
- (b) Add a `staging` profile to `docker-compose.yml` and verify it boots locally as a "staging" stand-in.
- (c) Skip the deploy part; report it as a known gap for the next sprint.
- (d) You have hosting credentials you haven't shared — paste the platform and token and I'll wire it up.

---

## Other notes

- The git remote URL in this clone embeds a GitHub PAT. I'm not going to echo or rotate it; flag if you want that rotated separately.
- My `AGENTS.md` describes an Android/Kotlin workspace (Gradle/Robolectric), but FlowWatch is Python+Node. I'm applying only the durable rules (feature branch, every-feature-gets-a-test, final report) and skipping the Android-specific bits.
- Once you answer the three questions above, I'll spawn ACP for the actual implementation, run the full backend pytest + dashboard jest, and write `sprint5-coder-report.md`.

Waiting on your call.
