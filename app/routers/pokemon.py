from fastapi import APIRouter, HTTPException, Path

from app.models.pokemon import PokemonData
from app.services.pokemon_client import (
    PokemonNotFoundError,
    PokemonServiceError,
    get_pokemon_data,
)


router = APIRouter()


@router.get("/{identifier}", response_model=PokemonData)
def get_pokemon(
    identifier: str = Path(
        ...,
        min_length=1,
        max_length=100,
        description="Pokemon name or National Pokedex number",
        examples=["pikachu"],
    ),
) -> PokemonData:
    try:
        return PokemonData(**get_pokemon_data(identifier))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PokemonNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Pokemon '{identifier}' was not found",
        ) from exc
    except PokemonServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
