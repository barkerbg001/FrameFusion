"""Free procedural background music when no ElevenLabs key is available."""

import hashlib
import math
import wave
from pathlib import Path

import numpy as np


SAMPLE_RATE = 44100


def _prompt_seed(prompt: str) -> int:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _mood_from_prompt(prompt: str) -> dict[str, float]:
    lowered = prompt.lower()
    tempo = 72.0
    brightness = 0.45
    energy = 0.35

    if any(word in lowered for word in ("fast", "upbeat", "energetic", "action", "hype")):
        tempo = 118.0
        energy = 0.75
        brightness = 0.65
    elif any(word in lowered for word in ("slow", "calm", "ambient", "relax", "sleep")):
        tempo = 58.0
        energy = 0.2
        brightness = 0.3
    elif any(word in lowered for word in ("dark", "cinematic", "tense", "dramatic")):
        tempo = 64.0
        energy = 0.55
        brightness = 0.22
    elif any(word in lowered for word in ("lofi", "lo-fi", "chill", "study", "jazz")):
        tempo = 78.0
        energy = 0.4
        brightness = 0.38

    return {"tempo": tempo, "brightness": brightness, "energy": energy}


def _note_frequency(note_index: int, root_hz: float = 220.0) -> float:
    return root_hz * (2 ** (note_index / 12))


def _apply_envelope(signal: np.ndarray, attack: float, release: float) -> np.ndarray:
    length = len(signal)
    attack_samples = max(1, int(SAMPLE_RATE * attack))
    release_samples = max(1, int(SAMPLE_RATE * release))
    envelope = np.ones(length, dtype=np.float64)
    envelope[:attack_samples] = np.linspace(0.0, 1.0, attack_samples)
    envelope[-release_samples:] = np.linspace(1.0, 0.0, release_samples)
    return signal * envelope


def generate_procedural_music(
    prompt: str,
    output_path: str,
    duration_seconds: int = 30,
) -> str:
    """Render a simple instrumental WAV track from a text prompt."""
    clamped_seconds = max(5, min(duration_seconds, 180))
    total_samples = SAMPLE_RATE * clamped_seconds
    rng = np.random.default_rng(_prompt_seed(prompt))
    mood = _mood_from_prompt(prompt)

    timeline = np.linspace(0.0, clamped_seconds, total_samples, endpoint=False)
    mix = np.zeros(total_samples, dtype=np.float64)

    chord_sets = [
        [0, 4, 7],
        [2, 5, 9],
        [4, 7, 11],
        [5, 9, 0],
    ]
    beat_interval = 60.0 / mood["tempo"]
    bar_seconds = beat_interval * 4

    for bar_index, start in enumerate(np.arange(0.0, clamped_seconds, bar_seconds)):
        end = min(start + bar_seconds, clamped_seconds)
        start_idx = int(start * SAMPLE_RATE)
        end_idx = int(end * SAMPLE_RATE)
        if end_idx <= start_idx:
            continue

        chord = chord_sets[bar_index % len(chord_sets)]
        bar_length = end_idx - start_idx
        bar_signal = np.zeros(bar_length, dtype=np.float64)

        for note in chord:
            frequency = _note_frequency(note + int(rng.integers(-1, 2)))
            phase = np.linspace(
                0.0,
                2.0 * math.pi * frequency * (bar_length / SAMPLE_RATE),
                bar_length,
                endpoint=False,
            )
            tone = np.sin(phase) * 0.55 + np.sin(phase * 2.0) * 0.15
            bar_signal += tone

        bar_signal /= max(len(chord), 1)
        bar_signal = _apply_envelope(bar_signal, attack=0.08, release=0.35)
        mix[start_idx:end_idx] += bar_signal * (0.18 + mood["brightness"] * 0.12)

        if mood["energy"] > 0.25:
            for beat in np.arange(start, end, beat_interval):
                beat_idx = int(beat * SAMPLE_RATE)
                if beat_idx >= total_samples:
                    break
                click_len = min(int(SAMPLE_RATE * 0.03), total_samples - beat_idx)
                click = np.linspace(1.0, 0.0, click_len) * (0.08 + mood["energy"] * 0.08)
                mix[beat_idx : beat_idx + click_len] += click

    shimmer = rng.normal(0.0, 0.004, total_samples)
    mix += shimmer
    mix *= np.linspace(0.0, 1.0, total_samples)
    mix *= np.linspace(1.0, 0.0, total_samples)

    peak = np.max(np.abs(mix)) or 1.0
    mix = np.clip(mix / peak * 0.85, -1.0, 1.0)
    pcm = (mix * 32767).astype(np.int16)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())

    return str(output.resolve())
