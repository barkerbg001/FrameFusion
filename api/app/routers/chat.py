from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.agents.director_agent import DirectorAgentError, run_director_chat
from app.models.chat import ChatAttachment, ChatMessage, ChatRequest, ChatResponse, VideoListItem
from app.services.video_producer import GENERATED_DIR

router = APIRouter()


@router.get("/health")
def chat_health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/videos", response_model=list[VideoListItem])
def list_chat_videos() -> list[VideoListItem]:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    items: list[VideoListItem] = []
    for path in sorted(
        GENERATED_DIR.glob("*.mp4"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        file_name = path.name
        download_name = file_name.split("_", 1)[-1] if "_" in file_name else file_name
        items.append(
            VideoListItem(
                url=f"/api/chat/videos/{quote(file_name)}",
                filename=download_name,
                created_at=int(path.stat().st_mtime),
            )
        )
    return items


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        result = run_director_chat(request.messages)
        return ChatResponse(
            message=ChatMessage(role="assistant", content=result.content),
            attachments=[ChatAttachment(**item) for item in result.attachments],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DirectorAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/videos/{file_name}")
def get_chat_video(file_name: str) -> FileResponse:
    if (
        not file_name
        or file_name != file_name.split("/")[-1]
        or file_name != file_name.split("\\")[-1]
        or ".." in file_name
    ):
        raise HTTPException(status_code=400, detail="Invalid file name")

    generated_root = GENERATED_DIR.resolve()
    video_path = (GENERATED_DIR / file_name).resolve()

    if video_path.parent != generated_root or not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video not found")

    download_name = file_name.split("_", 1)[-1] if "_" in file_name else file_name
    return FileResponse(
        path=video_path,
        media_type="video/mp4",
        filename=download_name,
    )
