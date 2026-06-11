import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.models.pokemon import PokemonResearchReport
from app.services.pokemon_client import get_pokemon_data


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


class PokemonAgentError(Exception):
    pass


def research_pokemon_tool(identifier: str) -> str:
    """Gets verified Pokemon data by name or National Pokedex number.

    Args:
        identifier: A Pokemon name or positive National Pokedex number.

    Returns:
        A JSON string containing verified PokeAPI data.
    """
    return json.dumps(get_pokemon_data(identifier))


def research_pokemon(
    identifier: str,
    question: str = "Provide a factual Pokemon research briefing.",
) -> Dict[str, Any]:
    """Run the Gemini Pokemon researcher and return a structured report."""
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise PokemonAgentError("GEMINI_API_KEY is not configured")

    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    client = genai.Client(api_key=api_key)
    researched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    research_prompt = f"""
You are FrameFusion's Pokemon research agent.

Pokemon requested: {identifier}
User's question: {question}

You must call research_pokemon_tool before answering. Base every factual claim
on the returned PokeAPI data. You may interpret the supplied base stats, but
clearly avoid unsupported claims about moves, evolution, competitive tiers,
type matchups, games, anime events, or lore not present in the tool response.

Prepare a concise factual research draft for a short-form content creator.
Include useful observations about its identity, types, abilities, physical
measurements, classification, generation, rarity flags, and base-stat profile.
"""

    try:
        research_response = client.models.generate_content(
            model=model,
            contents=research_prompt,
            config=types.GenerateContentConfig(
                tools=[research_pokemon_tool],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="AUTO",
                    )
                ),
                temperature=0.2,
            ),
        )
        pokemon_data = json.loads(research_pokemon_tool(identifier))
        format_prompt = f"""
Convert the Pokemon research below into the required response schema.

Pokemon requested: {identifier}
Question: {question}
Researched at UTC: {researched_at}
Research draft:
{research_response.text}

Authoritative source data:
{json.dumps(pokemon_data)}

Requirements:
- Set pokemon to the source display_name.
- Set pokedex_number to the source id.
- Set source to "PokeAPI".
- Include only claims supported by the authoritative source data.
- verified_facts should contain concise independently useful facts.
- stat_profile may compare the supplied base stats to one another, but must not
  claim competitive viability or rankings.
- content_hooks should be factual hooks suitable for short-form videos.
- short_video_script should be approximately 45 to 90 words and should not
  include production directions.
- Mention missing evolution, move, matchup, and game-specific data in
  limitations when relevant.
"""
        response = client.models.generate_content(
            model=model,
            contents=format_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PokemonResearchReport,
                temperature=0,
            ),
        )
        report = PokemonResearchReport.model_validate_json(response.text)
        report.pokemon = pokemon_data["display_name"]
        report.pokedex_number = pokemon_data["id"]
        report.researched_at = researched_at
        report.source = "PokeAPI"
        report.pokemon_data = pokemon_data
        return report.model_dump()
    except Exception as exc:
        raise PokemonAgentError(
            f"Pokemon research agent failed: {exc}"
        ) from exc
