from typing import Any, Dict

from app.agents.producer_agent import ProducerAgentError, run_producer_agent
from app.agents.researcher_agent import ResearcherAgentError, run_researcher_agent


class MasterAgentError(Exception):
    pass


def run_master_agent(
    task: str,
    context: str | None = None,
    produce_short: bool = True,
    short_format: str = "auto",
) -> Dict[str, Any]:
    """Run research via the main researcher agent, then optionally produce a short."""
    try:
        result = run_researcher_agent(task=task, context=context)
        result["production"] = None
        if produce_short:
            try:
                source_text = task.strip()
                if context and context.strip():
                    source_text = f"{task.strip()} {context.strip()}"
                result["production"] = run_producer_agent(
                    script=result["short_video_script"],
                    context=context,
                    short_format=short_format,
                    source_text=source_text,
                )
            except ProducerAgentError as exc:
                raise MasterAgentError(
                    f"Short production failed: {exc}"
                ) from exc
        return result
    except ResearcherAgentError as exc:
        raise MasterAgentError(str(exc)) from exc
    except MasterAgentError:
        raise
    except Exception as exc:
        raise MasterAgentError(
            f"Master agent failed: {exc}"
        ) from exc
