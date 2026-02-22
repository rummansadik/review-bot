import uuid

from django.db import models
from django.db.models import Q


class UUIDPrimaryKeyModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class Repository(UUIDPrimaryKeyModel):
    owner = models.CharField(max_length=100)
    name = models.CharField(max_length=100)
    installation_id = models.BigIntegerField()

    class Meta:
        unique_together = ("owner", "name")

    def __str__(self) -> str:
        return f"{self.owner} - {self.name}"


class PullRequest(UUIDPrimaryKeyModel):
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE)
    number = models.IntegerField()
    last_reviewed_sha = models.CharField(max_length=40, null=True, blank=True)

    class Meta:
        unique_together = ("repository", "number")

    def __str__(self) -> str:
        return f"{self.repository} #{self.number}"


class ReviewRun(UUIDPrimaryKeyModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"
        CANCELED = "canceled", "Canceled"

    pull_request = models.ForeignKey(PullRequest, on_delete=models.CASCADE)
    head_sha = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED, db_index=True)
    input_comments = models.JSONField(default=list, blank=True)
    reviewed_files = models.JSONField(default=list, blank=True)
    comments_posted = models.PositiveIntegerField(default=0)
    fallback_used = models.BooleanField(default=False)
    fallback_comment_body = models.TextField(blank=True)
    error = models.TextField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    upstream_status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128, null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["pull_request", "idempotency_key"],
                condition=Q(idempotency_key__isnull=False),
                name="uniq_reviewrun_idempotency_per_pr",
            )
        ]
        indexes = [
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.pull_request} - {self.status}"
