import json
import re
from functools import lru_cache
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


POKEAPI_BASE_URL = "https://pokeapi.co/api/v2"
POKEMON_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9-]+$")


class PokemonNotFoundError(Exception):
    pass


class PokemonServiceError(Exception):
    pass


def _normalize_identifier(identifier: str) -> str:
    normalized = identifier.strip().lower().replace(" ", "-")
    if not normalized or not POKEMON_IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Pokemon identifier must be a name or positive Pokedex number"
        )
    if normalized.isdigit() and int(normalized) < 1:
        raise ValueError("Pokedex number must be greater than zero")
    return normalized


@lru_cache(maxsize=512)
def _get_json(url: str) -> Dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FrameFusion/1.0",
        },
    )

    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            raise PokemonNotFoundError("Pokemon not found") from exc
        raise PokemonServiceError(
            f"PokeAPI returned HTTP {exc.code}"
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise PokemonServiceError("Unable to retrieve Pokemon data") from exc


def _english_value(
    entries: list[Dict[str, Any]],
    value_key: str,
) -> Optional[str]:
    for entry in reversed(entries):
        if entry.get("language", {}).get("name") == "en":
            value = entry.get(value_key)
            if value:
                return " ".join(value.replace("\f", " ").split())
    return None


def _display_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("-"))


def get_pokemon_data(identifier: str) -> Dict[str, Any]:
    """Return normalized Pokemon data by name or Pokedex number."""
    normalized = _normalize_identifier(identifier)
    pokemon = _get_json(f"{POKEAPI_BASE_URL}/pokemon/{normalized}")
    species = _get_json(pokemon["species"]["url"])
    sprites = pokemon.get("sprites") or {}
    artwork = sprites.get("other", {}).get("official-artwork", {})

    return {
        "id": pokemon["id"],
        "name": pokemon["name"],
        "display_name": _display_name(pokemon["name"]),
        "genus": _english_value(species.get("genera", []), "genus"),
        "description": _english_value(
            species.get("flavor_text_entries", []),
            "flavor_text",
        ),
        "types": [
            item["type"]["name"]
            for item in sorted(
                pokemon.get("types", []),
                key=lambda item: item["slot"],
            )
        ],
        "abilities": [
            item["ability"]["name"]
            for item in pokemon.get("abilities", [])
        ],
        "stats": {
            item["stat"]["name"]: item["base_stat"]
            for item in pokemon.get("stats", [])
        },
        "height_metres": pokemon["height"] / 10,
        "weight_kilograms": pokemon["weight"] / 10,
        "base_experience": pokemon.get("base_experience"),
        "habitat": (species.get("habitat") or {}).get("name"),
        "color": (species.get("color") or {}).get("name"),
        "generation": (species.get("generation") or {}).get("name"),
        "is_legendary": species.get("is_legendary", False),
        "is_mythical": species.get("is_mythical", False),
        "sprites": {
            "official_artwork": artwork.get("front_default"),
            "official_artwork_shiny": artwork.get("front_shiny"),
            "front_default": sprites.get("front_default"),
            "front_shiny": sprites.get("front_shiny"),
        },
    }
