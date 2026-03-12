"""Shared multi-track mixing utilities for THE 413 audio pipeline.

Provides timeline construction and per-layer audio building used by
XILP003 (automated two-pass mix) and XILP005 (DAW layer export).
Both stages classify stems by direction_type from the parsed script
JSON, then build foreground (dialogue/SFX) and background (ambience/
music) layers independently before combining.

Module Attributes:
    BACKGROUND_DIRECTION_TYPES: direction_type values routed to the
        background layer rather than the foreground timeline.
    AMBIENCE_LEVEL_DB: Default dB reduction applied to ambience overlays
        in the automated mix (Option A). 0 for DAW export (Option C).
    MUSIC_LEVEL_DB: Default dB reduction applied to music overlays
        in the automated mix. 0 for DAW export.
"""

import glob
import json
import os
from dataclasses import dataclass

from pydub import AudioSegment

# Background direction types — excluded from the foreground timeline,
# overlaid at their cue positions in a separate background pass.
BACKGROUND_DIRECTION_TYPES: frozenset[str] = frozenset({"AMBIENCE", "MUSIC"})

# Default level adjustments for the automated mixed master (Option A).
# Use 0 for DAW export layers so the producer controls levels in-DAW.
AMBIENCE_LEVEL_DB: float = -10.0
MUSIC_LEVEL_DB: float = -6.0


@dataclass
class StemPlan:
    """Resolved metadata for a single audio stem file.

    Attributes:
        seq: Sequence number extracted from the stem filename.
        filepath: Absolute or relative path to the MP3 stem file.
        direction_type: Parsed direction category for this entry
            (``"SFX"``, ``"MUSIC"``, ``"AMBIENCE"``, ``"BEAT"``),
            or ``None`` for dialogue stems.
        entry_type: Parsed entry classification (``"dialogue"``,
            ``"direction"``, etc.), or ``None`` if not in index.
    """

    seq: int
    filepath: str
    direction_type: str | None
    entry_type: str | None
    text: str | None = None

    @property
    def is_background(self) -> bool:
        """True if this stem belongs in the background layer."""
        return self.direction_type in BACKGROUND_DIRECTION_TYPES


def extract_seq(filepath: str) -> int:
    """Extract the sequence number from a stem filename.

    Stems are named ``{seq:03d}_{section}[-{scene}]_{speaker}.mp3``.
    The leading zero-padded integer is the sequence number.

    Args:
        filepath: Path like ``stems/S01E01/003_cold-open_adam.mp3``.

    Returns:
        Integer sequence number (e.g. ``"003"`` → ``3``).
    """
    basename = os.path.splitext(os.path.basename(filepath))[0]
    return int(basename.split("_")[0])


def load_entries_index(parsed_path: str) -> dict[int, dict]:
    """Load a parsed script JSON and return a ``{seq: entry}`` index.

    Args:
        parsed_path: Path to the parsed script JSON produced by XILP001.

    Returns:
        Dict mapping each sequence number to its full entry dict.
    """
    with open(parsed_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {entry["seq"]: entry for entry in data["entries"]}


def collect_stem_plans(
    stems_dir: str, entries_index: dict[int, dict]
) -> list[StemPlan]:
    """Collect and classify all MP3 stems in a stems directory.

    Uses the entries index to look up each stem's ``direction_type``
    and ``entry_type`` by sequence number. Stems whose seq is not in
    the index are treated as foreground (dialogue) to ensure they are
    always included in the output.

    Args:
        stems_dir: Directory containing episode stem MP3 files.
        entries_index: ``{seq: entry}`` mapping from
            :func:`load_entries_index`.

    Returns:
        List of :class:`StemPlan` instances sorted by sequence number.
    """
    stem_files = sorted(glob.glob(os.path.join(stems_dir, "*.mp3")))
    plans = []
    for filepath in stem_files:
        seq = extract_seq(filepath)
        entry = entries_index.get(seq, {})
        plans.append(StemPlan(
            seq=seq,
            filepath=filepath,
            direction_type=entry.get("direction_type"),
            entry_type=entry.get("type"),
            text=entry.get("text"),
        ))
    return plans


def apply_phone_filter(segment: AudioSegment) -> AudioSegment:
    """Apply a phone-speaker audio filter to an audio segment.

    Cuts frequencies below 300 Hz and above 3000 Hz, then boosts
    volume by 5 dB to simulate a telephone speaker.

    Args:
        segment: Input audio segment to filter.

    Returns:
        Filtered audio segment.
    """
    return segment.high_pass_filter(300).low_pass_filter(3000) + 5


def build_foreground(
    stem_plans: list[StemPlan],
    cast_config: dict,
    apply_effects_fn=None,
    gap_ms: int = 600,
) -> tuple[AudioSegment, dict[int, int]]:
    """Build the foreground audio track and a full-episode timeline.

    Iterates stems in sequence order. Foreground stems (dialogue, SFX,
    BEAT) are concatenated with silence gaps and their positions are
    recorded in the timeline. Background stems (AMBIENCE, MUSIC) are
    recorded in the timeline at the current foreground cursor position
    but do not advance it — they are overlaid at that cue point in a
    separate background pass.

    Args:
        stem_plans: Classified stem list from :func:`collect_stem_plans`.
        cast_config: ``{speaker_key: {"pan": float, "filter": bool}}``
            for per-speaker audio effects.
        apply_effects_fn: Optional callable applied to speakers with
            ``filter=True`` (typically :func:`apply_phone_filter`).
            Pass ``None`` to skip phone filtering.
        gap_ms: Silence inserted between foreground stems in ms.

    Returns:
        Tuple of ``(foreground_audio, timeline)`` where ``timeline``
        maps sequence numbers to millisecond offsets within the
        foreground track.
    """
    foreground = AudioSegment.empty()
    timeline: dict[int, int] = {}
    current_ms = 0

    for plan in sorted(stem_plans, key=lambda p: p.seq):
        # Record cue position for ALL stems (both fg and bg).
        # Background stems don't advance current_ms — they overlay.
        timeline[plan.seq] = current_ms

        if plan.is_background:
            continue

        segment = AudioSegment.from_file(plan.filepath)

        # Apply per-speaker effects to dialogue stems.
        basename = os.path.splitext(os.path.basename(plan.filepath))[0]
        speaker = basename.rsplit("_", 1)[-1]
        if speaker in cast_config:
            if cast_config[speaker].get("filter") and apply_effects_fn:
                segment = apply_effects_fn(segment)
            segment = segment.pan(cast_config[speaker].get("pan", 0.0))

        foreground += segment + AudioSegment.silent(duration=gap_ms)
        current_ms += len(segment) + gap_ms

    return foreground, timeline


def _loop_clip(clip: AudioSegment, duration_ms: int) -> AudioSegment:
    """Loop an audio clip to fill exactly ``duration_ms`` milliseconds.

    Args:
        clip: Source audio clip to repeat.
        duration_ms: Target duration in milliseconds.

    Returns:
        Audio segment of exactly ``duration_ms`` length, or a silent
        segment if ``clip`` is empty or ``duration_ms`` is zero.
    """
    if len(clip) == 0 or duration_ms <= 0:
        return AudioSegment.silent(duration=max(0, duration_ms))
    repeats = -(-duration_ms // len(clip))  # ceiling division
    return (clip * repeats)[:duration_ms]


def build_ambience_layer(
    stem_plans: list[StemPlan],
    timeline: dict[int, int],
    total_ms: int,
    level_db: float = AMBIENCE_LEVEL_DB,
) -> AudioSegment:
    """Build the ambience background layer.

    Each AMBIENCE stem is looped from its cue point to the start of
    the next background cue (AMBIENCE or MUSIC) or the end of the
    track, whichever comes first. The ``level_db`` parameter controls
    ducking; use ``0`` for DAW layer export so the producer controls
    levels in-DAW.

    Args:
        stem_plans: Classified stem list from :func:`collect_stem_plans`.
        timeline: Cue-point timestamps from :func:`build_foreground`.
        total_ms: Total foreground track length in milliseconds.
        level_db: Volume adjustment applied to the clip before looping.
            Negative values duck the ambience below dialogue.

    Returns:
        Tuple of ``(layer, labels)`` where *layer* is a full-length
        :class:`~pydub.AudioSegment` with ambience looped at each cue
        point, and *labels* is a list of ``(start_sec, end_sec, text)``
        tuples spanning each looped region.
    """
    layer = AudioSegment.silent(duration=total_ms)
    labels: list[tuple[float, float, str]] = []
    ambience_plans = sorted(
        (p for p in stem_plans if p.direction_type == "AMBIENCE"),
        key=lambda p: p.seq,
    )
    if not ambience_plans:
        return layer, labels

    # All background cue ms values (AMBIENCE + MUSIC) sorted by position.
    bg_cues: list[tuple[int, int]] = sorted(
        (
            (timeline.get(p.seq, 0), p.seq)
            for p in stem_plans
            if p.is_background
        ),
        key=lambda t: t[0],
    )

    for plan in ambience_plans:
        start_ms = timeline.get(plan.seq, 0)
        if start_ms >= total_ms:
            continue

        # End at the next background cue after this one, or track end.
        end_ms = total_ms
        for cue_ms, cue_seq in bg_cues:
            if cue_seq > plan.seq and cue_ms > start_ms:
                end_ms = min(cue_ms, total_ms)
                break

        duration_needed = end_ms - start_ms
        if duration_needed <= 0:
            continue

        clip = AudioSegment.from_file(plan.filepath)
        if level_db != 0:
            clip = clip + level_db
        looped = _loop_clip(clip, duration_needed)
        layer = layer.overlay(looped, position=start_ms)
        label_text = plan.text or plan.direction_type or "AMBIENCE"
        labels.append((start_ms / 1000.0, end_ms / 1000.0, label_text))

    return layer, labels


def build_music_layer(
    stem_plans: list[StemPlan],
    timeline: dict[int, int],
    total_ms: int,
    level_db: float = MUSIC_LEVEL_DB,
) -> AudioSegment:
    """Build the music/sting background layer.

    Each MUSIC stem is overlaid at its cue point without looping.
    Use ``level_db=0`` for DAW layer export so levels are set in-DAW.

    Args:
        stem_plans: Classified stem list from :func:`collect_stem_plans`.
        timeline: Cue-point timestamps from :func:`build_foreground`.
        total_ms: Total foreground track length in milliseconds.
        level_db: Volume adjustment applied before overlaying.

    Returns:
        Tuple of ``(layer, labels)`` where *layer* is a full-length
        :class:`~pydub.AudioSegment` with music stings overlaid at
        their cue positions, and *labels* is a list of
        ``(start_sec, end_sec, text)`` tuples for each sting.
    """
    layer = AudioSegment.silent(duration=total_ms)
    labels: list[tuple[float, float, str]] = []
    for plan in sorted(stem_plans, key=lambda p: p.seq):
        if plan.direction_type != "MUSIC":
            continue
        start_ms = timeline.get(plan.seq, 0)
        if start_ms >= total_ms:
            continue
        clip = AudioSegment.from_file(plan.filepath)
        if level_db != 0:
            clip = clip + level_db
        layer = layer.overlay(clip, position=start_ms)
        label_text = plan.text or plan.direction_type or "MUSIC"
        labels.append((start_ms / 1000.0, (start_ms + len(clip)) / 1000.0, label_text))
    return layer, labels


def build_dialogue_layer(
    stem_plans: list[StemPlan],
    timeline: dict[int, int],
    total_ms: int,
    cast_config: dict,
    apply_effects_fn=None,
) -> tuple:
    """Build an isolated dialogue layer for DAW export.

    Places only dialogue stems (``entry_type == "dialogue"``) at their
    foreground timeline positions in a full-length silent segment.
    Phone filter and pan effects are applied per speaker as configured.

    Args:
        stem_plans: Classified stem list from :func:`collect_stem_plans`.
        timeline: Cue-point timestamps from :func:`build_foreground`.
        total_ms: Total track length in milliseconds.
        cast_config: Per-speaker audio settings.
        apply_effects_fn: Optional phone filter callable.

    Returns:
        Tuple of ``(layer, labels)`` where *layer* is a full-length
        :class:`~pydub.AudioSegment` with dialogue stems at their
        timeline positions, and *labels* is a list of
        ``(start_sec, end_sec, speaker)`` tuples for Audacity label export.
    """
    layer = AudioSegment.silent(duration=total_ms)
    labels: list[tuple[float, float, str]] = []
    for plan in sorted(stem_plans, key=lambda p: p.seq):
        if plan.entry_type != "dialogue":
            continue
        start_ms = timeline.get(plan.seq, 0)
        segment = AudioSegment.from_file(plan.filepath)
        basename = os.path.splitext(os.path.basename(plan.filepath))[0]
        speaker = basename.rsplit("_", 1)[-1]
        if speaker in cast_config:
            if cast_config[speaker].get("filter") and apply_effects_fn:
                segment = apply_effects_fn(segment)
            segment = segment.pan(cast_config[speaker].get("pan", 0.0))
        end_ms = start_ms + len(segment)
        labels.append((start_ms / 1000.0, end_ms / 1000.0, speaker))
        layer = layer.overlay(segment, position=start_ms)
    return layer, labels


def build_sfx_layer(
    stem_plans: list[StemPlan],
    timeline: dict[int, int],
    total_ms: int,
) -> AudioSegment:
    """Build an isolated SFX layer for DAW export.

    Places only one-shot SFX and BEAT stems (``direction_type in
    ("SFX", "BEAT")``) at their foreground timeline positions.

    Args:
        stem_plans: Classified stem list from :func:`collect_stem_plans`.
        timeline: Cue-point timestamps from :func:`build_foreground`.
        total_ms: Total track length in milliseconds.

    Returns:
        Tuple of ``(layer, labels)`` where *layer* is a full-length
        :class:`~pydub.AudioSegment` with SFX stems at their timeline
        positions, and *labels* is a list of ``(start_sec, end_sec, text)``
        tuples for each one-shot effect.
    """
    layer = AudioSegment.silent(duration=total_ms)
    labels: list[tuple[float, float, str]] = []
    for plan in sorted(stem_plans, key=lambda p: p.seq):
        if plan.direction_type not in ("SFX", "BEAT"):
            continue
        start_ms = timeline.get(plan.seq, 0)
        segment = AudioSegment.from_file(plan.filepath)
        layer = layer.overlay(segment, position=start_ms)
        label_text = plan.text or plan.direction_type or "SFX"
        labels.append((start_ms / 1000.0, (start_ms + len(segment)) / 1000.0, label_text))
    return layer, labels
