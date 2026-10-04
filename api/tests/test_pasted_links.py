"""Links you paste after searching Google Images in your own browser.

FrameFusion never requests Google: result links are read locally and only the
publisher's page and image are fetched (through the scripted ``web`` fixture
here, so nothing touches the network).
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
import pytest
from PIL import Image
from rest_framework.test import APIClient

from engine.llm import CompletionResult
from engine.services.images import pasted
from engine.services.images.pasted import PastedLinkError, parse_link, resolve
from engine.services.images.relevance import VisionVerdict
from engine.services.images.webpage import license_label
from studio.models import MediaAsset, ProductionTask, Project

from .conftest import FakeRegistry, configure_ai

Handler = Callable[[httpx.Request], httpx.Response]

IMAGE = "https://cdn.publisher.example/photos/eiffel-tower-dusk.jpg"
PAGE = "https://publisher.example/travel/paris"


def jpeg(width: int = 900, height: int = 1400, color: str = "navy") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def image_route(data: bytes | None = None) -> Handler:
    body = data if data is not None else jpeg()
    return lambda request: httpx.Response(200, headers={"content-type": "image/jpeg"}, content=body)


def html_route(html: str, status: int = 200) -> Handler:
    return lambda request: httpx.Response(
        status, headers={"content-type": "text/html; charset=utf-8"}, content=html.encode()
    )


def imgres(image: str = IMAGE, page: str = PAGE, host: str = "www.google.com") -> str:
    return (
        f"https://{host}/imgres?imgurl={quote(image, safe='')}&imgrefurl={quote(page, safe='')}"
        "&docid=abc&tbnid=xyz&w=1600&h=2400"
    )


PUBLISHER_HTML = f"""<html><head>
  <title>A week in Paris</title>
  <meta property="og:site_name" content="Publisher Travel">
  <meta name="author" content="Jane Doe">
  <script type="application/ld+json">
  {{"@context": "https://schema.org", "@type": "ImageObject",
    "contentUrl": "{IMAGE}?w=1600",
    "license": "https://creativecommons.org/licenses/by/4.0/",
    "acquireLicensePage": "/licensing",
    "creditText": "Photo: Jane Doe / Publisher Travel",
    "creator": {{"@type": "Person", "name": "Jane Doe"}},
    "copyrightNotice": "© 2025 Jane Doe"}}
  </script>
</head><body>
  <img src="{IMAGE}?w=800" alt="The Eiffel Tower at dusk" width="800" height="1200">
  <img src="/img/louvre.jpg" alt="The Louvre" width="900" height="1200">
  <img src="/static/logo.png">
</body></html>"""


def no_google(web: dict[str, Any]) -> None:
    for url in web["requests"]:
        host = urlsplit(url).hostname or ""
        assert not pasted.is_google_host(host), f"FrameFusion requested Google: {url}"
        assert not pasted.is_google_thumbnail(host), url


# --- reading links locally ----------------------------------------------------------------


def test_google_result_links_are_read_without_fetching(web: dict[str, Any]) -> None:
    link = parse_link(imgres())
    assert (link.image_url, link.page_url, link.via_google) == (IMAGE, PAGE, True)
    assert (link.width, link.height) == (1600, 2400)

    local = parse_link(imgres(host="www.google.co.uk"))
    assert local.image_url == IMAGE

    redirect = parse_link(f"https://www.google.com/url?sa=i&url={quote(PAGE, safe='')}&psig=x")
    assert (redirect.image_url, redirect.page_url, redirect.via_google) == (None, PAGE, True)

    plain = parse_link("publisher.example/travel/paris")
    assert (plain.page_url, plain.via_google) == ("https://publisher.example/travel/paris", False)
    assert web["requests"] == []


@pytest.mark.parametrize(
    ("link", "kind"),
    [
        ("https://www.google.com/search?q=eiffel+tower&udm=2", "google_page"),
        ("https://images.google.com/search?tbm=isch&q=eiffel", "google_page"),
        ("https://www.google.com/imgres?docid=abc", "google_page"),
        ("https://www.google.com/url?q=https://www.google.com/search?q=x", "google_page"),
        ("https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9Gc", "preview_only"),
        ("data:image/jpeg;base64,/9j/4AAQSkZJRg==", "preview_only"),
        (imgres(image="https://encrypted-tbn0.gstatic.com/images?q=tbn:x"), "preview_only"),
        ("", "bad_link"),
    ],
)
def test_results_pages_and_thumbnails_are_refused_with_instructions(
    web: dict[str, Any], link: str, kind: str
) -> None:
    with pytest.raises(PastedLinkError) as raised:
        resolve(link)
    assert raised.value.kind == kind
    assert str(raised.value)
    assert web["requests"] == []


# --- finding the original on the publisher's page -----------------------------------------


def test_publisher_page_confirms_the_image_and_states_rights(web: dict[str, Any]) -> None:
    web["routes"][PAGE] = html_route(PUBLISHER_HTML)
    found, notes = resolve(imgres())

    first = found[0]
    assert first.download_url == IMAGE
    assert first.found_on_page is True
    assert first.title == "The Eiffel Tower at dusk"
    assert first.source_page_url == PAGE
    assert first.discovered_via == "google_images"
    assert first.publisher == "Publisher Travel"
    assert first.license == "CC BY 4.0 (stated by publisher)"
    assert first.license_url == "https://creativecommons.org/licenses/by/4.0/"
    assert first.attribution == "Photo: Jane Doe / Publisher Travel"
    assert first.rights_status == "unknown"  # a publisher's statement is not verified
    assert first.user_supplied is True
    assert "Google doesn't grant reuse rights" in first.usage_note
    assert (first.width, first.height) == (1600, 2400)
    # Other images on the page are offered too, never the logo.
    assert [c.title for c in found[1:]] == ["The Louvre"]
    assert notes == []
    no_google(web)


def test_image_missing_from_the_publisher_page_is_flagged(web: dict[str, Any]) -> None:
    web["routes"][PAGE] = html_route("<html><title>Moved</title><img src='/other.jpg'></html>")
    found, notes = resolve(imgres())
    assert found[0].download_url == IMAGE
    assert found[0].found_on_page is False
    assert found[0].license == "unknown"
    assert any("wasn't found on the publisher's page" in note for note in notes)


def test_unreachable_publisher_page_keeps_the_image_with_unknown_rights(
    web: dict[str, Any],
) -> None:
    web["routes"][PAGE] = html_route("denied", status=403)
    found, notes = resolve(imgres())
    assert len(found) == 1 and found[0].download_url == IMAGE
    assert found[0].publisher == "publisher.example"
    assert found[0].license == "unknown" and found[0].rights_status == "unknown"
    assert any("Couldn't open the publisher's page" in note for note in notes)


def test_pasted_page_and_direct_image_links(web: dict[str, Any]) -> None:
    web["routes"]["https://blog.example/post"] = html_route(
        """<html><head><link rel="license" href="https://creativecommons.org/publicdomain/zero/1.0/">
        <meta name="copyright" content="Public domain"></head>
        <body><img src="https://blog.example/tide.jpg" alt="Tide pool"></body></html>"""
    )
    web["routes"]["https://files.example/raw.jpg"] = image_route(jpeg(1080, 1920))

    page, _notes = resolve("https://blog.example/post")
    assert page[0].license == "CC0 (stated by publisher)"
    assert page[0].discovered_via is None and page[0].found_on_page is True

    direct, notes = resolve("https://files.example/raw.jpg")
    assert (direct[0].width, direct[0].height, direct[0].format) == (1080, 1920, "jpeg")
    assert direct[0].source_page_url is None
    assert any("direct image link" in note for note in notes)


COMMONS_PAGE = "https://commons.example.org/wiki/File:Tower_at_dusk.jpg"
COMMONS_ORIGINAL = "https://upload.example.org/media/a/a8/Tower_at_dusk.jpg"
COMMONS_HTML = f"""<html><head><title>File:Tower at dusk.jpg</title>
  <link rel="license" href="https://creativecommons.org/licenses/by-sa/4.0/">
  <script type="application/ld+json">
  {{"@context": "https://schema.org", "@type": "ImageObject",
    "contentUrl": "{COMMONS_ORIGINAL}?utm_source=x",
    "license": "https://commons.example.org/wiki/Help:Public_domain"}}
  </script>
  <meta property="og:image" content="https://thumb.example.org/media/thumb/a/a8/Tower_at_dusk.jpg/1200px-Tower_at_dusk.jpg">
</head><body>
  <img src="https://thumb.example.org/media/thumb/a/a8/Tower_at_dusk.jpg/960px-Tower_at_dusk.jpg"
       alt="Tower at dusk, seen from the river" width="324" height="600">
  <img src="https://thumb.example.org/media/b/Tower_at_dusk.jpg" alt="A different file, same name">
</body></html>"""


def test_resized_copies_match_the_declared_original(web: dict[str, Any]) -> None:
    """Shaped like a Wikimedia Commons file page: original in JSON-LD, thumbnails in the body."""
    web["routes"][COMMONS_PAGE] = html_route(COMMONS_HTML)
    found, notes = resolve(imgres(image=COMMONS_ORIGINAL, page=COMMONS_PAGE))

    first = found[0]
    assert first.download_url == COMMONS_ORIGINAL and first.found_on_page is True
    assert first.title == "Tower at dusk, seen from the river"
    # The image's own statement wins over the site footer's rel=license for page text.
    assert first.license == "Public domain (stated by publisher)"
    assert first.rights_status == "unknown"
    # Thumbnails of the same file are not offered again; a same-named file elsewhere is.
    assert [c.download_url for c in found[1:]] == [
        "https://thumb.example.org/media/b/Tower_at_dusk.jpg"
    ]
    assert notes == []
    no_google(web)


def test_license_labels() -> None:
    assert license_label("https://creativecommons.org/licenses/by-sa/3.0/deed.en") == "CC BY-SA 3.0"
    assert license_label("https://creativecommons.org/publicdomain/mark/1.0/") == (
        "Public Domain Mark"
    )
    assert license_label("https://publisher.example/terms") is None


# --- API: relevance, safe download, registration ------------------------------------------


def scripted_project() -> Project:
    project = Project.objects.create()
    ProductionTask.objects.create(
        project=project,
        stage="script",
        specialist="script",
        status=ProductionTask.Status.VERIFIED,
        output={
            "scenes": [
                {
                    "index": 0,
                    "narration": "The Eiffel Tower glows at dusk.",
                    "visual_description": "The Eiffel Tower at dusk",
                    "image_query": "Eiffel Tower dusk",
                }
            ]
        },
    )
    ProductionTask.objects.create(
        project=project,
        stage="visuals",
        specialist="visual",
        status=ProductionTask.Status.VERIFIED,
        output={"gaps": [{"scene_index": 0, "reason": "No suitable image found."}]},
    )
    return project


@pytest.mark.django_db
def test_pasted_link_is_checked_downloaded_safely_and_registered(
    client: APIClient, web: dict[str, Any]
) -> None:
    web["routes"][PAGE] = html_route(PUBLISHER_HTML)
    web["routes"][IMAGE] = image_route()
    project = scripted_project()
    url = f"/api/projects/{project.pk}/images/search"

    search = client.post(
        url, {"query": imgres(), "source": "link", "scene_index": 0}, format="json"
    )
    assert search.status_code == 200, search.json()
    body = search.json()
    first, louvre = body["candidates"][0], body["candidates"][1]
    assert "download_url" not in first
    assert first["discovered_via"] == "google_images" and first["found_on_page"] is True
    # Named subject, unknown rights: at best it waits for your review.
    assert first["assessment"]["decision"] == "review"
    assert first["assessment"]["verification"] == "metadata"
    assert louvre["assessment"]["decision"] == "reject"  # unrelated, even though downloadable

    saved = client.post(
        f"/api/projects/{project.pk}/images/download",
        {"candidate_id": first["candidate_id"], "scene_index": 0},
        format="json",
    )
    assert saved.status_code == 201, saved.json()
    asset = MediaAsset.objects.get()
    assert asset.source_url == IMAGE and asset.source_page_url == PAGE
    assert asset.rights_status == "unknown" and asset.user_supplied is True
    assert asset.license == "CC BY 4.0 (stated by publisher)"
    assert asset.metadata["discovered_via"] == "google_images"
    assert asset.metadata["publisher"] == "Publisher Travel"
    assert asset.metadata["found_on_page"] is True
    assert asset.checksum and asset.width == 900
    scene = saved.json()["production"]["scenes"][0]
    assert scene["asset_id"] == str(asset.pk) and scene["selected_by"] == "user"

    again = client.post(
        f"/api/projects/{project.pk}/images/download",
        {"candidate_id": first["candidate_id"]},
        format="json",
    )
    assert again.json()["reused_existing_file"] is True
    assert MediaAsset.objects.count() == 1
    no_google(web)


@pytest.mark.django_db
def test_unsafe_expired_and_corrupt_pasted_images_fail_cleanly(
    client: APIClient, web: dict[str, Any]
) -> None:
    project = scripted_project()
    search_url = f"/api/projects/{project.pk}/images/search"

    internal = client.post(
        search_url,
        {"query": imgres(image="http://169.254.169.254/latest/x.jpg"), "source": "link"},
        format="json",
    )
    assert internal.status_code == 422 and internal.json()["code"] == "blocked_url"

    google = client.post(
        search_url,
        {"query": "https://www.google.com/search?q=eiffel&udm=2", "source": "link"},
        format="json",
    )
    assert google.status_code == 422 and google.json()["code"] == "google_page"

    web["routes"][PAGE] = html_route(PUBLISHER_HTML)
    web["routes"][IMAGE] = image_route(b"\xff\xd8\xff not really a jpeg")
    found = client.post(search_url, {"query": imgres(), "source": "link"}, format="json").json()
    corrupt = client.post(
        f"/api/projects/{project.pk}/images/download",
        {"candidate_id": found["candidates"][0]["candidate_id"], "scene_index": 0},
        format="json",
    )
    assert corrupt.status_code == 422 and corrupt.json()["code"] == "invalid_image"

    web["routes"][IMAGE] = lambda request: httpx.Response(410)
    gone = client.post(
        f"/api/projects/{project.pk}/images/download",
        {"candidate_id": found["candidates"][0]["candidate_id"]},
        format="json",
    )
    assert gone.status_code == 422 and gone.json()["code"] == "not_found"
    assert MediaAsset.objects.count() == 0
    no_google(web)


@pytest.mark.django_db
def test_vision_check_runs_as_a_job_and_rejects_unrelated_images(
    client: APIClient, web: dict[str, Any], fake_providers: FakeRegistry
) -> None:
    configure_ai()
    web["routes"][PAGE] = html_route(PUBLISHER_HTML)
    web["routes"]["https://cdn.publisher.example/"] = image_route()
    web["routes"]["https://publisher.example/img/"] = image_route(jpeg(color="olive"))
    project = scripted_project()
    found = client.post(
        f"/api/projects/{project.pk}/images/search",
        {"query": imgres(), "source": "link", "scene_index": 0},
        format="json",
    ).json()["candidates"]
    tower, louvre = found[0]["candidate_id"], found[1]["candidate_id"]

    def seen(candidate_id: str, subject: str, identity: str, what: str) -> dict[str, Any]:
        return VisionVerdict(
            candidate_id=candidate_id,
            visible_content=what,
            subject_match=subject,  # type: ignore[arg-type]
            scene_relevance="high" if subject == "yes" else "low",
            identity=identity,  # type: ignore[arg-type]
            composition="good",
            technical_quality="good",
            excluded_present=False,
            text_or_watermark=False,
            reason="Scripted.",
        ).model_dump()

    fake_providers.get("openrouter").responses = [
        CompletionResult(
            text=json.dumps(
                {
                    "verdicts": [
                        seen(tower, "yes", "consistent", "The Eiffel Tower lit at dusk"),
                        seen(louvre, "no", "inconsistent", "A glass pyramid"),
                    ]
                }
            )
        )
    ]
    response = client.post(
        f"/api/projects/{project.pk}/images/check",
        {"scene_index": 0, "candidate_ids": [tower, louvre]},
        format="json",
    )
    assert response.status_code == 202, response.json()
    job = client.get(f"/api/jobs/{response.json()['id']}").json()
    assert job["status"] == "succeeded", job
    by_id = {a["candidate_id"]: a for a in job["result"]["assessments"]}
    assert by_id[tower]["verification"] == "vision"
    assert by_id[tower]["decision"] == "review"  # rights unknown until you approve
    assert by_id[louvre]["decision"] == "reject"
    request = fake_providers.get("openrouter").requests[0]
    assert len(request.messages[-1].images) == 2
    assert "Louvre" not in request.messages[-1].content  # page titles are withheld from vision

    expired = client.post(
        f"/api/projects/{project.pk}/images/check",
        {"scene_index": 0, "candidate_ids": ["webpage:never-seen"]},
        format="json",
    )
    assert expired.status_code == 409
    no_google(web)
