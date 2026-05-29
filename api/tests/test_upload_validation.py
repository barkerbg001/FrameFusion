import pytest
from app.core.errors import AppError
from app.core.upload_validation import validate_image_count, validate_media_type


def test_validate_media_type_accepts_image():
    validate_media_type("image/png", "image", "Image")


def test_validate_media_type_rejects_non_image():
    with pytest.raises(AppError) as exc:
        validate_media_type("text/plain", "image", "Image")

    assert exc.value.status_code == 422
    assert exc.value.code == "invalid_media_type"
    assert "image/*" in exc.value.message


def test_validate_image_count_limits():
    validate_image_count(1, 10)
    validate_image_count(10, 10)

    with pytest.raises(AppError) as exc:
        validate_image_count(0, 10)
    assert exc.value.status_code == 422
    assert exc.value.code == "validation_error"

    with pytest.raises(AppError) as exc:
        validate_image_count(11, 10)
    assert exc.value.code == "too_many_images"
    assert "Too many images" in exc.value.message
