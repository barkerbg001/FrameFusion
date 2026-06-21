from datetime import datetime, timezone
from typing import Any, Dict, List

from app.agents.cinematography_agent import (
    CinematographyAgentError,
    run_cinematography_agent,
)
from app.agents.director_planning import DirectorPlanningError, run_director_brief
from app.agents.music_director_agent import (
    MusicDirectorAgentError,
    run_music_director_agent,
)
from app.agents.registry import list_agents
from app.agents.researcher_agent import ResearcherAgentError, run_researcher_agent
from app.agents.screenwriter_agent import ScreenwriterAgentError, run_screenwriter_agent
from app.agents.sound_design_agent import SoundDesignAgentError, run_sound_design_agent
from app.agents.video_editor_agent import VideoEditorAgentError, run_video_editor_agent
from app.agents.visual_agent import VisualAgentError, run_visual_agent
from app.agents.voice_agent import VoiceAgentError, run_voice_agent
from app.agents.workflow_agent import WorkflowAgentError, run_workflow_agent
from app.models.production import ProductionReport
from app.models.video_editor import VideoEditorReport


class ProductionPipelineError(Exception):
    pass


def _collect_limitations(*reports: Dict[str, Any] | None) -> List[str]:
    limitations: List[str] = []
    for report in reports:
        if not report:
            continue
        for item in report.get("limitations", []):
            if isinstance(item, str) and item not in limitations:
                limitations.append(item)
    return limitations


def run_production_pipeline(
    task: str,
    context: str | None = None,
    render_video: bool = True,
    short_format: str = "auto",
) -> Dict[str, Any]:
    """Run the full production studio pipeline from Director brief through Editor."""
    normalized_task = " ".join(task.strip().split())
    if len(normalized_task) < 5:
        raise ValueError("task must contain at least five characters")

    produced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pipeline_steps: List[str] = []

    try:
        director = run_director_brief(task=normalized_task, context=context)
        pipeline_steps.append("director")

        workflow = run_workflow_agent(
            task=normalized_task,
            context=context,
            director_brief=director,
        )
        pipeline_steps.append("producer")

        research = run_researcher_agent(task=normalized_task, context=context)
        pipeline_steps.append("research")

        script = run_screenwriter_agent(
            task=normalized_task,
            context=context,
            research=research,
        )
        pipeline_steps.append("script")

        cinematography = run_cinematography_agent(
            task=normalized_task,
            context=context,
            research=research,
            script=script,
        )
        pipeline_steps.append("cinematography")

        visual = run_visual_agent(
            task=normalized_task,
            context=context,
            research=research,
            cinematography=cinematography,
        )
        pipeline_steps.append("visual")

        voice = run_voice_agent(
            task=normalized_task,
            context=context,
            script=script,
            short_format=short_format,
        )
        pipeline_steps.append("voice")

        music_director = run_music_director_agent(
            task=normalized_task,
            context=context,
            script=script,
            cinematography=cinematography,
        )
        pipeline_steps.append("music_director")

        sound_design = run_sound_design_agent(
            task=normalized_task,
            context=context,
            cinematography=cinematography,
            music_director=music_director,
        )
        pipeline_steps.append("sound_design")

        editor_report = None
        if render_video:
            editor_context_parts = [
                context or "",
                f"Director vision: {director.get('creative_vision', '')}",
                f"Visual style: {visual.get('visual_style', '')}",
                f"Voice approach: {voice.get('narration_approach', '')}",
                f"Music style: {music_director.get('overall_style', '')}",
            ]
            editor_context = "\n".join(
                part.strip() for part in editor_context_parts if part.strip()
            )
            editor_result = run_video_editor_agent(
                edit_brief=normalized_task,
                script=script["short_video_script"],
                context=editor_context or None,
                research=research,
                short_format=short_format,
                cinematography=cinematography,
                visual=visual,
                voice=voice,
                music_director=music_director,
                sound_design=sound_design,
                score_with_music=True,
            )
            editor_report = VideoEditorReport(**editor_result)
            pipeline_steps.append("editor")
            if editor_report.edit_data.get("music_scored"):
                pipeline_steps.append("music_score")

        limitations = _collect_limitations(
            research,
            script,
            cinematography,
            visual,
            voice,
            music_director,
            sound_design,
        )
        if workflow.get("risks"):
            for risk in workflow["risks"]:
                note = f"Production risk: {risk}"
                if note not in limitations:
                    limitations.append(note)

        report = ProductionReport(
            task=normalized_task,
            produced_at=produced_at,
            pipeline=pipeline_steps,
            director=director,
            workflow=workflow,
            research=research,
            script=script,
            cinematography=cinematography,
            visual=visual,
            voice=voice,
            music_director=music_director,
            sound_design=sound_design,
            editor=editor_report,
            limitations=limitations,
        )
        return report.model_dump()
    except (
        DirectorPlanningError,
        WorkflowAgentError,
        ResearcherAgentError,
        ScreenwriterAgentError,
        CinematographyAgentError,
        VisualAgentError,
        VoiceAgentError,
        MusicDirectorAgentError,
        SoundDesignAgentError,
        VideoEditorAgentError,
    ) as exc:
        raise ProductionPipelineError(str(exc)) from exc
    except ProductionPipelineError:
        raise
    except Exception as exc:
        raise ProductionPipelineError(
            f"Production pipeline failed: {exc}"
        ) from exc
