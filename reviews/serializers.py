from rest_framework import serializers

from .models import ReviewRun


class ReviewCommentInputSerializer(serializers.Serializer):
    path = serializers.CharField(max_length=500)
    line = serializers.IntegerField(min_value=1)
    body = serializers.CharField()
    side = serializers.ChoiceField(choices=["RIGHT", "LEFT"], required=False)


class ReviewRunCreateSerializer(serializers.Serializer):
    owner = serializers.CharField(max_length=100)
    repo = serializers.CharField(max_length=100)
    pr_number = serializers.IntegerField(min_value=1)
    comments = ReviewCommentInputSerializer(many=True, allow_empty=False)
    idempotency_key = serializers.CharField(max_length=128, required=False, allow_blank=False)


class ReviewRunListQuerySerializer(serializers.Serializer):
    owner = serializers.CharField(max_length=100, required=False)
    repo = serializers.CharField(max_length=100, required=False)
    pr_number = serializers.IntegerField(min_value=1, required=False)
    status = serializers.ChoiceField(choices=ReviewRun.Status.values, required=False)
    limit = serializers.IntegerField(min_value=1, max_value=100, required=False, default=20)
    offset = serializers.IntegerField(min_value=0, required=False, default=0)


class ReviewRunRetrySerializer(serializers.Serializer):
    force = serializers.BooleanField(required=False, default=False)


class ReviewRunDetailSerializer(serializers.ModelSerializer):
    owner = serializers.CharField(source="pull_request.repository.owner", read_only=True)
    repo = serializers.CharField(source="pull_request.repository.name", read_only=True)
    pr_number = serializers.IntegerField(source="pull_request.number", read_only=True)

    class Meta:
        model = ReviewRun
        fields = [
            "id",
            "owner",
            "repo",
            "pr_number",
            "status",
            "head_sha",
            "idempotency_key",
            "comments_posted",
            "fallback_used",
            "error",
            "error_code",
            "upstream_status_code",
            "created_at",
            "started_at",
            "finished_at",
        ]


class ReviewRunCommentsSerializer(serializers.Serializer):
    run_id = serializers.UUIDField()
    input_comments = ReviewCommentInputSerializer(many=True)
    comments_posted = serializers.IntegerField()
    fallback_used = serializers.BooleanField()
    fallback_comment_body = serializers.CharField(allow_blank=True)


class ReviewRunChangesSerializer(serializers.Serializer):
    run_id = serializers.UUIDField()
    head_sha = serializers.CharField(allow_blank=True)
    count = serializers.IntegerField()
    results = serializers.ListField(child=serializers.DictField())
