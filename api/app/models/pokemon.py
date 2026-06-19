from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PokemonSprites(BaseModel):
    official_artwork: Optional[str] = None
    official_artwork_shiny: Optional[str] = None
    front_default: Optional[str] = None
    front_shiny: Optional[str] = None


class PokemonData(BaseModel):
    id: int
    name: str
    display_name: str
    genus: Optional[str] = None
    description: Optional[str] = None
    types: List[str]
    abilities: List[str]
    stats: Dict[str, int]
    height_metres: float
    weight_kilograms: float
    base_experience: Optional[int] = None
    habitat: Optional[str] = None
    color: Optional[str] = None
    generation: Optional[str] = None
    is_legendary: bool
    is_mythical: bool
    sprites: PokemonSprites


class PokemonResearchRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=100)
    question: str = Field(
        "Provide a factual Pokemon research briefing.",
        min_length=1,
        max_length=1000,
    )


class PokemonResearchReport(BaseModel):
    pokemon: str
    pokedex_number: int
    researched_at: str
    summary: str
    verified_facts: List[str]
    stat_profile: List[str]
    notable_traits: List[str]
    content_hooks: List[str]
    short_video_script: str
    limitations: List[str]
    source: str
    pokemon_data: Dict[str, Any]
