from app.services.progress import EncodeProgressLogger


def test_encode_progress_logger_reports_frame_progress():
    updates: list[float] = []
    logger = EncodeProgressLogger(
        updates.append,
        progress_range=(10.0, 90.0),
        min_report_interval=0,
    )

    logger(**{"frame_index__total": 100})
    logger(**{"frame_index__index": 0})
    logger(**{"frame_index__index": 49})
    logger(**{"frame_index__index": 99})

    assert updates
    assert updates[0] == 10.8
    assert updates[-1] == 90.0


def test_encode_progress_logger_ignores_non_index_updates():
    updates: list[float] = []
    logger = EncodeProgressLogger(updates.append, min_report_interval=0)

    logger(message="MoviePy - Writing video")
    assert updates == []
