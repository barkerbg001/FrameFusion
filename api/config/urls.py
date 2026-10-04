from django.urls import include, path

urlpatterns = [
    path("api/", include("providers.urls")),
    path("api/", include("studio.urls")),
    path("api/", include("tools.urls")),
]
