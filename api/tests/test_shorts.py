from unittest.mock import patch

from app.services.shorts import create_shorts

from .conftest import requires_ffmpeg


@requires_ffmpeg
def test_create_shorts(test_image, test_audio, output_dir, fixtures_dir):
    second_image = fixtures_dir / "second.png"
    second_image.write_bytes(test_image.read_bytes())

    output_file = create_shorts(
        image_paths=[str(test_image), str(second_image)],
        output_path=str(output_dir),
        output_name="short.mp4",
        audio_path=str(test_audio),
        seconds_per_image=0.5,
        shuffle=False,
        max_duration_seconds=1.0,
        orientation="portrait",
    )

    assert output_file.endswith("short.mp4")


def test_create_shorts_without_audio(test_image, output_dir, tmp_path):
    with patch(
        "app.services.shorts.write_video_file",
        return_value=str(tmp_path / "short.mp4"),
    ) as mock_write:
        with patch("app.services.shorts.concatenate_videoclips") as mock_concat:
            mock_concat.return_value.duration = 1.0
            create_shorts(
                image_paths=[str(test_image)],
                output_path=str(output_dir),
                output_name="short.mp4",
                shuffle=False,
            )

    mock_write.assert_called_once()
