"""Scene image selection: briefs, relevance checks, source switching and honest gaps.

Sources, previews and downloads are served by the scripted ``web`` fixture and the
vision model is either a scripted ``VisionJudge`` or a ``FakeProvider``, so nothing
here touches the network.
"""

from __future__ import annotations

import io
import json
import random
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from PIL import Image

from engine.llm import CompletionResult, LLMError, use_llm_resolver
from engine.orchestrator import specialists
from engine.orchestrator.schemas import ProductionBrief, ScriptArtifact
from engine.services.images import sources
from engine.services.images import toolkit as toolkit_module
from engine.services.images.brief import VisualBrief, query_problem
from engine.services.images.candidates import ImageCandidate
from engine.services.images.relevance import (
    CandidateAssessment,
    VisionJudge,
    VisionVerdict,
    decide,
)
from engine.services.images.toolkit import ImageToolError, ImageToolkit
from providers.services import make_resolver
from studio.models import MediaAsset, Project
from studio.store import DjangoProjectStore

from .conftest import FakeRegistry, configure_ai

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def llm(fake_providers: FakeRegistry, db: Any) -> Iterator[FakeRegistry]:
    """A configured AI provider (scripted) and the resolver jobs normally install."""
    configure_ai()
    with use_llm_resolver(make_resolver()):
        yield fake_providers


# --- helpers ----------------------------------------------------------------------------


def textured_jpeg(seed: int, size: tuple[int, int] = (720, 1280), quality: int = 90) -> bytes:
    """A blocky random texture; different seeds give clearly different perceptual hashes."""
    rng = random.Random(seed)
    grid = Image.new("L", (12, 12))
    grid.putdata([rng.randrange(256) for _ in range(144)])
    image = grid.resize(size, Image.Resampling.NEAREST).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def jpeg(data: bytes) -> Handler:
    return lambda request: httpx.Response(200, headers={"content-type": "image/jpeg"}, content=data)


def brief(
    subject: str,
    *,
    queries: list[str],
    scene_index: int = 0,
    specificity: str = "generic",
    entities: list[str] | None = None,
    excluded: list[str] | None = None,
) -> VisualBrief:
    return VisualBrief.model_validate(
        {
            "scene_index": scene_index,
            "subject": subject,
            "specificity": specificity,
            "named_entities": [{"name": name, "kind": "landmark"} for name in entities or []],
            "excluded": excluded or [],
            "queries": [{"query": query} for query in queries],
        }
    )


def candidate(
    candidate_id: str,
    title: str,
    *,
    rights: str = "documented",
    width: int = 1200,
    height: int = 1800,
    provider: str = "openverse",
) -> ImageCandidate:
    return ImageCandidate(
        candidate_id=candidate_id,
        provider=provider,  # type: ignore[arg-type]
        title=title,
        download_url=f"https://upload.example/{candidate_id.replace(':', '-')}.jpg",
        preview_url=f"https://thumbs.example/{candidate_id.replace(':', '-')}.jpg",
        width=width,
        height=height,
        license="CC BY 4.0" if rights == "documented" else "unknown",
        rights_status=rights,  # type: ignore[arg-type]
    )


def verdict(
    candidate_id: str,
    *,
    subject: str = "yes",
    relevance: str = "high",
    identity: str = "not_applicable",
    composition: str = "good",
    quality: str = "good",
    excluded: bool = False,
    watermark: bool = False,
    seen: str = "",
) -> VisionVerdict:
    return VisionVerdict(
        candidate_id=candidate_id,
        visible_content=seen or "What the image shows.",
        subject_match=subject,  # type: ignore[arg-type]
        scene_relevance=relevance,  # type: ignore[arg-type]
        identity=identity,  # type: ignore[arg-type]
        composition=composition,  # type: ignore[arg-type]
        technical_quality=quality,  # type: ignore[arg-type]
        excluded_present=excluded,
        text_or_watermark=watermark,
        reason="Scripted verdict.",
    )


class ScriptedJudge(VisionJudge):
    """A vision judge that answers from a table instead of calling a model."""

    def __init__(self, verdicts: dict[str, VisionVerdict]) -> None:
        super().__init__("visual")
        self.verdicts = verdicts
        self.seen: list[str] = []

    def assess(
        self, brief: VisualBrief, candidates: list[ImageCandidate]
    ) -> tuple[dict[str, VisionVerdict], dict[str, str]]:
        self.seen.extend(c.candidate_id for c in candidates)
        return {
            c.candidate_id: self.verdicts[c.candidate_id]
            for c in candidates
            if c.candidate_id in self.verdicts
        }, {}


def openverse_items(*items: dict[str, Any]) -> Handler:
    results = []
    for item in items:
        identifier = item["id"]
        results.append(
            {
                "id": identifier,
                "title": item.get("title", ""),
                "url": item.get("url", f"https://upload.example/{identifier}.jpg"),
                "thumbnail": f"https://thumbs.example/{identifier}.jpg",
                "foreign_landing_url": f"https://commons.example/{identifier}",
                "creator": "Ana",
                "license": "by",
                "license_version": "4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "width": 1200,
                "height": 1800,
                "filetype": "jpg",
                "tags": [{"name": tag} for tag in item.get("tags", [])],
            }
        )
    return lambda request: httpx.Response(200, json={"results": results})


def only_sources(monkeypatch: pytest.MonkeyPatch, *configured: str) -> None:
    """Pretend exactly these keyed sources are set up (keyless sources are always available)."""
    monkeypatch.setattr(
        sources,
        "available",
        lambda source: source not in ("pexels", "pixabay", "brave") or source in configured,
    )
    monkeypatch.setattr(
        sources.integrations,
        "get_key",
        lambda service: f"{service}-test-key" if service in configured else None,
    )


def pexels_photos(monkeypatch: pytest.MonkeyPatch, photos: list[dict[str, Any]]) -> list[str]:
    queries: list[str] = []

    def search(query: str, **kwargs: Any) -> dict[str, Any]:
        queries.append(query)
        return {
            "photos": [
                {
                    "id": photo["id"],
                    "alt": photo["alt"],
                    "url": f"https://www.pexels.com/photo/{photo['id']}/",
                    "width": 3000,
                    "height": 4500,
                    "photographer": "Sam",
                    "src": {
                        "original": f"https://images.pexels.com/{photo['id']}.jpeg",
                        "medium": f"https://images.pexels.com/{photo['id']}-medium.jpeg",
                    },
                }
                for photo in photos
            ]
        }

    monkeypatch.setattr(sources.pexels_client, "search_pexels_photos", search)
    return queries


COMMONS_PAYLOAD = {
    "query": {
        "pages": [
            {
                "pageid": 42,
                "index": 1,
                "title": "File:Tour Eiffel Wikimedia Commons.jpg",
                "imageinfo": [
                    {
                        "mime": "image/jpeg",
                        "thumburl": "https://upload.wikimedia.org/thumb/1280px-Tour_Eiffel.jpg",
                        "thumbwidth": 1280,
                        "thumbheight": 1920,
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Tour_Eiffel.jpg",
                        "extmetadata": {
                            "ObjectName": {"value": "Eiffel Tower from the Champ de Mars"},
                            "ImageDescription": {"value": "The <b>Eiffel Tower</b> in Paris."},
                            "Artist": {"value": "<a href='https://x.example'>Jane Doe</a>"},
                            "LicenseShortName": {"value": "CC BY-SA 4.0"},
                            "LicenseUrl": {
                                "value": "https://creativecommons.org/licenses/by-sa/4.0"
                            },
                        },
                    }
                ],
            },
            {
                "pageid": 43,
                "index": 2,
                "title": "File:Eiffel Tower postcard.jpg",
                "imageinfo": [
                    {
                        "mime": "image/jpeg",
                        "thumburl": "https://upload.wikimedia.org/thumb/1280px-nc.jpg",
                        "extmetadata": {"LicenseShortName": {"value": "CC BY-NC 2.0"}},
                    }
                ],
            },
            {
                "pageid": 44,
                "index": 3,
                "title": "File:Eiffel Tower logo.png",
                "imageinfo": [
                    {
                        "mime": "image/png",
                        "thumburl": "https://upload.wikimedia.org/thumb/1280px-logo.png",
                        "extmetadata": {
                            "LicenseShortName": {"value": "Public domain"},
                            "NonFree": {"value": "true"},
                        },
                    }
                ],
            },
        ]
    }
}


# --- briefs and queries -----------------------------------------------------------------


def test_queries_must_keep_the_subject() -> None:
    exact = brief(
        "The Eiffel Tower at night",
        queries=["Eiffel Tower night"],
        specificity="exact",
        entities=["Eiffel Tower"],
    )
    assert query_problem("Eiffel Tower Paris", exact) is None
    assert query_problem("tower at night", exact)  # the name was dropped
    assert query_problem("Paris", exact)

    generic = brief("rocky tide pool", queries=["tide pool"])
    assert query_problem("tide pool starfish", generic) is None
    assert query_problem("nature", generic)
    assert query_problem("beautiful photo", generic)


@pytest.mark.django_db
def test_brief_refinement_cannot_drop_or_loosen_the_subject() -> None:
    exact = brief(
        "The Eiffel Tower at night",
        queries=["Eiffel Tower night"],
        specificity="exact",
        entities=["Eiffel Tower"],
    )
    kit = ImageToolkit(DjangoProjectStore(Project.objects.create()), scene_count=1, briefs=[exact])
    with pytest.raises(ImageToolError) as dropped:
        kit.refine_brief(0, subject="City lights")
    assert dropped.value.kind == "query_drops_subject"
    with pytest.raises(ImageToolError):
        kit.refine_brief(0, specificity="generic")
    with pytest.raises(ImageToolError) as broad:
        kit.refine_brief(0, queries="landmark at night|Paris")
    assert broad.value.kind == "query_drops_subject"
    refined = kit.refine_brief(0, queries="Eiffel Tower illuminated", excluded="Tokyo Tower")
    assert refined["queries"][0]["query"] == "Eiffel Tower illuminated"
    assert "Tokyo Tower" in refined["excluded"]


# --- acceptance rules and a small evaluation set ----------------------------------------

TIDE = brief("rocky tide pool", queries=["tide pool"])
EIFFEL = brief(
    "The Eiffel Tower", queries=["Eiffel Tower"], specificity="exact", entities=["Eiffel Tower"]
)
KITCHEN = brief("person cooking in a kitchen", queries=["cooking kitchen"], excluded=["logo"])
TOKAMAK = brief(
    "tokamak fusion reactor vacuum vessel interior",
    queries=["tokamak vacuum vessel interior"],
    specificity="representative",
)

EVALUATION_SET: list[tuple[str, VisualBrief, ImageCandidate, VisionVerdict | None, str]] = [
    # Metadata only (no vision): generic subjects may pass, exact subjects never auto-accept.
    ("generic, strong metadata", TIDE, candidate("a:1", "Tide pool with rocks"), None, "accept"),
    (
        "generic, unrelated metadata",
        TIDE,
        candidate("a:2", "Woman drinking coffee"),
        None,
        "reject",
    ),
    ("generic, no metadata", TIDE, candidate("a:3", ""), None, "reject"),
    # Seen in live Pexels results for a tokamak scene: one shared generic word is not a match.
    (
        "one shared word",
        TOKAMAK,
        candidate("a:7", "Interior view of a stainless steel temple"),
        None,
        "reject",
    ),
    (
        "niche subject named",
        TOKAMAK,
        candidate("a:8", "Inside the tokamak vacuum vessel"),
        None,
        "accept",
    ),
    ("exact, names subject", EIFFEL, candidate("a:4", "Eiffel Tower at dusk"), None, "review"),
    ("exact, look-alike name", EIFFEL, candidate("a:5", "Tokyo Tower at night"), None, "reject"),
    ("too small", TIDE, candidate("a:6", "Tide pool", width=300, height=200), None, "reject"),
    # Vision available: what is visible decides, the title is only supporting evidence.
    (
        "misleading title",
        TIDE,
        candidate("v:1", "Tide pool at low tide"),
        verdict("v:1", subject="no", seen="A parking lot"),
        "reject",
    ),
    (
        "generic, visible match",
        TIDE,
        candidate("v:2", "IMG_2041"),
        verdict("v:2"),
        "accept",
    ),
    (
        "exact, confirmed identity",
        EIFFEL,
        candidate("v:3", "Eiffel Tower from Trocadero"),
        verdict("v:3", identity="consistent"),
        "accept",
    ),
    (
        "exact, cannot tell which tower",
        EIFFEL,
        candidate("v:4", "Eiffel Tower"),
        verdict("v:4", identity="cannot_tell"),
        "illustrative",
    ),
    (
        "exact, different landmark",
        EIFFEL,
        candidate("v:5", "Eiffel Tower replica"),
        verdict("v:5", identity="inconsistent"),
        "reject",
    ),
    (
        "exact, looks right but unnamed",
        EIFFEL,
        candidate("v:6", "Paris skyline"),
        verdict("v:6", identity="consistent"),
        "review",
    ),
    (
        "partial generic match",
        KITCHEN,
        candidate("v:7", "Kitchen counter"),
        verdict("v:7", subject="partial"),
        "review",
    ),
    (
        "excluded content visible",
        KITCHEN,
        candidate("v:8", "Chef cooking"),
        verdict("v:8", excluded=True),
        "reject",
    ),
    (
        "watermarked",
        KITCHEN,
        candidate("v:9", "Cooking at home"),
        verdict("v:9", watermark=True),
        "review",
    ),
    (
        "unknown rights",
        TIDE,
        candidate("v:10", "Tide pool", rights="unknown"),
        verdict("v:10"),
        "review",
    ),
    (
        "irrelevant to narration",
        TIDE,
        candidate("v:11", "Tide pool"),
        verdict("v:11", relevance="low"),
        "reject",
    ),
]


@pytest.mark.parametrize(
    ("label", "scene_brief", "item", "seen", "expected"),
    EVALUATION_SET,
    ids=[case[0] for case in EVALUATION_SET],
)
def test_relevance_evaluation_set(
    label: str,
    scene_brief: VisualBrief,
    item: ImageCandidate,
    seen: VisionVerdict | None,
    expected: str,
) -> None:
    assessment = decide(item, scene_brief, seen)
    assert assessment.decision == expected, assessment.reasons
    assert assessment.reasons, "every decision explains itself"
    assert 0 <= assessment.score <= 100
    if seen is None:
        assert assessment.verification == "metadata"
        assert assessment.score <= 45  # metadata alone never scores like a visual check
    if assessment.decision == "accept" and seen is None:
        assert any("visually unverified" in reason for reason in assessment.reasons)


# --- staged selection -------------------------------------------------------------------


@pytest.mark.django_db
def test_unrelated_pexels_results_leave_the_scene_unresolved(
    web: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    only_sources(monkeypatch, "pexels")
    pexels_photos(
        monkeypatch,
        [
            {"id": 1, "alt": "Woman drinking coffee in a cafe"},
            {"id": 2, "alt": "Red sports car on a road"},
        ],
    )
    web["routes"][sources.OPENVERSE_URL] = openverse_items()
    kit = ImageToolkit(
        DjangoProjectStore(Project.objects.create()),
        scene_count=1,
        briefs=[brief("rocky tide pool", queries=["tide pool"])],
    )

    assert kit.staged_select(0) is None
    visual = kit.scene_visual(0)
    assert visual.status == "no_suitable_result"
    gap = kit.work[0].gap
    assert gap is not None
    assert {"search_other_source", "upload", "paste_url", "title_card"} <= set(gap.actions)
    assert "rocky tide pool" in gap.missing
    assert MediaAsset.objects.count() == 0
    assert not any("images.pexels.com" in url for url in web["requests"])


@pytest.mark.django_db
def test_empty_searches_report_an_honest_gap(
    web: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    only_sources(monkeypatch, "pexels")
    queries = pexels_photos(monkeypatch, [])
    web["routes"][sources.OPENVERSE_URL] = openverse_items()
    kit = ImageToolkit(
        DjangoProjectStore(Project.objects.create()),
        scene_count=1,
        briefs=[
            brief(
                "bioluminescent plankton", queries=["bioluminescent plankton", "glowing plankton"]
            )
        ],
    )
    assert kit.staged_select(0) is None
    gap = kit.work[0].gap
    assert gap is not None and "No results" in gap.reason
    # Every query kept the subject; nothing was broadened to "plankton" or "ocean".
    assert queries == ["bioluminescent plankton", "glowing plankton"]
    assert kit.scene_visual(0).status == "no_suitable_result"


@pytest.mark.django_db
def test_misleading_title_is_rejected_by_the_visual_check(web: dict[str, Any]) -> None:
    web["routes"][sources.OPENVERSE_URL] = openverse_items(
        {"id": "lot", "title": "Tide pool at low tide"},
        {"id": "pool", "title": "IMG 2041", "tags": ["tide pool"]},
    )
    web["routes"]["https://upload.example/pool.jpg"] = jpeg(textured_jpeg(1))
    judge = ScriptedJudge(
        {
            "openverse:lot": verdict("openverse:lot", subject="no", seen="An empty parking lot"),
            "openverse:pool": verdict("openverse:pool", seen="Rocks around a shallow tide pool"),
        }
    )
    kit = ImageToolkit(
        DjangoProjectStore(Project.objects.create()),
        scene_count=1,
        briefs=[brief("rocky tide pool", queries=["tide pool"])],
        vision=judge,
    )
    chosen = kit.staged_select(0)
    assert chosen is not None and chosen.candidate_id == "openverse:pool"
    assert chosen.verification == "vision"
    assert kit.work[0].assessments["openverse:lot"].decision == "reject"
    assert not any("upload.example/lot" in url for url in web["requests"])
    asset = MediaAsset.objects.get()
    assert asset.metadata["assessment"]["decision"] == "accept"
    assert asset.metadata["brief_subject"] == "rocky tide pool"


@pytest.mark.django_db
def test_switching_sources_finds_the_exact_subject(
    web: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    only_sources(monkeypatch, "pexels", "brave")
    pexels_photos(monkeypatch, [{"id": 7, "alt": "Eiffel Tower style tower in Las Vegas"}])
    web["routes"][sources.COMMONS_API] = lambda request: httpx.Response(200, json=COMMONS_PAYLOAD)
    web["routes"]["https://upload.wikimedia.org/thumb/1280px-Tour_Eiffel.jpg"] = jpeg(
        textured_jpeg(2)
    )
    judge = ScriptedJudge(
        {
            "pexels:7": verdict(
                "pexels:7", identity="inconsistent", seen="A replica tower by a casino"
            ),
            "wikimedia:42": verdict("wikimedia:42", identity="consistent", seen="The Eiffel Tower"),
        }
    )
    exact = brief(
        "The Eiffel Tower", queries=["Eiffel Tower"], specificity="exact", entities=["Eiffel Tower"]
    )
    kit = ImageToolkit(
        DjangoProjectStore(Project.objects.create()), scene_count=1, briefs=[exact], vision=judge
    )

    with pytest.raises(ImageToolError) as early:
        kit.scene_search(0, "Eiffel Tower", "brave")
    assert "only after" in str(early.value)

    first = kit.scene_search(0, "Eiffel Tower", "pexels")
    assert first["count"] == 1
    kit.scene_inspect(0, ["pexels:7"])
    with pytest.raises(ImageToolError) as refused:
        kit.scene_download(0, "pexels:7")
    assert refused.value.kind == "not_accepted"

    second = kit.scene_search(0, "Eiffel Tower", "wikimedia")
    # Non-commercial and non-free Commons files are filtered out by licence.
    assert [c["candidate_id"] for c in second["candidates"]] == ["wikimedia:42"]
    kit.scene_inspect(0, ["wikimedia:42"])
    ranked = kit.scene_rank(0)
    assert ranked["recommendation"] == "wikimedia:42"
    saved = kit.scene_download(0, "wikimedia:42", "Shows the tower itself")
    asset = MediaAsset.objects.get(pk=saved["asset_id"])
    assert asset.provider == "wikimedia"
    assert asset.license == "CC BY-SA 4.0"
    assert asset.creator == "Jane Doe"
    assert asset.source_page_url == "https://commons.wikimedia.org/wiki/File:Tour_Eiffel.jpg"
    assert kit.scene_visual(0).status == "selected"
    commons_request = next(
        h
        for url, h in zip(web["requests"], web["headers"], strict=True)
        if url.startswith(sources.COMMONS_API)
    )
    assert "FrameFusion" in commons_request["user-agent"]


@pytest.mark.django_db
def test_brave_results_are_discovery_only(
    web: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    only_sources(monkeypatch, "brave")
    web["routes"][sources.OPENVERSE_URL] = openverse_items({"id": "x", "title": "Unrelated car"})
    web["routes"][sources.BRAVE_URL] = lambda request: httpx.Response(
        200,
        json={
            "results": [
                {
                    "title": "Old harbour lighthouse",
                    "url": "https://blog.example/post",
                    "source": "blog.example",
                    "thumbnail": {"src": "https://thumbs.example/brave.jpg"},
                    "properties": {
                        "url": "https://blog.example/lighthouse.jpg",
                        "width": 1200,
                        "height": 1600,
                    },
                }
            ]
        },
    )
    kit = ImageToolkit(
        DjangoProjectStore(Project.objects.create()),
        scene_count=1,
        briefs=[brief("harbour lighthouse", queries=["harbour lighthouse"])],
        vision=ScriptedJudge({}),
    )
    kit.scene_search(0, "harbour lighthouse", "openverse")
    found = kit.scene_search(0, "harbour lighthouse", "brave")
    brave_id = found["candidates"][0]["candidate_id"]
    assert isinstance(kit.vision, ScriptedJudge)
    kit.vision.verdicts[brave_id] = verdict(brave_id, seen="A lighthouse by a harbour")
    kit.scene_inspect(0, [brave_id])
    assessment = kit.work[0].assessments[brave_id]
    assert assessment.rights == "unknown" and assessment.decision == "review"
    with pytest.raises(ImageToolError):
        kit.scene_download(0, brave_id)
    with pytest.raises(ImageToolError) as again:
        kit.scene_search(0, "harbour lighthouse", "brave")
    assert again.value.kind == "budget_exhausted"
    brave_headers = next(
        h
        for url, h in zip(web["requests"], web["headers"], strict=True)
        if url.startswith(sources.BRAVE_URL)
    )
    assert brave_headers["x-subscription-token"] == "brave-test-key"
    assert "brave-test-key" not in json.dumps(found)
    assert kit.scene_visual(0).status == "awaiting_review"


@pytest.mark.django_db
def test_vision_unsupported_falls_back_to_marked_metadata_checks(
    web: dict[str, Any], llm: FakeRegistry
) -> None:
    fake_providers = llm
    fake_providers.get("openrouter").responses = [
        LLMError(
            "This model does not support image input.", kind="unsupported", provider="openrouter"
        )
    ]
    web["routes"][sources.OPENVERSE_URL] = openverse_items(
        {"id": "pool", "title": "Rocky tide pool with anemones"},
    )
    web["routes"]["https://thumbs.example/"] = jpeg(textured_jpeg(3, (400, 600)))
    judge = VisionJudge("visual")
    generic = brief("rocky tide pool", queries=["tide pool"])
    exact = brief(
        "The Eiffel Tower", queries=["Eiffel Tower"], specificity="exact", entities=["Eiffel Tower"]
    )
    kit = ImageToolkit(
        DjangoProjectStore(Project.objects.create()), scene_count=1, briefs=[generic], vision=judge
    )
    kit.scene_search(0, "tide pool", "openverse")
    result = kit.scene_inspect(0, ["openverse:pool"])

    assert result["vision_available"] is False
    assessment = CandidateAssessment.model_validate(result["assessments"][0])
    assert assessment.verification == "metadata"
    assert assessment.decision == "accept"
    assert any("can't read images" in reason for reason in assessment.reasons)
    assert any("didn't accept images" in note for note in kit.limitations)

    request = fake_providers.get("openrouter").requests[0]
    user = request.messages[-1]
    assert len(user.images) == 1 and user.images[0].mime_type == "image/jpeg"
    assert "Rocky tide pool with anemones" not in user.content  # titles are withheld

    # The judge stays off for the rest of the run, and exact subjects then need review.
    eiffel = candidate("x:1", "Eiffel Tower at dusk")
    assert judge.assess(exact, [eiffel]) == ({}, {})
    assert decide(eiffel, exact, None, vision_note=judge.note).decision == "review"
    assert len(fake_providers.get("openrouter").requests) == 1


@pytest.mark.django_db
def test_vision_verdicts_drive_the_decision(web: dict[str, Any], llm: FakeRegistry) -> None:
    llm.get("openrouter").responses = [
        CompletionResult(
            text=json.dumps(
                {
                    "verdicts": [
                        verdict("openverse:a", seen="Rocks around a tide pool").model_dump(),
                        verdict("openverse:b", subject="no", seen="A swimming pool").model_dump(),
                    ]
                }
            )
        )
    ]
    web["routes"][sources.OPENVERSE_URL] = openverse_items(
        {"id": "a", "title": "DSC_0042"},
        {"id": "b", "title": "Tide pool"},
    )
    web["routes"]["https://thumbs.example/"] = jpeg(textured_jpeg(4, (400, 600)))
    kit = ImageToolkit(
        DjangoProjectStore(Project.objects.create()),
        scene_count=1,
        briefs=[brief("rocky tide pool", queries=["tide pool"])],
        vision=VisionJudge("visual"),
    )
    kit.scene_search(0, "tide pool", "openverse")
    kit.scene_inspect(0, ["openverse:a", "openverse:b"])
    assert kit.work[0].assessments["openverse:a"].decision == "accept"
    assert kit.work[0].assessments["openverse:a"].verification == "vision"
    assert kit.work[0].assessments["openverse:b"].decision == "reject"


# --- download safety --------------------------------------------------------------------


@pytest.mark.django_db
def test_exact_and_near_duplicates_are_not_reused_across_scenes(web: dict[str, Any]) -> None:
    original = textured_jpeg(5)
    resized = textured_jpeg(5, (800, 1420), quality=70)  # different bytes, same picture
    web["routes"][sources.OPENVERSE_URL] = openverse_items(
        {"id": "one", "title": "Tide pool"},
        {"id": "copy", "title": "Tide pool"},
        {"id": "near", "title": "Tide pool"},
        {"id": "other", "title": "Tide pool"},
    )
    web["routes"]["https://upload.example/one.jpg"] = jpeg(original)
    web["routes"]["https://upload.example/copy.jpg"] = jpeg(original)
    web["routes"]["https://upload.example/near.jpg"] = jpeg(resized)
    web["routes"]["https://upload.example/other.jpg"] = jpeg(textured_jpeg(6))
    ids = ["openverse:one", "openverse:copy", "openverse:near", "openverse:other"]
    judge = ScriptedJudge({cid: verdict(cid) for cid in ids})
    briefs = [brief("rocky tide pool", queries=["tide pool"], scene_index=i) for i in range(2)]
    kit = ImageToolkit(
        DjangoProjectStore(Project.objects.create()), scene_count=2, briefs=briefs, vision=judge
    )
    for scene in (0, 1):
        kit.scene_search(scene, "tide pool", "openverse")
        kit.scene_inspect(scene, ids)

    kit.scene_download(0, "openverse:one")
    for duplicate in ("openverse:copy", "openverse:near"):
        with pytest.raises(ImageToolError) as raised:
            kit.scene_download(1, duplicate)
        assert raised.value.kind == "duplicate"
    saved = kit.scene_download(1, "openverse:other")
    assert kit.work[1].selected is not None
    assert kit.work[1].selected.asset_id == saved["asset_id"]
    assert MediaAsset.objects.count() == 2


@pytest.mark.django_db
def test_corrupt_download_is_recorded_and_never_selected(
    web: dict[str, Any], output_dir: Any
) -> None:
    web["routes"][sources.OPENVERSE_URL] = openverse_items({"id": "bad", "title": "Tide pool"})
    web["routes"]["https://upload.example/bad.jpg"] = jpeg(b"\xff\xd8\xff" + b"not a jpeg" * 50)
    kit = ImageToolkit(
        DjangoProjectStore(Project.objects.create()),
        scene_count=1,
        briefs=[brief("rocky tide pool", queries=["tide pool"])],
        vision=ScriptedJudge({"openverse:bad": verdict("openverse:bad")}),
    )
    assert kit.staged_select(0) is None
    assert kit.work[0].download_failures
    assert kit.scene_visual(0).status == "download_failed"
    gap = kit.work[0].gap
    assert gap is not None and "could not be downloaded" in gap.reason
    assert MediaAsset.objects.count() == 0
    assert not [p for p in output_dir.rglob("*") if p.is_file()]


@pytest.mark.django_db
def test_unsafe_urls_and_oversized_files_are_refused(
    web: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata_url = "http://169.254.169.254/latest/meta-data/photo.jpg"
    kit = ImageToolkit(
        DjangoProjectStore(Project.objects.create()),
        user_urls=[metadata_url, "https://big.example/huge.jpg"],
        scene_count=1,
        briefs=[brief("harbour lighthouse", queries=["harbour lighthouse"])],
    )
    with pytest.raises(ImageToolError) as blocked:
        kit.scene_search(0, metadata_url, "url")
    assert blocked.value.kind == "blocked_url"
    with pytest.raises(ImageToolError):
        kit.scene_search(0, "https://not-supplied.example/a.jpg", "url")

    monkeypatch.setattr(toolkit_module, "MAX_IMAGE_BYTES", 1000)
    web["routes"]["https://big.example/"] = jpeg(textured_jpeg(7))
    found = kit.search("https://big.example/huge.jpg", "url")
    with pytest.raises(ImageToolError) as large:
        kit.inspect(found["candidates"][0]["candidate_id"])
    assert large.value.kind == "too_large"
    assert MediaAsset.objects.count() == 0


# --- the visual specialist end to end ---------------------------------------------------


def _script(scenes: int = 3) -> ScriptArtifact:
    return ScriptArtifact(
        title="Tide pools",
        hook="Look closer.",
        scenes=[
            {
                "index": i,
                "narration": f"Scene {i + 1} about tide pools.",
                "on_screen_text": "",
                "visual_description": "A rocky tide pool at low tide",
                "image_query": "tide pool",
            }
            for i in range(scenes)
        ],
    )


@pytest.mark.django_db
def test_unresolved_scenes_stay_unresolved_across_runs(
    web: dict[str, Any], llm: FakeRegistry
) -> None:
    # Every scripted model reply is "Done.", so briefs are derived and vision is unreadable.
    web["routes"][sources.OPENVERSE_URL] = openverse_items(
        {"id": "car", "title": "Red car parked downtown"},
        {"id": "cat", "title": "Cat sleeping on a sofa"},
    )
    web["routes"]["https://thumbs.example/"] = jpeg(textured_jpeg(8, (400, 600)))
    store = DjangoProjectStore(Project.objects.create())
    script = _script()
    production_brief = ProductionBrief(title="Tide pools", objective="Tide pools", scene_count=3)

    first = specialists.run_visuals(script, production_brief, store, user_urls=[])
    assert first.scene_assets == []
    assert [gap.scene_index for gap in first.gaps] == [0, 1, 2]
    assert [state.status for state in first.scenes] == ["no_suitable_result"] * 3
    assert all(gap.actions for gap in first.gaps)
    assert any("derived from the script" in note for note in first.limitations)
    assert any("Pexels isn't set up" in note for note in first.limitations)

    second = specialists.run_visuals(script, production_brief, store, user_urls=[], previous=first)
    assert second.scene_assets == []
    assert [state.status for state in second.scenes] == ["no_suitable_result"] * 3
    assert MediaAsset.objects.count() == 0
    assert not any(url.startswith("https://upload.example/") for url in web["requests"])
