# SECTION_MAP — Reference and Pipeline Impact

## Definition

Defined in `XILP001_script_parser.py` at module level:

```python
SECTION_MAP = {
    "COLD OPEN":         "cold-open",
    "ACT ONE":           "act1",
    "ACT TWO":           "act2",
    "MID-EPISODE BREAK": "mid-break",
    "CLOSING":           "closing",
}
```

Keys are the exact strings that appear in the production script markdown. Values are URL-safe slugs stamped onto every parsed entry and embedded in every stem filename.

---

## Effect in XILP001 — Three Roles

### 1. Gate-keeping (line 137)

```python
def is_section_header(line: str) -> bool:
    return line.strip() in SECTION_MAP
```

A line is only recognized as a section header if its stripped text exactly matches a key. Unrecognized headers (e.g., `"COLD OPEN 2"`, `"ACT THREE"`) fall through the classifier loop and are **silently skipped** — they generate no entry and do not update the section state.

### 2. State machine reset (lines 376–378)

```python
if is_section_header(line):
    current_section = SECTION_MAP[line.strip()]
    current_scene = None
```

When a section header is matched:
- `current_section` is set to the slug value
- `current_scene` is reset to `None`

Every subsequent entry inherits `current_section` until the next section header is encountered. Lines appearing before the first section header carry `"section": None`.

### 3. Slug stamped on every entry (lines 383, 403, 424, 446)

All four entry types receive the current section slug:

| Entry type | Section field set? |
|------------|-------------------|
| `section_header` | Yes (the header itself) |
| `scene_header` | Yes |
| `direction` | Yes |
| `dialogue` | Yes |

The stats collector at line 477 uses this to build `stats["sections"]` — a sorted list of unique section slugs seen in the script.

---

## Effect in XILP002 — Stem Filename Composition (lines 161–164)

```python
stem_name = f"{entry['seq']:03d}_{entry['section']}"
if entry.get("scene"):
    stem_name += f"-{entry['scene']}"
stem_name += f"_{entry['speaker']}"
```

The section slug becomes the **middle segment of every stem filename**:

```
003_cold-open_adam.mp3
028_act1-scene-1_rian.mp3
102_act2-scene-5_mr_patterson.mp3
```

This has a critical consequence for **duplicate stem prevention**: `generate_voices()` skips a stem if its file already exists on disk. If SECTION_MAP is changed after stems have been generated, the path changes and existing stems will not be found — XILP002 will re-generate them and consume additional TTS quota.

---

## Effect in XILP003 — None (Indirect Only)

XILP003 loads stems alphabetically via `sorted(glob(...))`. Since stems are prefixed with the zero-padded sequence number (`003_`, `028_`), the section slug in the middle does not affect sort order. XILP003 never reads section information directly — it extracts only the speaker from the filename suffix via `rsplit("_", 1)[-1]`.

---

## Adding a New Section

To add a new section (e.g., for an episode with an `"ACT THREE"`):

1. Add the entry to `SECTION_MAP` in `XILP001_script_parser.py`:
   ```python
   "ACT THREE": "act3",
   ```
2. Re-run XILP001 to regenerate the parsed JSON.
3. Re-run XILP002 — stems for the new section will have new filenames and will be generated fresh.

**Do not rename existing sections** after stems have been generated without also deleting the affected stems from `stems/`, or you will pay double TTS quota for those lines.

---

## Silent Failure Risk

An unrecognized section header causes **silent mislabeling**: all entries after it carry the slug of the *previous* section. This is invisible in normal output — `print_summary()` only shows which sections were found, not which lines were expected to be in which section.

The safest way to catch this is to check `stats["sections"]` after parsing and verify it contains all expected slugs:

```bash
python XILP001_script_parser.py scripts/the413_ep02.md --quiet
# then inspect parsed/parsed_the413_ep01.json → stats.sections
```
