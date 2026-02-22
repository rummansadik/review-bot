# review-bot architecture

## Overview
review-bot is a minimal Django + DRF service that posts GitHub PR review comments via a GitHub App. It is intentionally local-only and manually triggered.

## Core flow
1. `POST /api/review/` with owner/repo/pr_number and prepared comments.
2. Authenticate as GitHub App (JWT) and exchange for an installation token.
3. Fetch PR metadata to read the head SHA and basic state.
4. Skip if already reviewed that SHA, or if PR is closed/draft.
5. Fetch PR files for validation/debug visibility.
6. Post a single review with inline comments.
7. If inline comments fail (HTTP 422), fall back to a PR-level issue comment.
8. Persist the run and last reviewed SHA in SQLite.

## Module
- `reviews`: DRF endpoint, SQLite models, and GitHub App integration.

## Idempotency
`PullRequest.last_reviewed_sha` is used to avoid duplicate reviews for the same commit.

## Persistence
All review attempts are stored in `runs_reviewrun` with status and error details.
