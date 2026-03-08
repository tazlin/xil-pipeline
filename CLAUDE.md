# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated podcast/audio production pipeline using ElevenLabs TTS API. The project evolved from a simple multi-voice ad proof-of-concept into a full podcast episode producer for "THE 413" fiction podcast.

## Environment

- Python 3.13, virtualenv at `venv/`
- WSL2 (Linux on Windows)
- Activate: `source venv/bin/activate`
- Key packages: `elevenlabs`, `pydub`, `google-genai`, `gTTS`, `pyttsx3`, `ollama`
- ElevenLabs API key via `ELEVENLABS_API_KEY` env var
- Audio playback via `mpg123` in WSL

## Architecture: Three-Stage Pipeline

### Stage 1: Script Parsing
`XILP001_script_parser.py` — Parses markdown production scripts into structured JSON.

```bash
python XILP001_script_parser.py "scripts/<script>.md" --episode S01E01 --preview 10
```

- Input: Markdown scripts in `scripts/` with dialogue format `SPEAKER (direction) Spoken text`
- Output: `parsed/parsed_the413_S01E01.json` — entries with seq, type, section, scene, speaker, direction, text, direction_type
- Output path derived from script header metadata (season/episode); override with `--output`
- `--episode S01E01` (optional) validates that the script header matches the intended episode tag
- When `--episode` is provided and `cast_the413_S01E01.json` / `sfx_the413_S01E01.json` don't exist, auto-generates skeleton configs with `voice_id=TBD` and default SFX prompts
- Supports `--quiet` (JSON only, skip summary) and `--debug` (write diagnostic CSV alongside JSON)
- Known speakers defined in `KNOWN_SPEAKERS` list (must be longest-first for multi-word names like "MR. PATTERSON")

### Stage 2: Voice Generation
`XILP002_the413_producer.py` — Calls ElevenLabs API to generate voice stems.

```bash
python XILP002_the413_producer.py --episode S01E01 --dry-run
```

- `--episode` (required) derives `cast_the413_S01E01.json` and (with `--sfx`) `sfx_the413_S01E01.json`
- Reads: parsed JSON + cast config (voice_id/pan/filter per character)
- Outputs: `stems/<TAG>/{seq:03d}_{section}[-{scene}]_{speaker}.mp3` (e.g. `stems/S01E01/003_cold-open_adam.mp3`)
- Supports `--start-from N` for resuming interrupted runs
- Supports `--dry-run` to preview lines and TTS character cost without API calls
- Supports `--terse` to truncate each line to 3 words (minimizes TTS character cost)
- Supports `--sfx` flag to generate sound effect stems alongside dialogue
- Skips stems that already exist on disk

### Stage 3: Audio Assembly
`XILP003_the413_audio_assembly.py` — Concatenates stems with silence gaps into final audio.

```bash
python XILP003_the413_audio_assembly.py --episode S01E01
```

- Loads stems alphabetically (sequence prefix ensures order)
- Applies per-speaker effects (pan, phone filter) from cast config
- Extracts speaker from stem filename via `rsplit("_", 1)[-1]`
- Supports `--output` to set the master MP3 path (default: `the413_S01E01_master.mp3`, derived from cast config)
- No ElevenLabs API key required — safe to re-run freely

## ElevenLabs API Cost Controls

Every script that calls the API includes three guard functions (duplicated per file, not shared):
- `check_elevenlabs_quota()` — displays current character usage vs limit
- `has_enough_characters(text)` — per-line quota check before each API call
- `get_best_model_for_budget()` — switches from `eleven_v3` to `eleven_flash_v2_5` when balance is low

Always use `--dry-run` before running voice generation on a new script to verify TTS character budget.

## File Naming Convention

Scripts use prefix `XIL` (ElevenLabs, avoiding numeric prefixes). The suffix pattern is:
- `11L_*` — legacy standalone utilities (e.g., `XILU001_discover_voices_T2S.py`)
- `XILU002_*` — standalone SFX stem generation utility
- `XILP001_*` — script parser
- `XILP002_*` — voice generation (ElevenLabs TTS)
- `XILP003_*` — audio assembly (stems → master MP3)

## Cast Configuration

`cast_the413_S01E01.json` contains show-level metadata (`show`, `season`, `episode`, `title`) and a `cast` dict mapping character keys to settings:
```json
{
  "show": "THE 413", "season": 1, "episode": 1, "title": "The Holiday Shift",
  "cast": {
    "adam": { "full_name": "Adam Santos", "voice_id": "...", "pan": 0.0, "filter": false, "role": "Host/Narrator" }
  }
}
```
Voice IDs are discovered via `XILU001_discover_voices_T2S.py` (filters to premade category).

## SFX Configuration

`sfx_the413_S01E01.json` maps parsed direction entry text to ElevenLabs Sound Effects API parameters:
```json
{
  "show": "THE 413", "season": 1, "episode": 1,
  "defaults": { "prompt_influence": 0.3 },
  "effects": {
    "SFX: PHONE BUZZING": { "prompt": "Phone vibrating buzz", "duration_seconds": 2.0 },
    "BEAT": { "type": "silence", "duration_seconds": 1.0 }
  }
}
```
- Keys match the `text` field of parsed direction entries exactly
- `type: "sfx"` (default) entries call `client.text_to_sound_effects.convert()` with the `prompt`
- `type: "silence"` entries (BEAT/LONG BEAT) generate local silent audio — no API call
- `loop: true` entries are intended for ambience (future overlay support)
- SFX stems use `_sfx` suffix: `002_cold-open_sfx.mp3`

### Shared SFX Library
Each unique sound effect is generated **once** into the `SFX/` directory as a shared asset (e.g. `SFX/beat.mp3`, `SFX/sfx_phone-buzzing.mp3`). Episode stems in `stems/<TAG>/` are copies of these shared assets with sequence-numbered filenames. This avoids regenerating the same effect for repeated uses (e.g. BEAT appears 26 times in S01E01).

- Shared asset naming: `slugify_effect_key()` in `sfx_common.py` converts direction text to filesystem-safe slugs
- `--dry-run` shows three statuses: `EXISTS` (episode stem on disk), `CACHED` (shared asset exists, will be copied), `NEW` (needs API generation)
- Common SFX functions live in `sfx_common.py` — both XILU002 and XILP002 delegate to it

### Standalone SFX Utility
`XILU002_generate_SFX.py` — Generates SFX stems independently of XILP002 voice generation.

```bash
python XILU002_generate_SFX.py --episode S01E01 --dry-run
python XILU002_generate_SFX.py --episode S01E01 --max-duration 5.0
python XILU002_generate_SFX.py --episode S01E01
```

- `--episode` (required) derives `cast_the413_S01E01.json` and `sfx_the413_S01E01.json`
- Reads: parsed script JSON + SFX config + cast config (for episode tag)
- Outputs: shared assets to `SFX/`, episode stems to `stems/<TAG>/`
- `--dry-run` shows EXISTS/CACHED/NEW status per stem with credit estimates
- `--max-duration N` filters to effects ≤ N seconds (controls API credit spend)
- Skips stems that already exist on disk

## Developer/Maintainer Rules

Automated testing via Python and Bash serves as the fundamental mechanism for the Verification Loop. The project mandates that Claude must mention how it will verify its work before it begins any task.

Use tests for everything it implements:
- Determine which tests are appropriate; the model will then generate a test for every single feature it builds
- Test-Driven Development (TDD): A key best practice is implementing a verification-led technique where tests for a new feature are written first, followed by the actual code implementation

### Script Entry Point Style

Always use the `if __name__ == "__main__":` idiom. All application logic that would otherwise follow it must live inside a `main()` function — the dunder-main block must contain only the call to `main()`:

```python
def main():
    parser = argparse.ArgumentParser(...)
    args = parser.parse_args()
    # all application logic here

if __name__ == "__main__":
    main()
```

This keeps the `__main__` block to a single line, makes the entry point testable by calling `main()` directly, and prevents module-level side effects when the file is imported.

## Running Tests

```bash
python -m pytest tests/ -v
```

## Key Directories

- `tests/` — Automated test suite (pytest)
- `scripts/` — Source markdown production scripts (authored manually)
- `parsed/` — Parser JSON output (generated, cacheable)
- `stems/<TAG>/` — Individual voice/SFX audio files per episode (generated, expensive to recreate)
- `SFX/` — Shared SFX asset library (generated once, reused across episodes)
- `venv/` — Python virtualenv (do not commit)
