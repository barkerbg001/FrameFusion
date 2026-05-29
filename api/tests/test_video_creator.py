import os

from app.services.video_creator import create_video_from_images_and_audio

from .conftest import requires_ffmpeg


@requires_ffmpeg
def test_create_video_from_images_and_audio(test_image, test_audio, output_dir):
    output_file = create_video_from_images_and_audio(
        image_paths=[str(test_image)],
        audio_path=str(test_audio),
        output_path=str(output_dir),
        output_name="smoke.mp4",
        repeat_minutes=60,
        target_duration_seconds=2.0,
    )

    assert os.path.isfile(output_file)
    assert os.path.getsize(output_file) > 0


def test_create_video_missing_image_raises(test_audio, output_dir, tmp_path):
    missing_image = tmp_path / "missing.png"

    try:
        create_video_from_images_and_audio(
            image_paths=[str(missing_image)],
            audio_path=str(test_audio),
            output_path=str(output_dir),
            output_name="fail.mp4",
            repeat_minutes=1,
            target_duration_seconds=1.0,
        )
    except FileNotFoundError as exc:
        assert "missing.png" in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError for missing image")
