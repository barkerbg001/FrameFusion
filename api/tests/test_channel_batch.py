import pytest
from app.services.channel_batch import (
    iter_channel_folders,
    list_image_files,
    render_channel_batch,
)
from app.services.media_utils import resolve_resolution


def test_resolve_resolution_landscape():
    assert resolve_resolution("landscape") == (1920, 1080)


def test_resolve_resolution_invalid():
    with pytest.raises(ValueError, match="Unsupported orientation"):
        resolve_resolution("square")


def test_list_image_files(tmp_path):
    (tmp_path / "a.png").write_bytes(b"png")
    (tmp_path / "b.txt").write_text("skip")

    files = list_image_files(tmp_path)
    assert len(files) == 1
    assert files[0].endswith("a.png")


def test_iter_channel_folders(tmp_path):
    (tmp_path / "set-a").mkdir()
    (tmp_path / "set-b").mkdir()
    (tmp_path / "notes.txt").write_text("skip")

    folders = iter_channel_folders(tmp_path)
    assert [folder.name for folder in folders] == ["set-a", "set-b"]


def test_render_channel_batch_requires_audio_for_slideshow(tmp_path):
    channel = tmp_path / "channel"
    folder = channel / "clip-1"
    folder.mkdir(parents=True)
    (folder / "a.png").write_bytes(b"png")

    with pytest.raises(ValueError, match="audio_path is required"):
        render_channel_batch(
            channel_root=str(channel),
            output_root=str(tmp_path / "out"),
            render_type="slideshow",
        )
