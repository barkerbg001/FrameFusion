from django.urls import path

from . import views

urlpatterns = [
    path("app", views.AppView.as_view()),
    path("settings/appearance", views.AppearanceView.as_view()),
    path("settings/personality", views.PersonalityView.as_view()),
    path("settings/onboarding", views.OnboardingView.as_view()),
    path("settings/providers", views.ProvidersView.as_view()),
    path("settings/providers/<str:provider>/key", views.ProviderKeyView.as_view()),
    path("settings/providers/<str:provider>/test", views.ProviderTestView.as_view()),
    path("settings/providers/<str:provider>/models", views.ProviderModelsView.as_view()),
    path("settings/ai", views.AISettingsView.as_view()),
    path("settings/media", views.MediaSettingsView.as_view()),
    path("settings/media/elevenlabs/voices", views.ElevenLabsVoicesView.as_view()),
    path("settings/media/elevenlabs/models", views.ElevenLabsModelsView.as_view()),
    path("settings/narration", views.NarrationSettingsView.as_view()),
    path("settings/narration/edge/voices", views.EdgeVoicesView.as_view()),
    path("settings/import-conflicts", views.ImportConflictsView.as_view()),
    path(
        "settings/import-conflicts/<int:choice_id>",
        views.ImportConflictResolveView.as_view(),
    ),
]
