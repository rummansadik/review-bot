from __future__ import annotations

from typing import Any

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ReviewRun
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
                input_comments=comments,
                idempotency_key=idempotency_key,
            )
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

        if not run.input_comments:
            return Response(
                {"status": ReviewRun.Status.FAILED, "error": "no input comments available for retry"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        retry_run = ReviewRun.objects.create(
            pull_request=run.pull_request,
            status=ReviewRun.Status.QUEUED,
            input_comments=run.input_comments,
        )
        retry_run = execute_review_run(
            run=retry_run,
            owner=run.pull_request.repository.owner,
            repo=run.pull_request.repository.name,
            pr_number=run.pull_request.number,
            comments=run.input_comments,
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
        payload = {
            "run_id": run.id,
            "input_comments": run.input_comments,
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
        files = run.reviewed_files or []
        offset = validated["offset"]
        limit = validated["limit"]
        payload = {
            "run_id": run.id,
            "head_sha": run.head_sha,
            "count": len(files),
            "results": files[offset : offset + limit],
        }
        serializer = ReviewRunChangesSerializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


class LegacyReviewPRView(APIView):
    """
    Backward-compatible endpoint. Prefer /api/v1/review-runs/.
    """

    def post(self, request, *args, **kwargs):
        serializer = ReviewRunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            validate_github_config()
        except GithubConfigError as exc:
            return Response(
                {"status": "error", "error": exc.message},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        run = ReviewRun.objects.create(
            pull_request=get_or_create_pull_request(
                owner=payload["owner"],
                repo=payload["repo"],
                pr_number=payload["pr_number"],
            ),
            status=ReviewRun.Status.QUEUED,
            input_comments=payload["comments"],
        )
        run = execute_review_run(
            run=run,
            owner=payload["owner"],
            repo=payload["repo"],
            pr_number=payload["pr_number"],
            comments=payload["comments"],
        )
        return _legacy_response(run)


def _get_run(run_id) -> ReviewRun:
    return get_object_or_404(
        ReviewRun.objects.select_related("pull_request__repository"),
        id=run_id,
    )


def _legacy_response(run: ReviewRun) -> Response:
    if run.status == ReviewRun.Status.SUCCESS:
        payload: dict[str, Any] = {
            "status": "success",
            "reviewed_sha": run.head_sha,
            "comments_posted": run.comments_posted,
        }
        if run.fallback_used:
            payload["fallback"] = True
        return Response(payload, status=status.HTTP_200_OK)

    if run.status == ReviewRun.Status.SKIPPED:
        return Response(
            {"status": "skipped", "reason": run.error or "skipped"},
            status=status.HTTP_200_OK,
        )

    if run.upstream_status_code in {401, 403}:
        status_code = status.HTTP_401_UNAUTHORIZED
    elif run.upstream_status_code == 404:
        status_code = status.HTTP_404_NOT_FOUND
    elif run.upstream_status_code == 422:
        status_code = status.HTTP_400_BAD_REQUEST
    elif run.upstream_status_code:
        status_code = status.HTTP_502_BAD_GATEWAY
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    return Response(
        {"status": "error", "error": run.error or "unexpected error"},
        status=status_code,
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
