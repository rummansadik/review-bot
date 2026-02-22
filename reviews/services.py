from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .github_auth import get_installation_token, normalize_private_key
from .github_client import GitHubAPIError, GitHubClient
from .models import PullRequest, Repository, ReviewRun, ReviewRunFile

MAX_PATCH_CHARS = 4000


@dataclass
class GithubConfigError(Exception):
    message: str


def validate_github_config() -> None:
    missing = []
    if not settings.GITHUB_APP_ID:
        missing.append("GITHUB_APP_ID")
    if not settings.GITHUB_INSTALLATION_ID:
        missing.append("GITHUB_INSTALLATION_ID")
    if not settings.GITHUB_PRIVATE_KEY:
        missing.append("GITHUB_PRIVATE_KEY")
    if missing:
        raise GithubConfigError(f"Missing configuration: {', '.join(missing)}")
    try:
        int(settings.GITHUB_APP_ID)
        int(settings.GITHUB_INSTALLATION_ID)
    except (TypeError, ValueError) as exc:
        raise GithubConfigError("Invalid GitHub App configuration values") from exc


def get_or_create_pull_request(*, owner: str, repo: str, pr_number: int) -> PullRequest:
    installation_id = int(settings.GITHUB_INSTALLATION_ID)
    repository, _ = Repository.objects.get_or_create(
        owner=owner,
        name=repo,
        defaults={"installation_id": installation_id},
    )
    if repository.installation_id != installation_id:
        repository.installation_id = installation_id
        repository.save(update_fields=["installation_id"])

    pull_request, _ = PullRequest.objects.get_or_create(repository=repository, number=pr_number)
    return pull_request


def execute_review_run(
    *,
    run: ReviewRun,
    owner: str,
    repo: str,
    pr_number: int,
    comments: list[dict[str, Any]],
    force: bool = False,
) -> ReviewRun:
    if run.status == ReviewRun.Status.CANCELED:
        return run
    comments_payload = _normalize_comments(comments)

    run.status = ReviewRun.Status.RUNNING
    run.error = ""
    run.error_code = ""
    run.upstream_status_code = None
    run.started_at = timezone.now()
    run.finished_at = None
    run.fallback_used = False
    run.fallback_comment_body = ""
    run.comments_posted = 0
    run.save(
        update_fields=[
            "status",
            "error",
            "error_code",
            "upstream_status_code",
            "started_at",
            "finished_at",
            "fallback_used",
            "fallback_comment_body",
            "comments_posted",
        ]
    )

    try:
        token = get_installation_token(
            app_id=int(settings.GITHUB_APP_ID),
            installation_id=int(settings.GITHUB_INSTALLATION_ID),
            private_key=normalize_private_key(settings.GITHUB_PRIVATE_KEY),
            api_base=settings.GITHUB_API_BASE,
        )
        client = GitHubClient(token=token, api_base=settings.GITHUB_API_BASE)

        pr = client.get_pull(owner=owner, repo=repo, pr_number=pr_number)
        head_sha = pr["head"]["sha"]

        files = client.list_pull_files(owner=owner, repo=repo, pr_number=pr_number)
        run.head_sha = head_sha
        _replace_reviewed_files(run=run, files=files)

        if pr.get("state") != "open":
            return _finish_run(
                run=run,
                status=ReviewRun.Status.SKIPPED,
                error="pull request is closed",
            )

        if pr.get("draft"):
            return _finish_run(
                run=run,
                status=ReviewRun.Status.SKIPPED,
                error="pull request is a draft",
            )

        pull_request = run.pull_request
        if not force and pull_request.last_reviewed_sha == head_sha:
            return _finish_run(
                run=run,
                status=ReviewRun.Status.SKIPPED,
                error="already reviewed this commit",
            )

        review_response = client.create_review(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            comments=comments_payload,
        )

        fallback_used = False
        fallback_body = ""
        comments_posted = len(comments_payload)

        if review_response.status_code == 422:
            fallback_used = True
            comments_posted = 0
            fallback_body = _build_fallback_body(comments_payload)
            client.create_issue_comment(
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                body=fallback_body,
            )

        with transaction.atomic():
            pull_request.last_reviewed_sha = head_sha
            pull_request.save(update_fields=["last_reviewed_sha"])

            run.status = ReviewRun.Status.SUCCESS
            run.error = ""
            run.error_code = ""
            run.upstream_status_code = None
            run.comments_posted = comments_posted
            run.fallback_used = fallback_used
            run.fallback_comment_body = fallback_body
            run.finished_at = timezone.now()
            run.save(
                update_fields=[
                    "head_sha",
                    "status",
                    "error",
                    "error_code",
                    "upstream_status_code",
                    "comments_posted",
                    "fallback_used",
                    "fallback_comment_body",
                    "finished_at",
                ]
            )
        return run

    except GitHubAPIError as exc:
        run.error_code = "github_api_error"
        run.upstream_status_code = exc.status_code if exc.status_code > 0 else None
        return _finish_run(run=run, status=ReviewRun.Status.FAILED, error=exc.message)
    except Exception as exc:
        run.error_code = "unexpected_error"
        return _finish_run(run=run, status=ReviewRun.Status.FAILED, error=str(exc))


def _finish_run(*, run: ReviewRun, status: str, error: str) -> ReviewRun:
    run.status = status
    run.error = error
    run.finished_at = timezone.now()
    run.save(
        update_fields=[
            "head_sha",
            "status",
            "error",
            "error_code",
            "upstream_status_code",
            "finished_at",
        ]
    )
    return run


def _replace_reviewed_files(*, run: ReviewRun, files: list[dict[str, Any]]) -> None:
    run.reviewed_file_snapshots.all().delete()
    snapshots = []
    for index, item in enumerate(files):
        patch = item.get("patch")
        if isinstance(patch, str) and len(patch) > MAX_PATCH_CHARS:
            patch = patch[:MAX_PATCH_CHARS]
        snapshots.append(
            ReviewRunFile(
                run=run,
                filename=str(item.get("filename") or ""),
                status=str(item.get("status") or ""),
                additions=int(item.get("additions") or 0),
                deletions=int(item.get("deletions") or 0),
                changes=int(item.get("changes") or 0),
                previous_filename=str(item.get("previous_filename") or ""),
                patch=patch or "",
                position=index,
            )
        )
    if snapshots:
        ReviewRunFile.objects.bulk_create(snapshots, batch_size=200)


def _normalize_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": str(comment["path"]),
            "line": int(comment["line"]),
            "body": str(comment["body"]),
            "side": str(comment.get("side") or "RIGHT"),
        }
        for comment in comments
    ]


def _build_fallback_body(comments: list[dict[str, Any]]) -> str:
    lines = [
        "Inline comments could not be posted. Here are the requested comments:",
        "",
    ]
    for comment in comments:
        location = f"{comment['path']}:{comment['line']}"
        lines.append(f"- {location} - {comment['body']}")
    return "\n".join(lines)
