from fastapi import APIRouter, HTTPException

from app.agents.idea_agent import IdeaAgentError, run_idea_agent
from app.agents.director_agent import DirectorAgentError, run_director_pipeline
from app.agents.producer_agent import ProducerAgentError, run_producer_agent
from app.agents.researcher_agent import ResearcherAgentError, run_researcher_agent
from app.agents.screenwriter_agent import ScreenwriterAgentError, run_screenwriter_agent
from app.agents.video_editor_agent import VideoEditorAgentError, run_video_editor_agent
from app.models.idea import IdeaReport, IdeaRequest
from app.models.director import DirectorReport, DirectorRequest
from app.models.producer import ProducerReport, ProducerRequest
from app.models.researcher import ResearcherReport, ResearcherRequest
from app.models.screenwriter import ScreenwriterReport, ScreenwriterRequest
from app.models.video_editor import VideoEditorReport, VideoEditorRequest


router = APIRouter()


@router.post(
    "/ideas",
    response_model=IdeaReport,
)
def idea_agent(request: IdeaRequest) -> IdeaReport:
    try:
        return IdeaReport(
            **run_idea_agent(
                topic=request.topic,
                context=request.context,
                audience=request.audience,
                idea_count=request.idea_count,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IdeaAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/research",
    response_model=ResearcherReport,
)
def researcher_agent(request: ResearcherRequest) -> ResearcherReport:
    try:
        return ResearcherReport(
            **run_researcher_agent(
                task=request.task,
                context=request.context,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ResearcherAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/screenwrite",
    response_model=ScreenwriterReport,
)
def screenwriter_agent(request: ScreenwriterRequest) -> ScreenwriterReport:
    try:
        return ScreenwriterReport(
            **run_screenwriter_agent(
                task=request.task,
                context=request.context,
                research=request.research,
                target_words=request.target_words,
                style=request.style,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ScreenwriterAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/edit-video",
    response_model=VideoEditorReport,
)
def video_editor_agent(request: VideoEditorRequest) -> VideoEditorReport:
    try:
        return VideoEditorReport(
            **run_video_editor_agent(
                edit_brief=request.edit_brief,
                script=request.script,
                context=request.context,
                research=request.research,
                source_production=request.source_production,
                short_format=request.short_format,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VideoEditorAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/director",
    response_model=DirectorReport,
)
def director_agent(request: DirectorRequest) -> DirectorReport:
    try:
        return DirectorReport(
            **run_director_pipeline(
                task=request.task,
                context=request.context,
                produce_short=request.produce_short,
                short_format=request.short_format,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DirectorAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/produce-short",
    response_model=ProducerReport,
)
def producer_agent(request: ProducerRequest) -> ProducerReport:
    try:
        return ProducerReport(
            **run_producer_agent(
                script=request.script,
                context=request.context,
                short_format=request.short_format,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProducerAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
