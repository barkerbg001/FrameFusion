import pytest
from app.services.media_utils import loop_audio_to_duration


def test_loop_audio_to_duration(monkeypatch: pytest.MonkeyPatch):
    class FakeAudio:
        duration = 2.0

        def __init__(self, path: str) -> None:
            self.path = path

        def copy(self):
            return FakeAudio(self.path)

        def subclipped(self, start: float, end: float):
            clip = FakeAudio(self.path)
            clip.duration = end - start
            return clip

    def fake_concat(clips):
        total = sum(clip.duration for clip in clips)
        merged = FakeAudio("merged")
        merged.duration = total
        return merged

    monkeypatch.setattr("app.services.media_utils.AudioFileClip", FakeAudio)
    monkeypatch.setattr("app.services.media_utils.concatenate_audioclips", fake_concat)

    result = loop_audio_to_duration("track.wav", 5.0)
    assert result.duration == 5.0
