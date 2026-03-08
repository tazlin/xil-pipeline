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
python XILP001_script_parser.py "scripts/<script>.md" --preview 10
```

- Input: Markdown scripts in `scripts/` with dialogue format `SPEAKER (direction) Spoken text`
- Output: `parsed/parsed_the413_ep01.json` — entries with seq, type, section, scene, speaker, direction, text
- Known speakers defined in `KNOWN_SPEAKERS` list (must be longest-first for multi-word names like "MR. PATTERSON")

### Stage 2: Voice Generation (Phase 1)
`XILP002_the413_producer.py --phase 1` — Calls ElevenLabs API to generate voice stems.

- Reads: parsed JSON + `cast_the413.json` (voice_id/pan/filter per character)
- Outputs: `stems/{seq:03d}_{section}[-{scene}]_{speaker}.mp3`
- Supports `--start-from N` for resuming interrupted runs
- Supports `--dry-run` to preview lines and TTS character cost without API calls
- Skips stems that already exist on disk

### Stage 3: Assembly (Phase 2)
`XILP002_the413_producer.py --phase 2` — Concatenates stems with silence gaps into final audio.

- Loads stems alphabetically (sequence prefix ensures order)
- Applies per-speaker effects (pan, phone filter) from cast config
- Extracts speaker from stem filename via `rsplit("_", 1)[-1]`

## ElevenLabs API Cost Controls

Every script that calls the API includes three guard functions (duplicated per file, not shared):
- `check_elevenlabs_quota()` — displays current character usage vs limit
- `has_enough_characters(text)` — per-line quota check before each API call
- `get_best_model_for_budget()` — switches from `eleven_v3` to `eleven_flash_v2_5` when balance is low

Always use `--dry-run` before running Phase 1 on a new script to verify TTS character budget.

## File Naming Convention

Scripts use prefix `XIL` (ElevenLabs, avoiding numeric prefixes). The suffix pattern is:
- `11L_*` — legacy standalone utilities (e.g., `XILU001_discover_voices_T2S.py`)
- `XILP001_*` — proof-of-concept (3-voice ad, reference implementation)
- `XILP002_*` — production pipeline (full podcast episodes)

## Cast Configuration

`cast_the413.json` maps character keys to ElevenLabs settings:
```json
{ "adam": { "voice_id": "...", "pan": 0.0, "filter": false } }
```
Voice IDs are discovered via `XILU001_discover_voices_T2S.py` (filters to premade category).

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
- `stems/` — Individual voice audio files (generated, expensive to recreate)
- `venv/` — Python virtualenv (do not commit)
