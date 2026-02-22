from django.urls import path

from .views import (
    ReviewRunCancelView,
    ReviewRunChangesView,
    ReviewRunCollectionView,
    ReviewRunCommentsView,
    ReviewRunDetailView,
    ReviewRunRetryView,
)

urlpatterns = [
    path("v1/review-runs/", ReviewRunCollectionView.as_view(), name="review-run-collection"),
    path("v1/review-runs/<uuid:run_id>/", ReviewRunDetailView.as_view(), name="review-run-detail"),
    path("v1/review-runs/<uuid:run_id>/retry/", ReviewRunRetryView.as_view(), name="review-run-retry"),
    path("v1/review-runs/<uuid:run_id>/cancel/", ReviewRunCancelView.as_view(), name="review-run-cancel"),
    path("v1/review-runs/<uuid:run_id>/comments/", ReviewRunCommentsView.as_view(), name="review-run-comments"),
    path("v1/review-runs/<uuid:run_id>/changes/", ReviewRunChangesView.as_view(), name="review-run-changes"),
]
