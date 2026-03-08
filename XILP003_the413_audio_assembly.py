"""Assemble voice stems into the final master audio file.

Reads cast configuration for per-speaker audio settings (pan, filter),
applies effects to each stem, and concatenates into a master MP3.
No ElevenLabs API calls are made — this module is safe to run at any
time without consuming TTS quota.

Module Attributes:
    STEMS_DIR: Directory containing generated voice stem MP3 files.
    SILENCE_GAP_MS: Milliseconds of silence inserted between stems.
"""

import os
import json
import argparse
import glob

from pydub import AudioSegment

from models import CastConfiguration, VoiceConfig

STEMS_DIR = "stems"
SILENCE_GAP_MS = 600


def apply_phone_filter(segment: AudioSegment) -> AudioSegment:
    """Apply a phone-speaker audio filter to an audio segment.

    Cuts frequencies below 300 Hz and above 3000 Hz, then boosts
    volume by 5 dB to simulate a phone speaker.

    Args:
        segment: Input audio segment to filter.

    Returns:
        Filtered audio segment.
    """
    return segment.high_pass_filter(300).low_pass_filter(3000) + 5


def assemble_audio(config: dict[str, dict], stems_dir: str, final_output: str) -> None:
    """Assemble voice stems into a final master audio file.

    Loads all MP3 stems from the stems directory sorted by filename
    (sequence prefix ensures correct episode order), applies per-speaker
    audio effects (phone filter, stereo panning), concatenates with
    silence gaps, and exports the master file.

    Args:
        config: Mapping of speaker keys to voice settings dicts with
            keys ``id``, ``pan``, and ``filter``. Built from cast config
            via ``CastConfiguration`` and ``VoiceConfig``.
        stems_dir: Directory containing voice stem MP3 files.
        final_output: Path for the master MP3 output file.
    """
    stem_files = sorted(glob.glob(os.path.join(stems_dir, "*.mp3")))
    if not stem_files:
        print(f" [!] No stems found in {stems_dir}/. Run XILP002 first.")
        return

    print(f"--- Phase 2: Assembling {len(stem_files)} stems ---")
    full_vocals = AudioSegment.empty()

    for stem_file in stem_files:
        # Extract speaker from filename: "003_cold-open_adam.mp3" -> "adam"
        basename = os.path.splitext(os.path.basename(stem_file))[0]
        speaker = basename.rsplit("_", 1)[-1]

        print(f"   Loading: {stem_file} ({speaker})")
        segment = AudioSegment.from_file(stem_file)

        # Apply per-speaker effects
        if speaker in config:
            if config[speaker]["filter"]:
                segment = apply_phone_filter(segment)
            segment = segment.pan(config[speaker]["pan"])

        full_vocals += segment + AudioSegment.silent(duration=SILENCE_GAP_MS)

    full_vocals.export(final_output, format="mp3")
    print(f"--- Success! Created: {final_output} (Duration: {len(full_vocals)/1000:.1f}s) ---")
    os.system(f"mpg123 {os.path.abspath(final_output)}")


def main() -> None:
    """CLI entry point for audio assembly.

    Loads cast configuration to determine per-speaker audio settings,
    then assembles all stems in the stems directory into a master MP3.
    Does not require an ElevenLabs API key.
    """
    parser = argparse.ArgumentParser(
        description="THE 413 Audio Assembly — assemble voice stems into master MP3"
    )
    parser.add_argument(
        "--episode", required=True,
        help="Episode tag (e.g. S01E01) — derives cast config path"
    )
    parser.add_argument(
        "--output", default=None,
        help="Output master MP3 path (default: the413_<TAG>_master.mp3)"
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
    output = args.output or f"the413_{tag}_master.mp3"

    assemble_audio(config, stems_dir, output)


if __name__ == "__main__":
    main()
