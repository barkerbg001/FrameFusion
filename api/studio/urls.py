from django.urls import path

from . import views

urlpatterns = [
    path("projects", views.ProjectListView.as_view()),
    path("projects/import-legacy", views.LegacyImportView.as_view()),
    path("projects/<uuid:project_id>", views.ProjectDetailView.as_view()),
    path("projects/<uuid:project_id>/messages", views.ProjectMessagesView.as_view()),
    path("projects/<uuid:project_id>/production", views.ProjectProductionView.as_view()),
    path("projects/<uuid:project_id>/production/rerun", views.ProjectRerunView.as_view()),
    path("projects/<uuid:project_id>/images/search", views.ProjectImageSearchView.as_view()),
    path("projects/<uuid:project_id>/images/download", views.ProjectImageDownloadView.as_view()),
    path("projects/<uuid:project_id>/images/upload", views.ProjectImageUploadView.as_view()),
    path("projects/<uuid:project_id>/images/check", views.ProjectImageCheckView.as_view()),
    path(
        "projects/<uuid:project_id>/scenes/<int:scene_index>/image",
        views.ProjectSceneImageView.as_view(),
    ),
    path("jobs", views.JobListView.as_view()),
    path("jobs/<uuid:job_id>", views.JobDetailView.as_view()),
    path("jobs/<uuid:job_id>/cancel", views.JobCancelView.as_view()),
    path("jobs/<uuid:job_id>/retry", views.JobRetryView.as_view()),
    path("jobs/<uuid:job_id>/retry-narration", views.JobRetryNarrationView.as_view()),
    path("narration/preview", views.NarrationPreviewView.as_view()),
    path("narration/previews/<uuid:job_id>", views.NarrationPreviewFileView.as_view()),
    path("agents/registry", views.AgentRegistryView.as_view()),
    path("agents/status", views.AgentStatusView.as_view()),
    path("agents/<slug:slug>", views.AgentJobView.as_view()),
    path("media", views.MediaListView.as_view()),
    path("media/<uuid:asset_id>", views.MediaDetailView.as_view()),
    path("media/<uuid:asset_id>/file", views.MediaFileView.as_view()),
    path("chat/health", views.HealthView.as_view()),
    path("chat/videos", views.LegacyVideoListView.as_view()),
    path("chat/videos/<str:file_name>", views.LegacyFileView.as_view()),
    path("chat/audio/<str:file_name>", views.LegacyFileView.as_view()),
]
