# Project instructions

Read README.md and docs/HANDOFF.md before changing the project. Documentation is in Russian; keep the interface and user-facing instructions in Russian.

## Commands

- Node.js 24 is the tested runtime; there are no external npm dependencies.
- Test: `node --test`.
- Start: `npm start` (loopback port 3080).
- Never use live CDEK API calls as unit tests. Existing tests use mocks and temporary files.

## Data and credentials

This repository is public. Keep `.env`, `data/`, passwords, tokens, private keys and console links with access tokens out of commits, logs, issues and Actions artifacts. See docs/SECRETS.md for the names of the repository secrets. GitHub does not reveal their stored values to an agent.

Preserve all order fields and cabinet snapshots during imports. Do not replace real orders with demo data. The CDEK API needs known waybill numbers or UUIDs; webhooks discover new numbers but do not reconstruct the historical archive.

## Deployment status

No successful SSH login or remote deployment has been confirmed. HTTPS and the CDEK webhook subscription are not configured. Do not describe the project as deployed until verified. Keep the dashboard bound to loopback until authenticated public access is implemented; exposing its current `/api/state` endpoint would expose order data.

Run tests for source changes. Keep docs/HANDOFF.md current when deployment or integration status changes.
