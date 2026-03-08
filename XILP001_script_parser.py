"""Parse markdown production scripts into structured JSON.

Converts THE 413 podcast scripts from markdown format into
sequence-numbered entries suitable for voice generation.

Module Attributes:
    KNOWN_SPEAKERS: Ordered list of speaker names (longest-first for matching).
    SPEAKER_KEYS: Mapping from display names to normalized keys.
    SECTION_MAP: Mapping from section header text to URL-safe slugs.
    DIRECTION_TYPES: Recognized direction subtypes for stage directions.
"""

import re
import json
import argparse
import os

from models import ScriptEntry, ScriptStats, ParsedScript

# Known speakers — ordered longest-first so "MR. PATTERSON" matches before "MR."
KNOWN_SPEAKERS = [
    "MR. PATTERSON",
    "ADAM",
    "DEZ",
    "MAYA",
    "AVA",
    "RÍAN",
    "FRANK",
]

# Map display names to normalized keys for cast_config lookup
SPEAKER_KEYS = {
    "ADAM": "adam",
    "DEZ": "dez",
    "MAYA": "maya",
    "AVA": "ava",
    "RÍAN": "rian",
    "FRANK": "frank",
    "MR. PATTERSON": "mr_patterson",
}

# Section detection
SECTION_MAP = {
    "COLD OPEN": "cold-open",
    "ACT ONE": "act1",
    "ACT TWO": "act2",
    "MID-EPISODE BREAK": "mid-break",
    "CLOSING": "closing",
}

# Direction subtypes
DIRECTION_TYPES = ["SFX", "MUSIC", "AMBIENCE", "BEAT"]


def strip_markdown_escapes(text: str) -> str:
    """Remove markdown backslash escapes from the script.

    Args:
        text: Raw text possibly containing backslash-escaped markdown characters.

    Returns:
        Text with all backslash escapes removed.
    """
    text = text.replace("\\[", "[")
    text = text.replace("\\]", "]")
    text = text.replace("\\===", "===")
    text = text.replace("\\=", "=")
    # Remove all remaining backslash escapes (e.g., \. \~ \* \& \!)
    text = re.sub(r"\\(.)", r"\1", text)
    return text


def classify_direction(text: str) -> str | None:
    """Classify a stage direction into a sound category.

    Args:
        text: Bracket-interior text (e.g., ``"SFX: DOOR OPENS"``).

    Returns:
        One of ``"SFX"``, ``"MUSIC"``, ``"AMBIENCE"``, ``"BEAT"``, or ``None``
        if the direction doesn't match a known category.
    """
    for dt in DIRECTION_TYPES:
        if text.strip().startswith(dt):
            return dt
    if text.strip() == "BEAT" or text.strip() == "LONG BEAT":
        return "BEAT"
    return None


def try_match_speaker(line: str) -> tuple[str, str | None, str] | None:
    """Match a known speaker name at the start of a line.

    Args:
        line: A stripped line from the script.

    Returns:
        A tuple of ``(speaker_key, direction, spoken_text)`` if a known
        speaker is found, or ``None`` if no speaker matches.
    """
    for speaker in KNOWN_SPEAKERS:
        if not line.startswith(speaker):
            continue
        rest = line[len(speaker):]
        # Must be followed by space, '(' or end of string
        if rest and rest[0] not in (" ", "("):
            continue

        rest = rest.lstrip()
        direction = None
        # Check for parenthetical direction
        if rest.startswith("("):
            paren_end = rest.find(")")
            if paren_end != -1:
                direction = rest[1:paren_end].strip()
                rest = rest[paren_end + 1:].strip()

        spoken_text = rest
        return SPEAKER_KEYS[speaker], direction, spoken_text

    return None


def is_stage_direction(line: str) -> bool:
    """Check if a line is a stage direction like ``[SFX: ...]`` or ``[BEAT]``.

    Args:
        line: A stripped line from the script.

    Returns:
        ``True`` if the line starts with ``[`` and contains ``]``.
    """
    return line.startswith("[") and "]" in line


def is_section_header(line: str) -> bool:
    """Check if a line matches a known section header.

    Args:
        line: A stripped line from the script.

    Returns:
        ``True`` if the line matches a key in ``SECTION_MAP``.
    """
    return line.strip() in SECTION_MAP


def is_scene_header(line: str) -> bool:
    """Check if a line is a scene header (``SCENE N: ...``).

    Args:
        line: A stripped line from the script.

    Returns:
        ``True`` if the line matches the ``SCENE \\d+:`` pattern.
    """
    return bool(re.match(r"^SCENE \d+:", line))


def is_divider(line: str) -> bool:
    """Check if a line is a section divider (``===``).

    Args:
        line: A stripped line from the script.

    Returns:
        ``True`` if the stripped line equals ``"==="``.
    """
    return line.strip() == "==="


def is_metadata_section(line: str) -> bool:
    """Check if a line begins a post-script metadata section.

    Args:
        line: A stripped line from the script.

    Returns:
        ``True`` if the line matches a known metadata header
        (e.g., ``"PRODUCTION NOTES:"``).
    """
    return line.strip() in (
        "PRODUCTION NOTES:",
        "SOCIAL MEDIA PROMPT:",
        "KEY CHANGES FROM ORIGINAL:",
        "ACCESSIBILITY NOTES:",
        "VOICES NEEDED THIS EPISODE:",
        "KEY SOUND EFFECTS:",
        "MUSIC CUES:",
    )


def parse_scene_header(line: str) -> tuple[int | None, str | None]:
    """Extract scene number and name from a scene header line.

    Args:
        line: A line matching the ``SCENE N: ...`` pattern.

    Returns:
        A tuple of ``(scene_number, scene_name)``, or ``(None, None)``
        if the line doesn't match.
    """
    m = re.match(r"^SCENE (\d+):\s*(.+)", line)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None, None


def parse_script_header(line: str) -> tuple[str, int | None, int, str]:
    """Extract show, season, episode, and title from the script header line.

    Parses the first line of a production script, which follows the format::

        SHOW [Season N:] Episode N: ["Arc Title" Arc:] "Episode Title" ...

    Season is optional — scripts without a season declaration return ``None``.
    Title is the last double-quoted string if present, otherwise the bare text
    following ``Episode N:``.

    Args:
        line: The first non-empty line of the production script, after
            markdown escapes have been removed.

    Returns:
        A tuple of ``(show, season, episode, title)`` where ``season``
        is ``None`` if not declared in the header.
    """
    # Show: text before the first Season or Episode keyword
    show_match = re.match(r"^(.+?)\s+(?:Season\s+\d+|Episode\s+\d+)", line)
    show = show_match.group(1).strip() if show_match else "THE 413"

    # Season: optional
    season_match = re.search(r"Season\s+(\d+)", line)
    season = int(season_match.group(1)) if season_match else None

    # Episode
    ep_match = re.search(r"Episode\s+(\d+)", line)
    episode = int(ep_match.group(1)) if ep_match else 1

    # Title: last double-quoted string, or bare text after "Episode N: "
    quoted = re.findall(r'"([^"]+)"', line)
    if quoted:
        title = quoted[-1]
    else:
        ep_rest = re.search(r"Episode\s+\d+[:\s]+(.+)", line)
        title = ep_rest.group(1).strip() if ep_rest else ""

    return show, season, episode, title


def parse_script(filepath: str) -> dict:
    """Parse a markdown production script into structured entries.

    Reads a markdown file following THE 413 script format, extracts
    dialogue lines, stage directions, section headers, and scene headers
    into a sequence-numbered list of entries.

    Args:
        filepath: Path to the markdown production script file.

    Returns:
        Dictionary with keys ``show``, ``episode``, ``title``,
        ``source_file``, ``entries`` (list of entry dicts), and
        ``stats`` (aggregate statistics dict). Validates against
        the ``ParsedScript`` model.

    Raises:
        FileNotFoundError: If the script file does not exist.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read()

    raw = strip_markdown_escapes(raw)
    lines = raw.split("\n")

    entries = []
    seq = 0
    current_section = None
    current_scene = None
    in_metadata = False
    last_dialogue_idx = None  # Index into entries for continuation handling

    # Parse metadata from the header line, then skip it
    start = 0
    if lines and lines[0].startswith("THE 413"):
        show, season, episode, title = parse_script_header(lines[0])
        start = 1
    else:
        show, season, episode, title = "THE 413", None, 1, ""

    # Skip CAST section
    in_cast = False
    for i in range(start, len(lines)):
        line = lines[i].strip()
        if line == "CAST:":
            in_cast = True
            continue
        if in_cast:
            if line == "===" or (line and not line.startswith("*")):
                in_cast = False
                start = i
                break
            continue

    for i in range(start, len(lines)):
        line = lines[i].strip()

        if not line:
            continue

        if is_divider(line):
            continue

        if is_metadata_section(line):
            in_metadata = True
            continue

        if in_metadata:
            # Check if we've left metadata (shouldn't happen, metadata is at the end)
            continue

        # Also stop at END OF EPISODE
        if line.startswith("END OF EPISODE"):
            break

        # Section headers
        if is_section_header(line):
            current_section = SECTION_MAP[line.strip()]
            current_scene = None
            seq += 1
            entries.append({
                "seq": seq,
                "type": "section_header",
                "section": current_section,
                "scene": None,
                "speaker": None,
                "direction": None,
                "text": line.strip(),
                "direction_type": None,
            })
            last_dialogue_idx = None
            continue

        # Scene headers
        if is_scene_header(line):
            scene_num, scene_name = parse_scene_header(line)
            if scene_num is not None:
                current_scene = f"scene-{scene_num}"
            seq += 1
            entries.append({
                "seq": seq,
                "type": "scene_header",
                "section": current_section,
                "scene": current_scene,
                "speaker": None,
                "direction": None,
                "text": line.strip(),
                "direction_type": None,
            })
            last_dialogue_idx = None
            continue

        # Stage directions: [SFX: ...], [MUSIC: ...], [BEAT], etc.
        # Handle lines with multiple directions like [MUSIC: ...] [SFX: ...]
        if is_stage_direction(line):
            # Extract all bracketed sections
            brackets = re.findall(r"\[([^\]]+)\]", line)
            for bracket_text in brackets:
                seq += 1
                entries.append({
                    "seq": seq,
                    "type": "direction",
                    "section": current_section,
                    "scene": current_scene,
                    "speaker": None,
                    "direction": None,
                    "text": bracket_text.strip(),
                    "direction_type": classify_direction(bracket_text),
                })
            last_dialogue_idx = None
            continue

        # Dialogue lines: SPEAKER (direction) text
        match = try_match_speaker(line)
        if match:
            speaker_key, direction, spoken_text = match
            # Skip lines that are just stage directions disguised as speaker turns
            # (e.g., "[EVERYONE TURNS]" on its own line that starts with no speaker)
            if spoken_text:
                seq += 1
                entries.append({
                    "seq": seq,
                    "type": "dialogue",
                    "section": current_section,
                    "scene": current_scene,
                    "speaker": speaker_key,
                    "direction": direction,
                    "text": spoken_text,
                    "direction_type": None,
                })
                last_dialogue_idx = len(entries) - 1
            continue

        # Continuation text (no speaker prefix, no brackets)
        # Append to previous dialogue entry
        if last_dialogue_idx is not None and entries[last_dialogue_idx]["type"] == "dialogue":
            entries[last_dialogue_idx]["text"] += " " + line
            continue

        # Lines we can't classify — skip silently
        # (e.g., "[EVERYONE TURNS]" without brackets after stripping, stray markdown)

    # Compute stats
    dialogue_entries = [e for e in entries if e["type"] == "dialogue"]
    total_tts_chars = sum(len(e["text"]) for e in dialogue_entries)
    speakers_used = set(e["speaker"] for e in dialogue_entries)

    stats = ScriptStats(
        total_entries=len(entries),
        dialogue_lines=len(dialogue_entries),
        direction_lines=sum(1 for e in entries if e["type"] == "direction"),
        characters_for_tts=total_tts_chars,
        speakers=sorted(speakers_used),
        sections=sorted(set(e["section"] for e in entries if e["section"])),
    )

    parsed = ParsedScript(
        show=show,
        season=season,
        episode=episode,
        title=title,
        source_file=os.path.basename(filepath),
        entries=entries,
        stats=stats,
    )
    return parsed.model_dump()


def print_summary(parsed: dict) -> None:
    """Print a human-readable summary of the parsed script.

    Displays show metadata, entry counts, TTS character budget,
    and a per-speaker breakdown of lines and characters.

    Args:
        parsed: Output dictionary from ``parse_script()``.
    """
    stats = parsed["stats"]
    season_label = (
        f"S{parsed['season']:02d}E{parsed['episode']:02d}"
        if parsed.get("season") is not None
        else f"Episode {parsed['episode']}"
    )
    print(f"\n{'='*60}")
    print(f"PARSED: {parsed['show']} {season_label} — {parsed['title']}")
    print(f"Source: {parsed['source_file']}")
    print(f"{'='*60}")
    print(f"  Total entries:      {stats['total_entries']}")
    print(f"  Dialogue lines:     {stats['dialogue_lines']}")
    print(f"  Stage directions:   {stats['direction_lines']}")
    print(f"  TTS characters:     {stats['characters_for_tts']:,}")
    print(f"  Speakers:           {', '.join(stats['speakers'])}")
    print(f"  Sections:           {', '.join(stats['sections'])}")
    print(f"{'='*60}\n")

    # Per-speaker breakdown
    dialogue_entries = [e for e in parsed["entries"] if e["type"] == "dialogue"]
    speaker_stats = {}
    for e in dialogue_entries:
        sp = e["speaker"]
        if sp not in speaker_stats:
            speaker_stats[sp] = {"lines": 0, "chars": 0}
        speaker_stats[sp]["lines"] += 1
        speaker_stats[sp]["chars"] += len(e["text"])

    print(f"{'Speaker':<15} {'Lines':>6} {'Chars':>8}")
    print(f"{'-'*15} {'-'*6} {'-'*8}")
    for sp in sorted(speaker_stats.keys()):
        s = speaker_stats[sp]
        print(f"{sp:<15} {s['lines']:>6} {s['chars']:>8,}")
    print()


def print_dialogue_preview(parsed: dict, limit: int | None = None) -> None:
    """Print dialogue lines for review.

    Args:
        parsed: Output dictionary from ``parse_script()``.
        limit: Maximum number of dialogue lines to display.
            ``None`` shows all lines.
    """
    dialogue_entries = [e for e in parsed["entries"] if e["type"] == "dialogue"]
    if limit:
        dialogue_entries = dialogue_entries[:limit]

    print(f"\n--- Dialogue Preview ({len(dialogue_entries)} lines) ---\n")
    for e in dialogue_entries:
        scene_label = e["scene"] or e["section"] or "?"
        direction_label = f" ({e['direction']})" if e["direction"] else ""
        text_preview = e["text"][:80] + "..." if len(e["text"]) > 80 else e["text"]
        print(f"  {e['seq']:03d} | {scene_label:<16} | {e['speaker']:<14}{direction_label}")
        print(f"       {text_preview}")
        print()


def main() -> None:
    """CLI entry point for script parsing."""
    parser = argparse.ArgumentParser(description="Parse THE 413 production script markdown into structured JSON")
    parser.add_argument("script", help="Path to the production script markdown file")
    parser.add_argument("--output", "-o", default="parsed/parsed_the413_ep01.json",
                        help="Output JSON path (default: parsed/parsed_the413_ep01.json)")
    parser.add_argument("--preview", type=int, default=None,
                        help="Show first N dialogue lines (default: show all)")
    parser.add_argument("--quiet", action="store_true",
                        help="Only output JSON, skip summary/preview")
    args = parser.parse_args()

    parsed = parse_script(args.script)

    # Write JSON output
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2, ensure_ascii=False)

    if not args.quiet:
        print_summary(parsed)
        print_dialogue_preview(parsed, limit=args.preview)
        print(f"JSON written to: {args.output}")


if __name__ == "__main__":
    main()
