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
- Legacy compatibility endpoint: `POST /api/review/`

## Module
- `reviews`: DRF endpoint, SQLite models, and GitHub App integration.

## Lifecycle
- `queued` -> `running` -> `success | skipped | failed`
- `canceled` can be set before terminal completion.

## Idempotency and dedupe
- `PullRequest.last_reviewed_sha` avoids duplicate reviews for the same commit by default.
- Optional `idempotency_key` is supported on create requests and deduped per pull request.

## Persistence
All review attempts are stored in `reviews_reviewrun` with status, timestamps, upstream error metadata, requested comments, and reviewed file snapshots.
