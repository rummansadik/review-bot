# API reference

Base path: `/api`

## POST /api/v1/review-runs/

Create and execute a review run.

Request:
```json
{
  "owner": "octo-org",
  "repo": "backend-service",
  "pr_number": 128,
  "idempotency_key": "run-20260222-001",
  "comments": [
    {
      "path": "src/payments/service.py",
      "line": 87,
      "body": "Handle timeout exceptions explicitly.",
      "side": "RIGHT"
    }
  ]
}
```

Response (`201`):
```json
{
  "id": "uuid",
  "owner": "octo-org",
  "repo": "backend-service",
  "pr_number": 128,
  "status": "success",
  "head_sha": "abc123",
  "idempotency_key": "run-20260222-001",
  "comments_posted": 1,
  "fallback_used": false,
  "error": "",
  "error_code": "",
  "upstream_status_code": null,
  "created_at": "2026-02-22T23:10:00Z",
  "started_at": "2026-02-22T23:10:00Z",
  "finished_at": "2026-02-22T23:10:01Z"
}
```

## GET /api/v1/review-runs/

List review runs.

Query params:
- `owner`
- `repo`
- `pr_number`
- `status` (`queued`, `running`, `success`, `skipped`, `failed`, `canceled`)
- `limit` (default `20`, max `100`)
- `offset` (default `0`)

## GET /api/v1/review-runs/{run_id}/

Fetch one review run by ID.

## POST /api/v1/review-runs/{run_id}/retry/

Retry an existing run using stored comments.

Request:
```json
{
  "force": false
}
```

## POST /api/v1/review-runs/{run_id}/cancel/

Cancel a queued/running run.

## GET /api/v1/review-runs/{run_id}/comments/

Return requested comments and fallback-comment metadata.

## GET /api/v1/review-runs/{run_id}/changes/

Return reviewed PR file snapshots captured during execution.

Query params:
- `limit` (default `100`, max `500`)
- `offset` (default `0`)

## Legacy endpoint

`POST /api/review/` remains available for backward compatibility.
