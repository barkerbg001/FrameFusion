"""Structured visual briefs and subject-preserving search queries.

A brief says what a scene's image must show before anything is searched. The
anchor terms (subject words and named entities) are what every query, metadata
check and relevance decision is held to, so a weak search can never drift into
"something vaguely nearby".
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Specificity = Literal["exact", "representative", "generic"]
VisualType = Literal["photograph", "illustration", "diagram", "screenshot", "background"]
EntityKind = Literal[
    "person",
    "place",
    "landmark",
    "organisation",
    "product",
    "event",
    "artwork",
    "species",
    "other",
]

MAX_QUERIES = 4

STOPWORDS = frozenset(
    """a an and are as at be by for from has have in into is it its of on or over the
    their this that these those to under with without while during about after before
    very more most some any each other such than then there here what when where which
    who whom whose why how up down out off near between through across along around""".split()
)
GENERIC_WORDS = frozenset(
    """photo photos photograph picture image images shot close closeup view scene background
    stock beautiful nice high quality hd vertical portrait landscape wide angle detail
    illustration vector graphic concept abstract""".split()
)


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


_WORD = re.compile(r"[a-z0-9][a-z0-9'-]*")


def tokens(text: str) -> list[str]:
    """Lower-case content words, lightly stemmed, without stopwords."""
    words = _WORD.findall((text or "").lower().replace("’", "'"))
    return [_stem(word.strip("'-")) for word in words if word not in STOPWORDS and len(word) > 1]


class NamedEntity(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: EntityKind = "other"

    @property
    def terms(self) -> list[str]:
        return [term for term in tokens(self.name) if term not in GENERIC_WORDS]


class BriefQuery(BaseModel):
    query: str = Field(min_length=2, max_length=100)
    rationale: str = Field(default="", max_length=200)

    @field_validator("query")
    @classmethod
    def flatten(cls, value: str) -> str:
        return " ".join(value.split())


class VisualBrief(BaseModel):
    scene_index: int = Field(ge=0)
    purpose: str = Field(default="", max_length=200)
    subject: str = Field(min_length=2, max_length=120)
    action: str = Field(default="", max_length=120)
    named_entities: list[NamedEntity] = Field(default_factory=list, max_length=4)
    specificity: Specificity = "generic"
    visual_type: VisualType = "photograph"
    orientation: Literal["portrait", "landscape", "square", "any"] = "portrait"
    min_short_side: int = Field(default=600, ge=320, le=2000)
    composition: str = Field(default="", max_length=160)
    acceptable_alternatives: list[str] = Field(default_factory=list, max_length=4)
    excluded: list[str] = Field(default_factory=list, max_length=6)
    queries: list[BriefQuery] = Field(min_length=1, max_length=MAX_QUERIES)
    narration: str = Field(default="", max_length=400)
    derived: bool = False

    @property
    def subject_terms(self) -> list[str]:
        return list(dict.fromkeys(t for t in tokens(self.subject) if t not in GENERIC_WORDS))

    @property
    def anchor_terms(self) -> list[str]:
        terms = list(self.subject_terms)
        for entity in self.named_entities:
            terms.extend(entity.terms)
        return list(dict.fromkeys(terms))

    @property
    def requires_exact(self) -> bool:
        return self.specificity == "exact"

    def summary(self) -> dict[str, Any]:
        return {
            "scene_index": self.scene_index,
            "purpose": self.purpose,
            "subject": self.subject,
            "action": self.action,
            "named_entities": [entity.model_dump() for entity in self.named_entities],
            "specificity": self.specificity,
            "visual_type": self.visual_type,
            "orientation": self.orientation,
            "min_short_side": self.min_short_side,
            "composition": self.composition,
            "acceptable_alternatives": self.acceptable_alternatives,
            "excluded": self.excluded,
            "queries": [query.model_dump() for query in self.queries],
            "derived": self.derived,
        }


class VisualBriefSet(BaseModel):
    briefs: list[VisualBrief] = Field(min_length=1, max_length=10)


def query_problem(query: str, brief: VisualBrief) -> str | None:
    """Why a query would lose the scene's subject, or ``None`` when it keeps it."""
    words = set(tokens(query))
    if not words:
        return "The query has no searchable words."
    if brief.named_entities and brief.requires_exact:
        if not any(e.terms and set(e.terms) <= words for e in brief.named_entities):
            names = ", ".join(entity.name for entity in brief.named_entities)
            return f"The scene needs an exact subject; keep the full name in the query ({names})."
        return None
    anchors = set(brief.anchor_terms)
    if anchors and not anchors & words:
        return (
            "The query drops the scene's subject. Keep at least one of: "
            + ", ".join(sorted(anchors)[:8])
            + "."
        )
    return None


_PROPER = re.compile(
    r"\b([A-Z][a-zA-Z'’.-]+(?:\s+(?:of|de|du|la|von|van|the)?\s*[A-Z][a-zA-Z'’.-]+)+)"
)
_SENTENCE_STARTERS = frozenset({"The", "A", "An", "This", "That", "In", "On", "At", "It", "We"})


def _proper_names(text: str) -> list[str]:
    names = []
    for match in _PROPER.finditer(text or ""):
        words = match.group(1).split()
        while words and words[0] in _SENTENCE_STARTERS:
            words = words[1:]
        if len(words) >= 2:
            names.append(" ".join(words))
    return list(dict.fromkeys(names))[:3]


def derive_brief(scene: Any) -> VisualBrief:
    """Conservative brief built without a model (used only when the model call fails)."""
    description = " ".join(str(scene.visual_description).split())
    names = _proper_names(f"{scene.visual_description}. {scene.narration}")
    query = " ".join(str(scene.image_query).split())[:100]
    queries = [BriefQuery(query=query, rationale="The script's search phrase for this scene.")]
    if names and not any(name.lower() in query.lower() for name in names):
        queries.insert(0, BriefQuery(query=names[0][:100], rationale="Named subject in the scene."))
    return VisualBrief(
        scene_index=scene.index,
        purpose="Illustrate the narration.",
        subject=(description or query)[:120],
        named_entities=[NamedEntity(name=name) for name in names],
        specificity="exact" if names else "generic",
        queries=queries[:MAX_QUERIES],
        narration=str(scene.narration)[:400],
        derived=True,
    )
