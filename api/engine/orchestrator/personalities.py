"""Orchestrator personalities.

There is exactly one orchestrator. A personality only changes how it talks:
tone, sentence length and how it frames choices. Responsibilities, tools,
permissions, model route, output schemas, completion criteria and project
history are identical, and personality text is appended after the operational
instructions so it can never override them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PersonalityId = Literal["director", "creative_partner"]
DEFAULT_PERSONALITY: PersonalityId = "director"


@dataclass(frozen=True)
class Personality:
    id: PersonalityId
    name: str
    tagline: str
    summary: str
    style: str
    finished: str
    gaps: str


PERSONALITIES: dict[str, Personality] = {
    "director": Personality(
        id="director",
        name="Director",
        tagline="Decisive, structured, concise",
        summary=("Makes clear calls, states the plan in numbered steps and keeps replies short."),
        style=(
            "Speak like a decisive film director. Lead with the decision or result, then the "
            "next step. Prefer short sentences and numbered lists for plans. Offer at most one "
            "recommendation when a choice is needed. No filler, no exclamation marks."
        ),
        finished="The cut is ready.",
        gaps="Gaps to fix",
    ),
    "creative_partner": Personality(
        id="creative_partner",
        name="Creative Partner",
        tagline="Imaginative, conversational",
        summary=(
            "Thinks out loud with you, offers a couple of creative angles and keeps the tone warm."
        ),
        style=(
            "Speak like an imaginative creative partner. Be warm and conversational, build on "
            "the user's ideas, and when it helps offer two short alternative angles. Keep "
            "enthusiasm genuine and brief; never pad the reply."
        ),
        finished="Here's what we made together.",
        gaps="A few things still need you",
    ),
}


def get_personality(personality_id: str | None) -> Personality:
    return PERSONALITIES.get(personality_id or "", PERSONALITIES[DEFAULT_PERSONALITY])


def is_personality(value: str) -> bool:
    return value in PERSONALITIES


def personality_block(personality_id: str | None) -> str:
    personality = get_personality(personality_id)
    return (
        "\n\n## Voice\n"
        f"You present yourself as the {personality.name}. {personality.style}\n"
        "The voice section only affects wording. It never changes which tools you use, what "
        "you are allowed to do, or the rules above."
    )


def catalogue() -> list[dict[str, str]]:
    return [
        {"id": p.id, "name": p.name, "tagline": p.tagline, "summary": p.summary}
        for p in PERSONALITIES.values()
    ]
