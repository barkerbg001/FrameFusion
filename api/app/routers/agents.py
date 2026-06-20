from fastapi import APIRouter, HTTPException

from app.agents.cinematography_agent import (
    CinematographyAgentError,
    run_cinematography_agent,
)
from app.agents.director_planning import DirectorPlanningError, run_director_brief
from app.agents.idea_agent import IdeaAgentError, run_idea_agent
from app.agents.director_agent import DirectorAgentError, run_director_pipeline
from app.agents.music_composer_agent import (
    MusicComposerAgentError,
    run_music_composer_agent,
)
from app.agents.music_director_agent import (
    MusicDirectorAgentError,
    run_music_director_agent,
)
from app.agents.production_pipeline import (
    ProductionPipelineError,
    run_production_pipeline,
)
from app.agents.producer_agent import ProducerAgentError, run_producer_agent
from app.agents.registry import list_agents
from app.agents.researcher_agent import ResearcherAgentError, run_researcher_agent
from app.agents.screenwriter_agent import ScreenwriterAgentError, run_screenwriter_agent
from app.agents.sound_design_agent import SoundDesignAgentError, run_sound_design_agent
from app.agents.video_editor_agent import VideoEditorAgentError, run_video_editor_agent
from app.agents.visual_agent import VisualAgentError, run_visual_agent
from app.agents.voice_agent import VoiceAgentError, run_voice_agent
from app.agents.workflow_agent import WorkflowAgentError, run_workflow_agent
from app.models.idea import IdeaReport, IdeaRequest
from app.models.director import DirectorReport, DirectorRequest
from app.models.music_composer import MusicComposerReport, MusicComposerRequest
from app.models.producer import ProducerReport, ProducerRequest
from app.models.production import (
    AgentTaskRequest,
    CinematographyRequest,
    DirectorBrief,
    CinematographyReport,
    MusicDirectorReport,
    MusicDirectorRequest,
    ProductionReport,
    ProductionRequest,
    SoundDesignReport,
    SoundDesignRequest,
    VisualReport,
    VisualRequest,
    VoiceReport,
    VoiceRequest,
    WorkflowPlan,
    WorkflowRequest,
)
from app.models.researcher import ResearcherReport, ResearcherRequest
from app.models.screenwriter import ScreenwriterReport, ScreenwriterRequest
from app.models.video_editor import VideoEditorReport, VideoEditorRequest


router = APIRouter()


@router.get("/registry")
def agent_registry() -> list[dict[str, object]]:
    return list_agents()


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
                cinematography=request.cinematography,
                visual=request.visual,
                voice=request.voice,
                music_director=request.music_director,
                sound_design=request.sound_design,
                score_with_music=request.score_with_music,
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


@router.post(
    "/compose-music",
    response_model=MusicComposerReport,
)
def music_composer_agent(request: MusicComposerRequest) -> MusicComposerReport:
    try:
        return MusicComposerReport(
            **run_music_composer_agent(
                brief=request.brief,
                context=request.context,
                duration_seconds=request.duration_seconds,
                mood=request.mood,
                genre=request.genre,
                instrumental=request.instrumental,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MusicComposerAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/production", response_model=ProductionReport)
def production_pipeline(request: ProductionRequest) -> ProductionReport:
    try:
        return ProductionReport(
            **run_production_pipeline(
                task=request.task,
                context=request.context,
                render_video=request.render_video,
                short_format=request.short_format,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProductionPipelineError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/director-brief", response_model=DirectorBrief)
def director_brief(request: AgentTaskRequest) -> DirectorBrief:
    try:
        return DirectorBrief(**run_director_brief(request.task, request.context))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DirectorPlanningError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/workflow", response_model=WorkflowPlan)
def workflow_agent(request: WorkflowRequest) -> WorkflowPlan:
    try:
        return WorkflowPlan(
            **run_workflow_agent(
                task=request.task,
                context=request.context,
                director_brief=request.director_brief,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkflowAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/cinematography", response_model=CinematographyReport)
def cinematography_agent(request: CinematographyRequest) -> CinematographyReport:
    try:
        return CinematographyReport(
            **run_cinematography_agent(
                task=request.task,
                context=request.context,
                research=request.research,
                script=request.script,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CinematographyAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/visual", response_model=VisualReport)
def visual_agent_endpoint(request: VisualRequest) -> VisualReport:
    try:
        return VisualReport(
            **run_visual_agent(
                task=request.task,
                context=request.context,
                research=request.research,
                cinematography=request.cinematography,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VisualAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/voice", response_model=VoiceReport)
def voice_agent_endpoint(request: VoiceRequest) -> VoiceReport:
    try:
        return VoiceReport(
            **run_voice_agent(
                task=request.task,
                context=request.context,
                script=request.script,
                short_format=request.short_format,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VoiceAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/music-director", response_model=MusicDirectorReport)
def music_director_agent_endpoint(
    request: MusicDirectorRequest,
) -> MusicDirectorReport:
    try:
        return MusicDirectorReport(
            **run_music_director_agent(
                task=request.task,
                context=request.context,
                script=request.script,
                cinematography=request.cinematography,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MusicDirectorAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sound-design", response_model=SoundDesignReport)
def sound_design_agent_endpoint(request: SoundDesignRequest) -> SoundDesignReport:
    try:
        return SoundDesignReport(
            **run_sound_design_agent(
                task=request.task,
                context=request.context,
                cinematography=request.cinematography,
                music_director=request.music_director,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SoundDesignAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
