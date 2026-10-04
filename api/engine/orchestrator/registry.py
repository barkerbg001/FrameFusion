"""What the Agents page shows: one orchestrator, its specialists and services."""

from __future__ import annotations

from typing import Any

from engine.llm import AGENT_ROUTES, ROUTE_LABELS
from engine.orchestrator.personalities import catalogue

SPECIALISTS: list[dict[str, Any]] = [
    {
        "id": "research",
        "name": "Research specialist",
        "role": "Verifies facts with Wikipedia, weather, time and Pokemon data.",
        "tools": [
            "search_wikipedia_tool",
            "get_weather_tool",
            "get_current_time_tool",
            "get_pokemon_tool",
        ],
        "produces": "Research report with citations",
    },
    {
        "id": "script",
        "name": "Script specialist",
        "role": "Writes the narration and plans scenes with a visual and an image query each.",
        "tools": [],
        "produces": "Script with scenes",
    },
    {
        "id": "visual",
        "name": "Visual specialist",
        "role": "Searches, inspects and downloads one real image per scene and records licences.",
        "tools": [
            "search_images",
            "inspect_image_candidate",
            "download_image",
            "assign_scene_image",
            "list_project_assets",
        ],
        "produces": "Scene-to-image map with gaps",
    },
    {
        "id": "ideas",
        "name": "Ideas specialist",
        "role": "Brainstorms distinct short-video ideas on request.",
        "tools": [],
        "produces": "Idea list",
    },
    {
        "id": "music_composer",
        "name": "Music specialist",
        "role": "Composes a standalone music track when you ask for one.",
        "tools": [],
        "produces": "Audio track",
    },
]

SERVICES: list[dict[str, str]] = [
    {
        "id": "narration",
        "name": "Narration",
        "role": "Records the voiceover with Edge TTS (online, free) or ElevenLabs (credits).",
    },
    {
        "id": "music",
        "name": "Music bed",
        "role": "Generates a simple procedural background track when the brief asks for music.",
    },
    {
        "id": "renderer",
        "name": "Timeline renderer",
        "role": "Cuts scenes to the narration timing and renders a 1080x1920 MP4.",
    },
    {
        "id": "qc",
        "name": "Quality check",
        "role": "Re-opens the video and checks resolution, duration, audio and scene images.",
    },
]


def list_agents() -> dict[str, Any]:
    return {
        "orchestrator": {
            "id": "orchestrator",
            "name": "Orchestrator",
            "role": (
                "Talks with you, writes the brief, delegates to specialists, checks every "
                "artifact and assembles the video."
            ),
            "route": AGENT_ROUTES["orchestrator"],
            "route_label": ROUTE_LABELS[AGENT_ROUTES["orchestrator"]],
            "tools": [
                "get_project_status",
                "delegate_research",
                "brainstorm_ideas",
                "plan_video",
                "produce_video",
                "list_project_assets",
            ],
            "personalities": catalogue(),
        },
        "specialists": [
            {
                **spec,
                "reports_to": "orchestrator",
                "route": AGENT_ROUTES[spec["id"]],
                "route_label": ROUTE_LABELS[AGENT_ROUTES[spec["id"]]],
            }
            for spec in SPECIALISTS
        ],
        "services": SERVICES,
    }
