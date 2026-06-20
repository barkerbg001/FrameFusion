"""Production studio agent registry — roles, responsibilities, and implementations."""

from dataclasses import dataclass
from typing import Callable, Literal

AgentId = Literal[
    "director",
    "producer",
    "research",
    "script",
    "cinematography",
    "visual",
    "voice",
    "music_director",
    "sound_design",
    "editor",
    "renderer",
]


@dataclass(frozen=True)
class AgentRole:
    id: AgentId
    emoji: str
    name: str
    tagline: str
    responsibilities: tuple[str, ...]
    implementation: str


PRODUCTION_AGENTS: tuple[AgentRole, ...] = (
    AgentRole(
        id="director",
        emoji="🎬",
        name="Director Agent",
        tagline="Overall creative vision",
        responsibilities=(
            "Creative vision and tone",
            "Assigns tasks to specialist agents",
            "Final approval",
        ),
        implementation="director_agent",
    ),
    AgentRole(
        id="producer",
        emoji="📋",
        name="Producer Agent",
        tagline="Workflow management",
        responsibilities=(
            "Workflow management",
            "Deadlines and phases",
            "Asset tracking",
        ),
        implementation="workflow_agent",
    ),
    AgentRole(
        id="research",
        emoji="🔍",
        name="Research Agent",
        tagline="Facts and references",
        responsibilities=(
            "Verified facts",
            "References and citations",
            "Source material",
        ),
        implementation="researcher_agent",
    ),
    AgentRole(
        id="script",
        emoji="✍️",
        name="Script Agent",
        tagline="Story and hooks",
        responsibilities=(
            "Script writing",
            "Hooks and pacing",
            "Storytelling",
        ),
        implementation="screenwriter_agent",
    ),
    AgentRole(
        id="cinematography",
        emoji="📷",
        name="Cinematography Agent",
        tagline="Shots and composition",
        responsibilities=(
            "Shot lists",
            "Camera movements",
            "Scene composition",
        ),
        implementation="cinematography_agent",
    ),
    AgentRole(
        id="visual",
        emoji="🎨",
        name="Visual Agent",
        tagline="Look and assets",
        responsibilities=(
            "Background and b-roll direction",
            "Visual style",
            "Asset requirements",
        ),
        implementation="visual_agent",
    ),
    AgentRole(
        id="voice",
        emoji="🎤",
        name="Voice Agent",
        tagline="Narration and delivery",
        responsibilities=(
            "Narration plan",
            "Voice selection",
            "Delivery style",
        ),
        implementation="voice_agent",
    ),
    AgentRole(
        id="music_director",
        emoji="🎼",
        name="Music Director Agent",
        tagline="Score and mood",
        responsibilities=(
            "Music style per scene",
            "Mood and tempo direction",
            "Prompts for music generation",
            "Track transition notes",
        ),
        implementation="music_director_agent",
    ),
    AgentRole(
        id="sound_design",
        emoji="🔊",
        name="Sound Design Agent",
        tagline="SFX and mix",
        responsibilities=(
            "Sound effects",
            "Ambient sound layers",
            "Audio mixing suggestions",
        ),
        implementation="sound_design_agent",
    ),
    AgentRole(
        id="editor",
        emoji="✂️",
        name="Editor Agent",
        tagline="Assembly and timing",
        responsibilities=(
            "Video assembly",
            "Timing and pacing",
            "Cuts and transitions",
        ),
        implementation="video_editor_agent",
    ),
    AgentRole(
        id="renderer",
        emoji="🎞️",
        name="Render Agent",
        tagline="Fast script-to-video",
        responsibilities=(
            "Direct script rendering",
            "Single-pass MP4 output",
        ),
        implementation="producer_agent",
    ),
)

AGENT_BY_ID: dict[AgentId, AgentRole] = {agent.id: agent for agent in PRODUCTION_AGENTS}

PIPELINE_ORDER: tuple[AgentId, ...] = (
    "director",
    "producer",
    "research",
    "script",
    "cinematography",
    "visual",
    "voice",
    "music_director",
    "sound_design",
    "editor",
)


def list_agents() -> list[dict[str, object]]:
    return [
        {
            "id": agent.id,
            "emoji": agent.emoji,
            "name": agent.name,
            "tagline": agent.tagline,
            "responsibilities": list(agent.responsibilities),
            "implementation": agent.implementation,
        }
        for agent in PRODUCTION_AGENTS
    ]
