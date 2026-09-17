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

Production runs on REG Cloud VPS 194.58.102.218 at https://snowbrick.ru (REG_VPS_DOMAIN). HTTPS, form login/logout, and 20 API orders with 20 cabinet snapshots were verified on 2026-09-17. www redirects to the primary domain. Read docs/HANDOFF.md and docs/AUTH.md. Keep Node bound to loopback and require authenticated public access; /api/state contains personal order data. Production authentication must fail closed when configuration is incomplete. The legacy Cloud4box server and its webhook subscription remain unchanged. Never put dashboard credentials in commits or logs.

Run tests for source changes. Keep docs/HANDOFF.md current when deployment or integration status changes.
