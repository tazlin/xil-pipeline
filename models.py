"""Pydantic data models for THE 413 podcast production pipeline.

Defines validated, typed structures for script parsing output,
cast configuration, and production dialogue entries. These models
replace untyped dictionaries with field-level validation and
type annotations that render as rich API documentation via mkdocstrings.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Script parsing models (Stage 1 output)
# ---------------------------------------------------------------------------


class ScriptEntry(BaseModel):
    """A single parsed entry from a production script.

    Each entry represents one line or block from the markdown script,
    classified into one of four types: dialogue, direction,
    section_header, or scene_header.

    Attributes:
        seq: Sequence number, 1-based and unique within a script.
        type: Entry classification determining how the line is processed.
        section: Current section slug (e.g., ``"cold-open"``, ``"act1"``).
        scene: Current scene slug (e.g., ``"scene-1"``) or ``None``.
        speaker: Normalized speaker key for dialogue entries (e.g., ``"adam"``).
        direction: Parenthetical acting direction for dialogue lines.
        text: The spoken text, header text, or stage direction content.
        direction_type: Subtype for direction entries indicating sound category.
    """

    seq: int = Field(..., gt=0, description="1-based sequence number")
    type: Literal["dialogue", "direction", "section_header", "scene_header"] = Field(
        ..., description="Entry classification"
    )
    section: str | None = Field(default=None, description="Current section slug")
    scene: str | None = Field(default=None, description="Current scene slug")
    speaker: str | None = Field(default=None, description="Normalized speaker key")
    direction: str | None = Field(default=None, description="Acting direction")
    text: str = Field(..., description="Entry content text")
    direction_type: Literal["SFX", "MUSIC", "AMBIENCE", "BEAT"] | None = Field(
        default=None, description="Sound category for direction entries"
    )


class ScriptStats(BaseModel):
    """Aggregate statistics for a parsed production script.

    Attributes:
        total_entries: Total number of parsed entries.
        dialogue_lines: Count of dialogue-type entries.
        direction_lines: Count of direction-type entries.
        characters_for_tts: Total character count across all dialogue text.
        speakers: Sorted list of unique speaker keys found in the script.
        sections: Sorted list of unique section slugs found in the script.
    """

    total_entries: int = Field(..., ge=0, description="Total parsed entries")
    dialogue_lines: int = Field(..., ge=0, description="Dialogue entry count")
    direction_lines: int = Field(..., ge=0, description="Direction entry count")
    characters_for_tts: int = Field(..., ge=0, description="TTS character budget")
    speakers: list[str] = Field(..., description="Unique speaker keys")
    sections: list[str] = Field(..., description="Unique section slugs")


class ParsedScript(BaseModel):
    """Complete output of the script parsing stage.

    Produced by ``parse_script()`` in XILP001, consumed by
    ``load_production()`` in XILP002.

    Attributes:
        show: Show title (e.g., ``"THE 413"``).
        season: Season number, or ``None`` if not declared in the script header.
        episode: Episode number.
        title: Episode title.
        source_file: Basename of the source markdown file.
        entries: Ordered list of parsed script entries.
        stats: Aggregate statistics for the parsed script.
    """

    show: str = Field(..., description="Show title")
    season: int | None = Field(default=None, description="Season number")
    episode: int = Field(..., description="Episode number")
    title: str = Field(..., description="Episode title")
    source_file: str = Field(..., description="Source markdown filename")
    entries: list[ScriptEntry] = Field(..., description="Parsed script entries")
    stats: ScriptStats = Field(..., description="Aggregate statistics")


# ---------------------------------------------------------------------------
# Cast configuration models
# ---------------------------------------------------------------------------


class CastMember(BaseModel):
    """Configuration for a single cast member's voice and audio settings.

    Maps a character to their ElevenLabs voice and stereo positioning.

    Attributes:
        full_name: Character's display name (e.g., ``"Adam Santos"``).
        voice_id: ElevenLabs voice identifier, or ``"TBD"`` if unassigned.
        pan: Stereo pan position from -1.0 (full left) to 1.0 (full right).
        filter: Whether to apply phone-speaker audio filter.
        role: Character role description (e.g., ``"Host/Narrator"``).
    """

    full_name: str = Field(..., description="Character display name")
    voice_id: str = Field(..., min_length=1, description="ElevenLabs voice ID")
    pan: float = Field(..., ge=-1.0, le=1.0, description="Stereo pan position")
    filter: bool = Field(..., description="Apply phone-speaker filter")
    role: str = Field(..., description="Character role description")


class CastConfiguration(BaseModel):
    """Complete cast configuration for a production episode.

    Loaded from ``cast_the413.json`` and used by ``load_production()``
    to map speaker keys to voice and audio settings.

    Attributes:
        show: Show title (e.g., ``"THE 413"``).
        season: Season number, or ``None`` if not set in the cast file.
        episode: Episode number.
        title: Episode title (optional, not used during production).
        cast: Mapping of speaker keys to their voice configurations.
    """

    show: str = Field(..., description="Show title")
    season: int | None = Field(default=None, description="Season number")
    episode: int = Field(..., description="Episode number")
    title: str | None = Field(default=None, description="Episode title")
    cast: dict[str, CastMember] = Field(..., description="Speaker-to-config mapping")


# ---------------------------------------------------------------------------
# Production pipeline models (Stage 2/3)
# ---------------------------------------------------------------------------


class VoiceConfig(BaseModel):
    """Simplified voice configuration used during voice generation.

    Built from ``CastMember`` by ``load_production()``, carrying only
    the fields needed for TTS generation and audio assembly.

    Attributes:
        id: ElevenLabs voice identifier.
        pan: Stereo pan position from -1.0 (full left) to 1.0 (full right).
        filter: Whether to apply phone-speaker audio filter.
    """

    id: str = Field(..., description="ElevenLabs voice ID")
    pan: float = Field(..., ge=-1.0, le=1.0, description="Stereo pan position")
    filter: bool = Field(..., description="Apply phone-speaker filter")


class DialogueEntry(BaseModel):
    """A single dialogue line prepared for voice generation.

    Produced by ``load_production()`` from parsed script entries,
    enriched with the stem filename for audio output.

    Attributes:
        speaker: Normalized speaker key (e.g., ``"adam"``).
        text: Spoken dialogue text to synthesize.
        stem_name: Output filename stem (e.g., ``"003_cold-open_adam"``).
        seq: Sequence number from the parsed script.
        direction: Acting direction for the line, if any.
    """

    speaker: str = Field(..., description="Speaker key")
    text: str = Field(..., description="Dialogue text for TTS")
    stem_name: str = Field(..., description="Output audio stem name")
    seq: int = Field(..., gt=0, description="1-based sequence number")
    direction: str | None = Field(default=None, description="Acting direction")
