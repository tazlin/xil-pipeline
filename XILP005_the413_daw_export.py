"""Export THE 413 episode audio as separate DAW layer WAV files.

Reads the parsed script JSON and episode stems to build four isolated,
full-length WAV files — one per audio layer — that can be imported into
Audacity (or any DAW) as pre-aligned tracks:

    daw/{TAG}/{TAG}_layer_dialogue.wav  — spoken dialogue (with effects)
    daw/{TAG}/{TAG}_layer_ambience.wav  — looped environmental background
    daw/{TAG}/{TAG}_layer_music.wav     — music stings and themes
    daw/{TAG}/{TAG}_layer_sfx.wav       — one-shot sound effects/beats

All four WAVs are exactly the same length (full episode duration) so
they align perfectly when imported at t=0.  The producer controls final
level balance and any additional processing inside the DAW.

An Audacity import helper script is also generated at:
    daw/{TAG}/{TAG}_open_in_audacity.py

Run it to print the file paths and manual import instructions; if
Audacity's mod-script-pipe is enabled it will attempt automation.

Usage:
    python XILP005_the413_daw_export.py --episode S01E02 --dry-run
    python XILP005_the413_daw_export.py --episode S01E02
    python XILP005_the413_daw_export.py --episode S01E02 --output-dir exports/

No ElevenLabs API calls are made — this stage is safe to run freely.
"""

import json
import os
import argparse
import textwrap

from pydub import AudioSegment

from models import CastConfiguration, VoiceConfig
from mix_common import (
    apply_phone_filter,
    collect_stem_plans,
    load_entries_index,
    build_foreground,
    build_ambience_layer,
    build_music_layer,
    build_dialogue_layer,
    build_sfx_layer,
)

STEMS_DIR = "stems"
DAW_DIR = "daw"
SILENCE_GAP_MS = 600

# Layer definitions: (key, filename_suffix, description)
LAYERS: list[tuple[str, str, str]] = [
    ("dialogue", "layer_dialogue", "Spoken dialogue (phone filter + pan applied)"),
    ("ambience", "layer_ambience", "Looped environmental background (no ducking)"),
    ("music",    "layer_music",    "Music stings and themes (no ducking)"),
    ("sfx",      "layer_sfx",      "One-shot sound effects and beat silences"),
]


def _write_labels(output_dir: str, fname: str, labels: list[tuple[float, float, str]]) -> None:
    """Write an Audacity label file (tab-separated start, end, text)."""
    with open(os.path.join(output_dir, fname), "w", encoding="utf-8") as lf:
        for start_s, end_s, text in labels:
            lf.write(f"{start_s:.3f}\t{end_s:.3f}\t{text}\n")


def _make_audacity_script(tag: str, layer_files: list[tuple[str, str]]) -> str:
    """Generate the content of the Audacity import helper script.

    Args:
        tag: Episode tag (e.g. ``"S01E01"``).
        layer_files: List of ``(track_name, relative_filename)`` pairs.

    Returns:
        Python source code for the helper script as a string.
    """
    layers_repr = repr(layer_files)
    return textwrap.dedent(f"""\
        #!/usr/bin/env python3
        \"\"\"Open THE 413 {tag} DAW layers in Audacity.

        Run this script while Audacity is open.  If mod-script-pipe is
        enabled the four layer WAVs are imported automatically.  Otherwise
        the file paths and manual import instructions are printed below.

        Enable mod-script-pipe in Audacity:
          Edit > Preferences > Modules > mod-script-pipe → Enabled
          (restart Audacity after enabling)
        \"\"\"
        import os
        import sys

        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        LAYERS = {layers_repr}


        def try_pipe_import(layers):
            \"\"\"Attempt Audacity import via mod-script-pipe named pipe.\"\"\"
            import platform
            if platform.system() == "Windows":
                tofile = r"\\\\.\\pipe\\ToSrvPipe"
                fromfile = r"\\\\.\\pipe\\FromSrvPipe"
            else:
                tofile = "/tmp/audacity_script_pipe.to.app"
                fromfile = "/tmp/audacity_script_pipe.from.app"

            if not os.path.exists(tofile):
                return False

            try:
                import time
                with open(tofile, "w") as pipe_to, open(fromfile, "r") as pipe_from:
                    def send(cmd):
                        pipe_to.write(cmd + "\\n")
                        pipe_to.flush()
                        time.sleep(0.1)
                        return pipe_from.readline().strip()

                    send("New:")
                    for name, filename in layers:
                        full_path = os.path.join(BASE_DIR, filename)
                        send(f"Import2: Filename={{full_path}}")
                        send(f"SetTrackStatus: Name={{name}}")
                    print(f"[✓] Imported {{len(layers)}} tracks into Audacity.")
                return True
            except Exception as exc:
                print(f"[!] Pipe import failed: {{exc}}")
                return False


        def print_instructions(layers):
            \"\"\"Print manual import instructions.\"\"\"
            print()
            print(f"THE 413 {tag} — Audacity Layer Import")
            print("=" * 45)
            print()
            print("Import these 4 WAV files into Audacity:")
            print("  File > Import > Audio...  (Ctrl+Shift+I on Windows/Linux)")
            print()
            for i, (name, filename) in enumerate(layers, 1):
                full = os.path.join(BASE_DIR, filename)
                print(f"  {{i}}. {{name:<12}}  {{full}}")
            print()
            print("After importing, all tracks are pre-aligned at t=0.")
            print("No repositioning needed — just mix levels and export.")
            print()
            print("Suggested track order (top to bottom in Audacity):")
            print("  1. Dialogue  — speaking parts (phone filter already applied)")
            print("  2. Music     — stings and themes")
            print("  3. SFX       — one-shot effects")
            print("  4. Ambience  — background loops")
            print()


        if __name__ == "__main__":
            if not try_pipe_import(LAYERS):
                print_instructions(LAYERS)
        """)


def dry_run_daw(tag: str, stem_plans, entries_index: dict, output_dir: str) -> None:
    """Print a DAW export summary without writing any files.

    Args:
        tag: Episode tag.
        stem_plans: Classified stem list.
        entries_index: Parsed entry index.
        output_dir: Target directory (shown in summary).
    """
    fg_plans = [p for p in stem_plans if not p.is_background]
    bg_plans = [p for p in stem_plans if p.is_background]
    ambience = [p for p in bg_plans if p.direction_type == "AMBIENCE"]
    music = [p for p in bg_plans if p.direction_type == "MUSIC"]
    sfx = [p for p in stem_plans if p.direction_type in ("SFX", "BEAT")]
    dialogue = [p for p in stem_plans if p.entry_type == "dialogue"]

    print(f"\n--- DAW Export Dry Run: {tag} ---")
    print(f"   Stems directory : stems/{tag}/")
    print(f"   Output directory: {output_dir}/")
    print()
    print(f"   Layer             Stems")
    print(f"   ─────────────────────────────")
    print(f"   dialogue          {len(dialogue):3d} stems")
    print(f"   ambience          {len(ambience):3d} stems  (looped to scene boundaries)")
    print(f"   music             {len(music):3d} stems  (one-shot at cue points)")
    print(f"   sfx               {len(sfx):3d} stems")
    print()
    print(f"   Output files (all same duration as foreground track):")
    for _, suffix, desc in LAYERS:
        print(f"     {output_dir}/{tag}_{suffix}.wav  — {desc}")
    print(f"     {output_dir}/{tag}_open_in_audacity.py")
    print()


def export_daw_layers(
    config: dict[str, dict],
    stems_dir: str,
    parsed_path: str,
    output_dir: str,
    tag: str,
) -> None:
    """Build and export all four DAW layer WAV files.

    Args:
        config: Per-speaker voice settings from cast config.
        stems_dir: Directory containing episode stem MP3 files.
        parsed_path: Path to the parsed script JSON (XILP001 output).
        output_dir: Directory to write the layer WAV files.
        tag: Episode tag used to name output files.
    """
    entries_index = load_entries_index(parsed_path)
    stem_plans = collect_stem_plans(stems_dir, entries_index)

    if not stem_plans:
        print(f" [!] No stems found in {stems_dir}/. Run XILP002 first.")
        return

    print(f"--- Building foreground timeline from {len(stem_plans)} stems ---")
    foreground, timeline = build_foreground(
        stem_plans, config, apply_phone_filter, gap_ms=SILENCE_GAP_MS
    )

    if len(foreground) == 0:
        print(" [!] No foreground stems — cannot determine episode duration.")
        return

    total_ms = len(foreground)
    print(f"    Episode duration: {total_ms / 1000:.1f}s")

    os.makedirs(output_dir, exist_ok=True)

    layer_files: list[tuple[str, str]] = []

    # --- Dialogue layer ---
    print("--- Building dialogue layer ---")
    dlg, labels = build_dialogue_layer(
        stem_plans, timeline, total_ms, config, apply_phone_filter
    )
    fname = f"{tag}_layer_dialogue.wav"
    dlg.export(os.path.join(output_dir, fname), format="wav")
    layer_files.append(("Dialogue", fname))
    print(f"    Written: {output_dir}/{fname}")

    # --- Dialogue label track ---
    _write_labels(output_dir, f"{tag}_labels_dialogue.txt", labels)
    layer_files.append(("Labels (Dialogue)", f"{tag}_labels_dialogue.txt"))
    print(f"    Written: {output_dir}/{tag}_labels_dialogue.txt")

    # --- Ambience layer ---
    print("--- Building ambience layer ---")
    amb, amb_labels = build_ambience_layer(stem_plans, timeline, total_ms, level_db=0)
    fname = f"{tag}_layer_ambience.wav"
    amb.export(os.path.join(output_dir, fname), format="wav")
    layer_files.append(("Ambience", fname))
    print(f"    Written: {output_dir}/{fname}")
    _write_labels(output_dir, f"{tag}_labels_ambience.txt", amb_labels)
    layer_files.append(("Labels (Ambience)", f"{tag}_labels_ambience.txt"))
    print(f"    Written: {output_dir}/{tag}_labels_ambience.txt")

    # --- Music layer ---
    print("--- Building music layer ---")
    mus, mus_labels = build_music_layer(stem_plans, timeline, total_ms, level_db=0)
    fname = f"{tag}_layer_music.wav"
    mus.export(os.path.join(output_dir, fname), format="wav")
    layer_files.append(("Music", fname))
    print(f"    Written: {output_dir}/{fname}")
    _write_labels(output_dir, f"{tag}_labels_music.txt", mus_labels)
    layer_files.append(("Labels (Music)", f"{tag}_labels_music.txt"))
    print(f"    Written: {output_dir}/{tag}_labels_music.txt")

    # --- SFX layer ---
    print("--- Building SFX layer ---")
    sfx, sfx_labels = build_sfx_layer(stem_plans, timeline, total_ms)
    fname = f"{tag}_layer_sfx.wav"
    sfx.export(os.path.join(output_dir, fname), format="wav")
    layer_files.append(("SFX", fname))
    print(f"    Written: {output_dir}/{fname}")
    _write_labels(output_dir, f"{tag}_labels_sfx.txt", sfx_labels)
    layer_files.append(("Labels (SFX)", f"{tag}_labels_sfx.txt"))
    print(f"    Written: {output_dir}/{tag}_labels_sfx.txt")

    # --- Audacity helper script ---
    script_fname = f"{tag}_open_in_audacity.py"
    script_path = os.path.join(output_dir, script_fname)
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(_make_audacity_script(tag, layer_files))
    os.chmod(script_path, 0o755)
    print(f"    Written: {output_dir}/{script_fname}")

    print()
    print(f"--- Done! {len(layer_files)} layer WAVs in {output_dir}/ ---")
    print(f"    Import into Audacity: python {output_dir}/{script_fname}")


def main() -> None:
    """CLI entry point for DAW layer export.

    Loads cast config, derives stem and parsed JSON paths from the
    episode tag, builds four per-layer WAV files and an Audacity helper
    script.  No ElevenLabs API key required.
    """
    parser = argparse.ArgumentParser(
        description="THE 413 DAW Export — export episode as layered WAV files for Audacity"
    )
    parser.add_argument(
        "--episode", required=True,
        help="Episode tag (e.g. S01E02) — derives cast config, stems, and parsed JSON paths"
    )
    parser.add_argument(
        "--parsed", default=None,
        help="Path to parsed script JSON (default: parsed/parsed_the413_<TAG>.json)"
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Output directory for layer WAVs (default: daw/<TAG>/)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show export summary without writing files"
    )
    args = parser.parse_args()

    cast_path = f"cast_the413_{args.episode}.json"
    with open(cast_path, "r", encoding="utf-8") as f:
        cast_data = json.load(f)

    cast_cfg = CastConfiguration(**cast_data)
    tag = cast_cfg.tag
    config = {
        key: VoiceConfig(id=member.voice_id, pan=member.pan, filter=member.filter).model_dump()
        for key, member in cast_cfg.cast.items()
    }

    stems_dir = os.path.join(STEMS_DIR, tag)
    parsed_path = args.parsed or f"parsed/parsed_the413_{tag}.json"
    output_dir = args.output_dir or os.path.join(DAW_DIR, tag)

    if not os.path.exists(parsed_path):
        print(f" [!] Parsed JSON not found: {parsed_path!r}. Run XILP001 first.")
        return

    entries_index = load_entries_index(parsed_path)
    stem_plans = collect_stem_plans(stems_dir, entries_index)

    if args.dry_run:
        dry_run_daw(tag, stem_plans, entries_index, output_dir)
        return

    export_daw_layers(config, stems_dir, parsed_path, output_dir, tag)


if __name__ == "__main__":
    main()
