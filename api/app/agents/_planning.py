"""Shared helpers for production-studio planning agents."""

import json
from typing import Any


def format_context(context: str | None) -> str:
    if context and context.strip():
        return f"\nContext:\n{context.strip()}\n"
    return ""


def format_research_block(research: dict[str, Any] | None) -> str:
    if not research:
        return "No prior research was supplied."
    return f"""
Research summary: {research.get("summary", "")}

Verified facts:
{json.dumps(research.get("verified_facts", []), indent=2)}

Content hooks:
{json.dumps(research.get("content_hooks", []), indent=2)}

Visual suggestions:
{json.dumps(research.get("visual_suggestions", []), indent=2)}

Limitations:
{json.dumps(research.get("limitations", []), indent=2)}
"""


def format_script_block(script: dict[str, Any] | None) -> str:
    if not script:
        return "No script was supplied."
    return f"""
Script:
{script.get("short_video_script", "")}

Style notes:
{json.dumps(script.get("style_notes", []), indent=2)}
"""
