from __future__ import annotations

from typing import Any

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ReviewRun, ReviewRunComment
from .serializers import (
    ReviewRunChangesSerializer,
    ReviewRunCommentsSerializer,
    ReviewRunCreateSerializer,
    ReviewRunDetailSerializer,
    ReviewRunListQuerySerializer,
    ReviewRunRetrySerializer,
)
from .services import GithubConfigError, execute_review_run, get_or_create_pull_request, validate_github_config

TERMINAL_STATUSES = {
    ReviewRun.Status.SUCCESS,
    ReviewRun.Status.SKIPPED,
    ReviewRun.Status.FAILED,
    ReviewRun.Status.CANCELED,
}


class ReviewRunCollectionView(APIView):
    def get(self, request, *args, **kwargs):
        query = ReviewRunListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data

        queryset = ReviewRun.objects.select_related("pull_request__repository").order_by("-created_at")
        owner = filters.get("owner")
        repo = filters.get("repo")
        pr_number = filters.get("pr_number")
        status_filter = filters.get("status")

        if owner:
            queryset = queryset.filter(pull_request__repository__owner=owner)
        if repo:
            queryset = queryset.filter(pull_request__repository__name=repo)
        if pr_number:
            queryset = queryset.filter(pull_request__number=pr_number)
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        total = queryset.count()
        limit = filters["limit"]
        offset = filters["offset"]
        runs = list(queryset[offset : offset + limit])

        next_offset = offset + limit if offset + limit < total else None
        payload = {
            "count": total,
            "limit": limit,
            "offset": offset,
            "next_offset": next_offset,
            "results": ReviewRunDetailSerializer(runs, many=True).data,
        }
        return Response(payload, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = ReviewRunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            validate_github_config()
        except GithubConfigError as exc:
            return Response(
                {"status": ReviewRun.Status.FAILED, "error": exc.message},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        owner = payload["owner"]
        repo = payload["repo"]
        pr_number = payload["pr_number"]
        comments = payload["comments"]
        idempotency_key = payload.get("idempotency_key")

        pull_request = get_or_create_pull_request(owner=owner, repo=repo, pr_number=pr_number)
        if idempotency_key:
            existing = (
                ReviewRun.objects.select_related("pull_request__repository")
                .filter(pull_request=pull_request, idempotency_key=idempotency_key)
                .order_by("-created_at")
                .first()
            )
            if existing:
                return Response(ReviewRunDetailSerializer(existing).data, status=status.HTTP_200_OK)

        try:
            run = ReviewRun.objects.create(
                pull_request=pull_request,
                status=ReviewRun.Status.QUEUED,
                idempotency_key=idempotency_key,
            )
            _create_run_comments(run, comments)
        except IntegrityError:
            # Safe retry for concurrent requests with same idempotency key.
            if not idempotency_key:
                raise
            existing = (
                ReviewRun.objects.select_related("pull_request__repository")
                .filter(pull_request=pull_request, idempotency_key=idempotency_key)
                .order_by("-created_at")
                .first()
            )
            if existing:
                return Response(ReviewRunDetailSerializer(existing).data, status=status.HTTP_200_OK)
            raise

        run = execute_review_run(
            run=run,
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            comments=comments,
        )
        return Response(ReviewRunDetailSerializer(run).data, status=status.HTTP_201_CREATED)


class ReviewRunDetailView(APIView):
    def get(self, request, run_id, *args, **kwargs):
        run = _get_run(run_id)
        return Response(ReviewRunDetailSerializer(run).data, status=status.HTTP_200_OK)


class ReviewRunRetryView(APIView):
    def post(self, request, run_id, *args, **kwargs):
        run = _get_run(run_id)
        serializer = ReviewRunRetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        force = serializer.validated_data["force"]
        source_comments = _get_run_comments(run)
        if not source_comments:
            return Response(
                {"status": ReviewRun.Status.FAILED, "error": "no input comments available for retry"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        retry_run = ReviewRun.objects.create(
            pull_request=run.pull_request,
            status=ReviewRun.Status.QUEUED,
        )
        _create_run_comments(retry_run, source_comments)
        retry_run = execute_review_run(
            run=retry_run,
            owner=run.pull_request.repository.owner,
            repo=run.pull_request.repository.name,
            pr_number=run.pull_request.number,
            comments=source_comments,
            force=force,
        )
        return Response(ReviewRunDetailSerializer(retry_run).data, status=status.HTTP_201_CREATED)


class ReviewRunCancelView(APIView):
    def post(self, request, run_id, *args, **kwargs):
        run = _get_run(run_id)
        if run.status in TERMINAL_STATUSES:
            return Response(
                {"detail": f"cannot cancel run in terminal state: {run.status}"},
                status=status.HTTP_409_CONFLICT,
            )

        run.status = ReviewRun.Status.CANCELED
        run.error = "canceled by user"
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at"])
        return Response(ReviewRunDetailSerializer(run).data, status=status.HTTP_200_OK)


class ReviewRunCommentsView(APIView):
    def get(self, request, run_id, *args, **kwargs):
        run = _get_run(run_id)
        input_comments = _get_run_comments(run)
        payload = {
            "run_id": run.id,
            "input_comments": input_comments,
            "comments_posted": run.comments_posted,
            "fallback_used": run.fallback_used,
            "fallback_comment_body": run.fallback_comment_body,
        }
        serializer = ReviewRunCommentsSerializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ReviewRunChangesView(APIView):
    def get(self, request, run_id, *args, **kwargs):
        run = _get_run(run_id)
        validated = _validate_offset_limit(request.query_params)
        offset = validated["offset"]
        limit = validated["limit"]
        files_queryset = run.reviewed_file_snapshots.order_by("position", "created_at")
        count = files_queryset.count()
        files = list(
            files_queryset[offset : offset + limit].values(
                "filename",
                "status",
                "additions",
                "deletions",
                "changes",
                "previous_filename",
                "patch",
                "position",
            )
        )
        payload = {
            "run_id": run.id,
            "head_sha": run.head_sha,
            "count": count,
            "results": files,
        }
        serializer = ReviewRunChangesSerializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


def _get_run(run_id) -> ReviewRun:
    return get_object_or_404(
        ReviewRun.objects.select_related("pull_request__repository"),
        id=run_id,
    )


def _create_run_comments(run: ReviewRun, comments: list[dict[str, Any]]) -> None:
    items = []
    for index, comment in enumerate(comments):
        items.append(
            ReviewRunComment(
                run=run,
                path=str(comment["path"]),
                line=int(comment["line"]),
                side=str(comment.get("side") or ReviewRunComment.Side.RIGHT),
                body=str(comment["body"]),
                position=index,
            )
        )
    if items:
        ReviewRunComment.objects.bulk_create(items, batch_size=200)


def _get_run_comments(run: ReviewRun) -> list[dict[str, Any]]:
    return list(
        run.requested_comments.order_by("position", "created_at").values(
            "path",
            "line",
            "side",
            "body",
            "position",
        )
    )


def _validate_offset_limit(query_params) -> dict[str, int]:
    def _to_int(name: str, default: int) -> int:
        try:
            value = int(query_params.get(name, default))
        except (TypeError, ValueError):
            value = default
        return value

    limit = _to_int("limit", 100)
    offset = _to_int("offset", 0)

    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500
    if offset < 0:
        offset = 0

    return {"limit": limit, "offset": offset}
