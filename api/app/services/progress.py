from __future__ import annotations

from collections.abc import Callable

from proglog import ProgressBarLogger


class EncodeProgressLogger(ProgressBarLogger):
    """MoviePy/proglog logger that maps frame encoding to a progress percentage."""

    def __init__(
        self,
        on_progress: Callable[[float], None],
        *,
        progress_range: tuple[float, float] = (5.0, 95.0),
        min_report_interval: float = 0.5,
    ) -> None:
        super().__init__(logged_bars=(), min_time_interval=min_report_interval)
        self.on_progress = on_progress
        self.progress_start, self.progress_end = progress_range
        self._last_reported = -1.0

    def bars_callback(self, bar: str, attr: str, value: object, old_value: object = None) -> None:
        if attr != "index":
            return

        bar_info = self.bars.get(bar)
        if bar_info is None:
            return

        total = bar_info.get("total")
        index = bar_info.get("index")
        if total in (None, 0) or index is None or index < 0:
            return

        fraction = min(1.0, (index + 1) / total)
        progress = self.progress_start + fraction * (self.progress_end - self.progress_start)
        if progress - self._last_reported < 0.5 and progress < self.progress_end:
            return

        self._last_reported = progress
        self.on_progress(progress)
