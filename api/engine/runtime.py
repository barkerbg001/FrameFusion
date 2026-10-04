"""Per-run context for agents: tool results, progress reporting, cancellation.

Everything here is stored in ``contextvars`` so concurrent background jobs and
requests never share tool results or progress callbacks.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

Reporter = Callable[[str, dict[str, Any]], None]
CancelCheck = Callable[[], None]

_tool_results: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "framefusion_tool_results", default=None
)
_reporter: contextvars.ContextVar[Reporter | None] = contextvars.ContextVar(
    "framefusion_reporter", default=None
)
_cancel_check: contextvars.ContextVar[CancelCheck | None] = contextvars.ContextVar(
    "framefusion_cancel_check", default=None
)


class RunCancelled(Exception):
    """Raised inside agent code when the owning job was cancelled."""


def _results() -> list[dict[str, Any]]:
    results = _tool_results.get()
    if results is None:
        results = []
        _tool_results.set(results)
    return results


def reset_tool_results() -> None:
    _tool_results.set([])


def get_tool_results() -> list[dict[str, Any]]:
    return list(_results())


def get_tools_used() -> list[str]:
    return sorted({entry["tool"] for entry in _results()})


def record_tool_result(
    tool_name: str,
    args: dict[str, Any],
    result: Any = None,
    error: str | None = None,
    *,
    agent: str = "",
) -> None:
    entry: dict[str, Any] = {"tool": tool_name, "args": args}
    if error is not None:
        entry["error"] = error
    else:
        entry["result"] = result
    _results().append(entry)
    report("tool", tool=tool_name, ok=error is None, error=error, agent=agent)


def report(event: str, **data: Any) -> None:
    reporter = _reporter.get()
    if reporter is not None:
        reporter(event, data)


def check_cancelled() -> None:
    check = _cancel_check.get()
    if check is not None:
        check()


@contextmanager
def run_context(
    reporter: Reporter | None = None,
    cancel_check: CancelCheck | None = None,
) -> Iterator[None]:
    tokens = (
        _tool_results.set([]),
        _reporter.set(reporter),
        _cancel_check.set(cancel_check),
    )
    try:
        yield
    finally:
        _cancel_check.reset(tokens[2])
        _reporter.reset(tokens[1])
        _tool_results.reset(tokens[0])
