from unittest.mock import patch

from app.services.slideshow import create_slideshow

from .conftest import requires_ffmpeg


@requires_ffmpeg
def test_create_slideshow(test_image, test_audio, output_dir, fixtures_dir):
    second_image = fixtures_dir / "second.png"
    second_image.write_bytes(test_image.read_bytes())

    output_file = create_slideshow(
        image_paths=[str(test_image), str(second_image)],
        audio_path=str(test_audio),
        output_path=str(output_dir),
        output_name="slideshow.mp4",
        target_duration_seconds=2.0,
    )

    assert output_file.endswith("slideshow.mp4")
    assert output_file.startswith(str(output_dir))


def test_create_slideshow_calls_write_video(test_image, test_audio, output_dir, tmp_path):
    with patch(
        "app.services.slideshow.write_video_file",
        return_value=str(tmp_path / "out.mp4"),
    ) as mock_write:
        with patch("app.services.slideshow.concatenate_videoclips") as mock_concat:
            mock_concat.return_value.with_audio.return_value = mock_concat.return_value
            create_slideshow(
                image_paths=[str(test_image)],
                audio_path=str(test_audio),
                output_path=str(output_dir),
                output_name="slideshow.mp4",
                target_duration_seconds=2.0,
            )

    mock_write.assert_called_once()
