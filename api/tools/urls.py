from django.urls import path

from . import views

urlpatterns = [
    path("pexels/photos/search", views.PexelsView.as_view(mode="photos")),
    path("pexels/videos/search", views.PexelsView.as_view(mode="videos")),
    path("pexels/search", views.PexelsView.as_view(mode="both")),
    path("pokemon/<str:identifier>", views.PokemonView.as_view()),
    path("weather", views.WeatherView.as_view()),
    path("time", views.TimeView.as_view()),
    path("wikipedia/search", views.WikipediaView.as_view()),
    path("shorts/generate-text-video", views.TextVideoView.as_view()),
    path("shorts/generate-audio-video", views.AudioVideoView.as_view()),
    path("shorts/generate-sound-video", views.SoundVideoView.as_view()),
    path("lofi/generate-video", views.LofiView.as_view()),
    path("video-producer/text-short", views.ProducerTextShortView.as_view()),
    path("video-producer/sound-short", views.ProducerSoundShortView.as_view()),
]
