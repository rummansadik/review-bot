import uuid

from django.db import models


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
        SUCCESS = "success", "Success"
        SKIPPED = "skipped", "Skipped"
        ERROR = "error", "Error"

    pull_request = models.ForeignKey(PullRequest, on_delete=models.CASCADE)
    head_sha = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.pull_request} - {self.status}"
