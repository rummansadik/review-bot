# review-bot architecture

## Overview
review-bot is a Django + DRF service that posts GitHub PR review comments via a GitHub App.

## API design
- Command endpoint: `POST /api/v1/review-runs/`
- Query endpoints:
  - `GET /api/v1/review-runs/`
  - `GET /api/v1/review-runs/{run_id}/`
  - `GET /api/v1/review-runs/{run_id}/comments/`
  - `GET /api/v1/review-runs/{run_id}/changes/`
- Control endpoints:
  - `POST /api/v1/review-runs/{run_id}/retry/`
  - `POST /api/v1/review-runs/{run_id}/cancel/`

## Module
- `reviews`: DRF endpoint, SQLite models, and GitHub App integration.

## Data model
- `ReviewRun`: run lifecycle/status and execution metadata.
- `ReviewRunComment`: normalized requested inline comments per run.
- `ReviewRunFile`: normalized reviewed file snapshots per run.

## Lifecycle
- `queued` -> `running` -> `success | skipped | failed`
- `canceled` can be set before terminal completion.

## Idempotency and dedupe
- `PullRequest.last_reviewed_sha` avoids duplicate reviews for the same commit by default.
- Optional `idempotency_key` is supported on create requests and deduped per pull request.

## Persistence
All review attempts are stored in `reviews_reviewrun`. Requested comments and reviewed file snapshots are stored in dedicated relational tables for queryability and scale.
