"""Tests for XILP001_script_parser.py — markdown production script parser."""

import os
import json
import tempfile
import importlib
import unittest.mock

import pytest

# Import the parser module (filename starts with digits, so use importlib)
import importlib.util
spec = importlib.util.spec_from_file_location(
    "script_parser",
    os.path.join(os.path.dirname(__file__), "..", "XILP001_script_parser.py")
)
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


# ─── Unit Tests: strip_markdown_escapes ───

class TestStripMarkdownEscapes:
    def test_brackets(self):
        assert parser.strip_markdown_escapes("\\[SFX: DOOR\\]") == "[SFX: DOOR]"

    def test_dividers(self):
        assert parser.strip_markdown_escapes("\\===") == "==="

    def test_periods_and_tildes(self):
        assert parser.strip_markdown_escapes("1972\\.") == "1972."
        assert parser.strip_markdown_escapes("\\~30 minutes") == "~30 minutes"

    def test_no_escapes(self):
        assert parser.strip_markdown_escapes("plain text") == "plain text"

    def test_multiple_escapes_in_one_line(self):
        result = parser.strip_markdown_escapes("\\[BEAT\\] and \\[SFX\\]")
        assert result == "[BEAT] and [SFX]"


# ─── Unit Tests: classify_direction ───

class TestClassifyDirection:
    def test_sfx(self):
        assert parser.classify_direction("SFX: DOOR OPENS") == "SFX"

    def test_music(self):
        assert parser.classify_direction("MUSIC: THEME BEGINS, LOW") == "MUSIC"

    def test_ambience(self):
        assert parser.classify_direction("AMBIENCE: DINER – COFFEE") == "AMBIENCE"

    def test_beat(self):
        assert parser.classify_direction("BEAT") == "BEAT"

    def test_long_beat(self):
        assert parser.classify_direction("LONG BEAT") == "BEAT"

    def test_unknown(self):
        assert parser.classify_direction("EVERYONE TURNS") is None

    def test_whitespace(self):
        assert parser.classify_direction("  SFX: PHONE BUZZING  ") == "SFX"


# ─── Unit Tests: try_match_speaker ───

class TestTryMatchSpeaker:
    def test_simple_dialogue(self):
        result = parser.try_match_speaker("ADAM What do you mean?")
        assert result == ("adam", None, "What do you mean?")

    def test_dialogue_with_direction(self):
        result = parser.try_match_speaker("ADAM (narration) Morrison's Diner has been open...")
        assert result == ("adam", "narration", "Morrison's Diner has been open...")

    def test_multi_word_speaker(self):
        result = parser.try_match_speaker("MR. PATTERSON Long enough.")
        assert result == ("mr_patterson", None, "Long enough.")

    def test_multi_word_with_direction(self):
        result = parser.try_match_speaker("MR. PATTERSON (older man's voice) That's because she had.")
        assert result == ("mr_patterson", "older man's voice", "That's because she had.")

    def test_accented_speaker(self):
        result = parser.try_match_speaker("RÍAN (entering) Okay, I'm here.")
        assert result == ("rian", "entering", "Okay, I'm here.")

    def test_no_match(self):
        assert parser.try_match_speaker("Some random text") is None

    def test_partial_name_no_match(self):
        # "ADAMS" should not match "ADAM"
        assert parser.try_match_speaker("ADAMS went home") is None

    def test_speaker_with_parenthetical_only(self):
        result = parser.try_match_speaker("DEZ (uneasy) I know.")
        assert result == ("dez", "uneasy", "I know.")


# ─── Unit Tests: line classifiers ───

class TestLineClassifiers:
    def test_is_stage_direction(self):
        assert parser.is_stage_direction("[SFX: DOOR OPENS]") is True
        assert parser.is_stage_direction("[BEAT]") is True
        assert parser.is_stage_direction("ADAM Hello") is False

    def test_is_section_header(self):
        assert parser.is_section_header("COLD OPEN") is True
        assert parser.is_section_header("ACT ONE") is True
        assert parser.is_section_header("SCENE 1: DINER") is False

    def test_is_scene_header(self):
        assert parser.is_scene_header("SCENE 1: THE DINER") is True
        assert parser.is_scene_header("SCENE 12: FINALE") is True
        assert parser.is_scene_header("COLD OPEN") is False

    def test_is_divider(self):
        assert parser.is_divider("===") is True
        assert parser.is_divider("  ===  ") is True
        assert parser.is_divider("== =") is False

    def test_is_metadata_section(self):
        assert parser.is_metadata_section("PRODUCTION NOTES:") is True
        assert parser.is_metadata_section("MUSIC CUES:") is True
        assert parser.is_metadata_section("ACT ONE") is False


class TestParseSceneHeader:
    def test_simple(self):
        num, name = parser.parse_scene_header("SCENE 1: THE DINER – INTERIOR")
        assert num == 1
        assert name == "THE DINER – INTERIOR"

    def test_no_match(self):
        num, name = parser.parse_scene_header("COLD OPEN")
        assert num is None
        assert name is None


# ─── Unit Tests: parse_script_header ───

class TestParseScriptHeader:
    FULL = 'THE 413 Season 1: Episode 1: "The Empty Booth" Arc: "The Holiday Shift" (1 of 3) Runtime: ~30 minutes'
    MINIMAL = "THE 413 Season 1: Episode 1: Test"
    NO_SEASON = "THE 413 Episode 2: Another Episode"

    def test_full_header_extracts_show(self):
        show, _, _, _ = parser.parse_script_header(self.FULL)
        assert show == "THE 413"

    def test_full_header_extracts_season(self):
        _, season, _, _ = parser.parse_script_header(self.FULL)
        assert season == 1

    def test_full_header_extracts_episode(self):
        _, _, episode, _ = parser.parse_script_header(self.FULL)
        assert episode == 1

    def test_full_header_extracts_title_from_last_quoted_string(self):
        _, _, _, title = parser.parse_script_header(self.FULL)
        assert title == "The Holiday Shift"

    def test_minimal_header_extracts_season(self):
        _, season, _, _ = parser.parse_script_header(self.MINIMAL)
        assert season == 1

    def test_minimal_header_extracts_title_after_episode(self):
        _, _, _, title = parser.parse_script_header(self.MINIMAL)
        assert title == "Test"

    def test_no_season_returns_none(self):
        _, season, _, _ = parser.parse_script_header(self.NO_SEASON)
        assert season is None

    def test_no_season_extracts_episode(self):
        _, _, episode, _ = parser.parse_script_header(self.NO_SEASON)
        assert episode == 2


# ─── Integration Test: parse_script with minimal fixture ───

MINIMAL_SCRIPT = """\
THE 413 Season 1: Episode 1: Test

CAST:

* ADAM SANTOS (Host)
* DEZ WILLIAMS (Supporting)

===

COLD OPEN

[AMBIENCE: RADIO STATION]

ADAM (on-air voice) It's 2:47 AM.

[BEAT]

ADAM (continuing) If you're listening right now, you're awake.

But let me back up.

===

ACT ONE

SCENE 1: THE DINER [AMBIENCE: DINER]

===

DEZ Adam. Over here.

ADAM (approaching) What's going on?

MR. PATTERSON (gravel-rough) That's because she had.

[SFX: DOOR OPENS] [MUSIC: THEME]

===

END OF EPISODE 1

===

PRODUCTION NOTES:

* Should not appear in output
"""


class TestParseScriptIntegration:
    @pytest.fixture
    def parsed(self, tmp_path):
        script_file = tmp_path / "test_script.md"
        script_file.write_text(MINIMAL_SCRIPT, encoding="utf-8")
        return parser.parse_script(str(script_file))

    def test_top_level_metadata(self, parsed):
        assert parsed["show"] == "THE 413"
        assert parsed["episode"] == 1
        assert parsed["season"] == 1

    def test_dialogue_count(self, parsed):
        assert parsed["stats"]["dialogue_lines"] == 5  # ADAM x3, DEZ x1, MR. PATTERSON x1

    def test_all_speakers_found(self, parsed):
        assert set(parsed["stats"]["speakers"]) == {"adam", "dez", "mr_patterson"}

    def test_sections_tracked(self, parsed):
        assert "cold-open" in parsed["stats"]["sections"]
        assert "act1" in parsed["stats"]["sections"]

    def test_direction_extracted(self, parsed):
        dialogue = [e for e in parsed["entries"] if e["type"] == "dialogue"]
        adam_first = dialogue[0]
        assert adam_first["speaker"] == "adam"
        assert adam_first["direction"] == "on-air voice"
        assert adam_first["text"] == "It's 2:47 AM."

    def test_continuation_line_merged(self, parsed):
        dialogue = [e for e in parsed["entries"] if e["type"] == "dialogue"]
        # Second ADAM line should have continuation appended
        adam_second = dialogue[1]
        assert "But let me back up." in adam_second["text"]
        assert adam_second["text"].startswith("If you're listening")

    def test_scene_context(self, parsed):
        dialogue = [e for e in parsed["entries"] if e["type"] == "dialogue"]
        dez_line = [d for d in dialogue if d["speaker"] == "dez"][0]
        assert dez_line["scene"] == "scene-1"
        assert dez_line["section"] == "act1"

    def test_mr_patterson_parsed(self, parsed):
        dialogue = [e for e in parsed["entries"] if e["type"] == "dialogue"]
        mp = [d for d in dialogue if d["speaker"] == "mr_patterson"][0]
        assert mp["direction"] == "gravel-rough"
        assert mp["text"] == "That's because she had."

    def test_multi_direction_line(self, parsed):
        directions = [e for e in parsed["entries"] if e["type"] == "direction"]
        sfx_dirs = [d for d in directions if d["direction_type"] == "SFX"]
        music_dirs = [d for d in directions if d["direction_type"] == "MUSIC"]
        assert len(sfx_dirs) >= 1
        assert len(music_dirs) >= 1

    def test_scene_header_ambience_split(self, parsed):
        """Scene header with embedded [AMBIENCE:...] produces two entries."""
        scene_headers = [e for e in parsed["entries"] if e["type"] == "scene_header"]
        assert len(scene_headers) == 1
        # Scene header text should be clean (no brackets)
        assert "[" not in scene_headers[0]["text"]
        assert scene_headers[0]["text"] == "SCENE 1: THE DINER"
        # A separate AMBIENCE direction entry should follow
        ambience_dirs = [e for e in parsed["entries"]
                         if e["type"] == "direction" and e["direction_type"] == "AMBIENCE"]
        diner_ambience = [d for d in ambience_dirs if "DINER" in d["text"]]
        assert len(diner_ambience) >= 1
        assert diner_ambience[0]["scene"] == "scene-1"

    def test_metadata_excluded(self, parsed):
        all_text = " ".join(e["text"] for e in parsed["entries"] if e["text"])
        assert "Should not appear in output" not in all_text

    def test_cast_section_excluded(self, parsed):
        all_text = " ".join(e["text"] for e in parsed["entries"] if e["text"])
        assert "ADAM SANTOS (Host)" not in all_text

    def test_tts_character_count(self, parsed):
        dialogue = [e for e in parsed["entries"] if e["type"] == "dialogue"]
        expected = sum(len(d["text"]) for d in dialogue)
        assert parsed["stats"]["characters_for_tts"] == expected

    def test_sequence_numbers_ascending(self, parsed):
        seqs = [e["seq"] for e in parsed["entries"]]
        assert seqs == sorted(seqs)
        assert len(seqs) == len(set(seqs))  # all unique


# ─── Integration Test: parse full production script ───

FULL_SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "scripts",
    "Full Production Script THE 413 Season 1 _ Episode 1_ _The Empty Booth_ Arc_ _The Holiday Shift_ 1_11_26 CLAUDE.AI PROJECT THE 413.md"
)


@pytest.mark.skipif(not os.path.exists(FULL_SCRIPT_PATH), reason="Full production script not present")
class TestParseFullScript:
    @pytest.fixture
    def parsed(self):
        return parser.parse_script(FULL_SCRIPT_PATH)

    def test_all_seven_speakers(self, parsed):
        expected = {"adam", "ava", "dez", "frank", "maya", "mr_patterson", "rian"}
        assert set(parsed["stats"]["speakers"]) == expected

    def test_dialogue_line_count_in_range(self, parsed):
        # Should be approximately 127 lines (verified in prior runs)
        assert 120 <= parsed["stats"]["dialogue_lines"] <= 140

    def test_tts_chars_in_range(self, parsed):
        # Should be approximately 12,463 chars
        assert 10000 <= parsed["stats"]["characters_for_tts"] <= 15000

    def test_five_sections(self, parsed):
        assert len(parsed["stats"]["sections"]) == 5

    def test_no_backslash_escapes_in_dialogue(self, parsed):
        dialogue = [e for e in parsed["entries"] if e["type"] == "dialogue"]
        for d in dialogue:
            assert "\\" not in d["text"], f"Backslash in seq {d['seq']}: {d['text'][:50]}"

    def test_no_stage_directions_in_dialogue_text(self, parsed):
        dialogue = [e for e in parsed["entries"] if e["type"] == "dialogue"]
        for d in dialogue:
            assert not d["text"].startswith("["), f"Bracket in seq {d['seq']}: {d['text'][:50]}"

    def test_season_is_one(self, parsed):
        assert parsed["season"] == 1


# ─── Tests: scene header ambience splitting ───

SCRIPT_SCENE_NO_BRACKETS = """\
THE 413 Season 1: Episode 1: Test

===

ACT ONE

SCENE 1: THE DINER

ADAM Hello.

===

END OF EPISODE 1
"""

SCRIPT_SCENE_MULTI_BRACKETS = """\
THE 413 Season 1: Episode 1: Test

===

ACT ONE

SCENE 1: THE DINER [AMBIENCE: DINER SOUNDS] [SFX: DOOR OPENS]

ADAM Hello.

===

END OF EPISODE 1
"""


class TestSceneHeaderAmbienceSplit:
    """Test splitting embedded directions out of scene headers."""

    def test_scene_no_brackets_single_entry(self, tmp_path):
        """Scene header without brackets produces only a scene_header entry."""
        f = tmp_path / "script.md"
        f.write_text(SCRIPT_SCENE_NO_BRACKETS, encoding="utf-8")
        parsed = parser.parse_script(str(f))
        scene_headers = [e for e in parsed["entries"] if e["type"] == "scene_header"]
        assert len(scene_headers) == 1
        assert scene_headers[0]["text"] == "SCENE 1: THE DINER"
        # No direction entries from the scene header line
        directions = [e for e in parsed["entries"] if e["type"] == "direction"]
        assert len(directions) == 0

    def test_scene_multi_brackets_split(self, tmp_path):
        """Scene header with multiple brackets produces scene_header + N direction entries."""
        f = tmp_path / "script.md"
        f.write_text(SCRIPT_SCENE_MULTI_BRACKETS, encoding="utf-8")
        parsed = parser.parse_script(str(f))
        scene_headers = [e for e in parsed["entries"] if e["type"] == "scene_header"]
        assert len(scene_headers) == 1
        assert "[" not in scene_headers[0]["text"]
        assert scene_headers[0]["text"] == "SCENE 1: THE DINER"
        # Two direction entries from the brackets
        directions = [e for e in parsed["entries"] if e["type"] == "direction"]
        assert len(directions) == 2
        types = {d["direction_type"] for d in directions}
        assert "AMBIENCE" in types
        assert "SFX" in types

    def test_scene_ambience_has_correct_scene_context(self, tmp_path):
        """Split direction entries inherit the scene context."""
        f = tmp_path / "script.md"
        f.write_text(SCRIPT_SCENE_MULTI_BRACKETS, encoding="utf-8")
        parsed = parser.parse_script(str(f))
        directions = [e for e in parsed["entries"] if e["type"] == "direction"]
        for d in directions:
            assert d["scene"] == "scene-1"
            assert d["section"] == "act1"

    def test_sequence_numbers_still_ascending(self, tmp_path):
        """Sequence numbers remain unique and ascending after split."""
        f = tmp_path / "script.md"
        f.write_text(SCRIPT_SCENE_MULTI_BRACKETS, encoding="utf-8")
        parsed = parser.parse_script(str(f))
        seqs = [e["seq"] for e in parsed["entries"]]
        assert seqs == sorted(seqs)
        assert len(seqs) == len(set(seqs))


# ─── Tests: script without season in header ───

SCRIPT_WITHOUT_SEASON = """\
THE 413 Episode 2: Another Episode

CAST:

* ADAM SANTOS (Host)

===

COLD OPEN

ADAM Hello.

===

END OF EPISODE 2
"""


class TestParseScriptNoSeason:
    @pytest.fixture
    def parsed(self, tmp_path):
        script_file = tmp_path / "no_season.md"
        script_file.write_text(SCRIPT_WITHOUT_SEASON, encoding="utf-8")
        return parser.parse_script(str(script_file))

    def test_season_is_none_when_not_in_header(self, parsed):
        assert parsed["season"] is None

    def test_episode_still_extracted(self, parsed):
        assert parsed["episode"] == 2


# ─── Tests: print_summary and print_dialogue_preview ───

class TestPrintSummary:
    @pytest.fixture
    def parsed(self, tmp_path):
        script_file = tmp_path / "script.md"
        script_file.write_text(MINIMAL_SCRIPT, encoding="utf-8")
        return parser.parse_script(str(script_file))

    def test_prints_show_title(self, parsed, capsys):
        parser.print_summary(parsed)
        out = capsys.readouterr().out
        assert "THE 413" in out
        assert "Test" in out  # title from MINIMAL_SCRIPT header

    def test_prints_dialogue_line_count(self, parsed, capsys):
        parser.print_summary(parsed)
        out = capsys.readouterr().out
        assert "Dialogue lines" in out
        assert "5" in out

    def test_prints_per_speaker_stats(self, parsed, capsys):
        parser.print_summary(parsed)
        out = capsys.readouterr().out
        assert "adam" in out
        assert "dez" in out
        assert "mr_patterson" in out

    def test_prints_tts_character_count(self, parsed, capsys):
        parser.print_summary(parsed)
        out = capsys.readouterr().out
        assert "TTS characters" in out


class TestPrintDialoguePreview:
    @pytest.fixture
    def parsed(self, tmp_path):
        script_file = tmp_path / "script.md"
        script_file.write_text(MINIMAL_SCRIPT, encoding="utf-8")
        return parser.parse_script(str(script_file))

    def test_prints_all_lines_by_default(self, parsed, capsys):
        parser.print_dialogue_preview(parsed)
        out = capsys.readouterr().out
        assert "It's 2:47 AM." in out
        assert "That's because she had." in out

    def test_limit_restricts_output(self, parsed, capsys):
        parser.print_dialogue_preview(parsed, limit=1)
        out = capsys.readouterr().out
        assert "It's 2:47 AM." in out
        assert "That's because she had." not in out

    def test_shows_speaker_name(self, parsed, capsys):
        parser.print_dialogue_preview(parsed)
        out = capsys.readouterr().out
        assert "adam" in out
        assert "dez" in out

    def test_shows_direction(self, parsed, capsys):
        parser.print_dialogue_preview(parsed)
        out = capsys.readouterr().out
        assert "on-air voice" in out


# ─── Tests: metadata section path (lines 173-174, 178) ───

SCRIPT_WITH_METADATA_BEFORE_END = """\
THE 413 Episode 1: Test

===

COLD OPEN

ADAM Hello.

PRODUCTION NOTES:

* This should be excluded

DEZ Should not appear either.

===

END OF EPISODE 1
"""


class TestMetadataSectionPath:
    def test_metadata_lines_excluded(self, tmp_path):
        script_file = tmp_path / "script.md"
        script_file.write_text(SCRIPT_WITH_METADATA_BEFORE_END, encoding="utf-8")
        parsed = parser.parse_script(str(script_file))
        all_text = " ".join(e["text"] for e in parsed["entries"] if e.get("text"))
        assert "Should not appear either." not in all_text

    def test_dialogue_before_metadata_included(self, tmp_path):
        script_file = tmp_path / "script.md"
        script_file.write_text(SCRIPT_WITH_METADATA_BEFORE_END, encoding="utf-8")
        parsed = parser.parse_script(str(script_file))
        dialogue = [e for e in parsed["entries"] if e["type"] == "dialogue"]
        assert any("Hello." in d["text"] for d in dialogue)


# ─── Contract Tests: parse_script output validates against Pydantic models ───

# Import models
_models_path = os.path.join(os.path.dirname(__file__), "..", "models.py")
_models_spec = importlib.util.spec_from_file_location("models", _models_path)
models = importlib.util.module_from_spec(_models_spec)
_models_spec.loader.exec_module(models)


class TestParseScriptModelContract:
    """Verify parse_script output is valid against Pydantic models."""

    @pytest.fixture
    def parsed(self, tmp_path):
        script_file = tmp_path / "test_script.md"
        script_file.write_text(MINIMAL_SCRIPT, encoding="utf-8")
        return parser.parse_script(str(script_file))

    def test_entries_are_valid_script_entry_models(self, parsed):
        for entry in parsed["entries"]:
            models.ScriptEntry(**entry)

    def test_stats_is_valid_script_stats_model(self, parsed):
        models.ScriptStats(**parsed["stats"])

    def test_full_output_is_valid_parsed_script_model(self, parsed):
        models.ParsedScript(**parsed)


# ─── Tests: --debug CSV output ───

import csv as csv_module


class TestDebugCSV:
    """Tests for write_debug_csv and parse_script debug_output parameter."""

    SCRIPT = """\
THE 413 Season 1: Episode 1: Test

CAST:

* ADAM SANTOS (Host)

===

COLD OPEN

[AMBIENCE: RADIO STATION]

ADAM (on-air voice) It's 2:47 AM.

===

END OF EPISODE 1
"""

    def _parse_with_debug(self, tmp_path):
        script_file = tmp_path / "debug_script.md"
        script_file.write_text(self.SCRIPT, encoding="utf-8")
        csv_path = str(tmp_path / "debug.csv")
        parser.parse_script(str(script_file), debug_output=csv_path)
        return csv_path

    def _read_csv(self, csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            return list(csv_module.DictReader(f))

    def test_debug_csv_created(self, tmp_path):
        csv_path = self._parse_with_debug(tmp_path)
        assert os.path.exists(csv_path)

    def test_no_csv_without_debug_output(self, tmp_path):
        script_file = tmp_path / "script.md"
        script_file.write_text(self.SCRIPT, encoding="utf-8")
        default_csv = str(tmp_path / "parsed.csv")
        parser.parse_script(str(script_file))
        assert not os.path.exists(default_csv)

    def test_csv_has_expected_columns(self, tmp_path):
        csv_path = self._parse_with_debug(tmp_path)
        rows = self._read_csv(csv_path)
        assert rows, "CSV should have at least one data row"
        expected = {"md_line_num", "md_raw", "seq", "type", "section",
                    "scene", "speaker", "direction", "text", "direction_type"}
        assert expected == set(rows[0].keys())

    def test_direction_entry_row(self, tmp_path):
        csv_path = self._parse_with_debug(tmp_path)
        rows = self._read_csv(csv_path)
        direction_rows = [r for r in rows if r["type"] == "direction"]
        assert direction_rows, "Should have at least one direction row"
        row = direction_rows[0]
        assert row["direction_type"] == "AMBIENCE"
        assert "AMBIENCE: RADIO STATION" in row["text"]
        assert "[AMBIENCE: RADIO STATION]" in row["md_raw"]

    def test_dialogue_entry_row(self, tmp_path):
        csv_path = self._parse_with_debug(tmp_path)
        rows = self._read_csv(csv_path)
        dialogue_rows = [r for r in rows if r["type"] == "dialogue"]
        assert dialogue_rows, "Should have at least one dialogue row"
        row = dialogue_rows[0]
        assert row["speaker"] == "adam"
        assert "2:47" in row["text"]
        assert row["direction"] == "on-air voice"

    def test_md_line_num_is_1_based(self, tmp_path):
        csv_path = self._parse_with_debug(tmp_path)
        rows = self._read_csv(csv_path)
        line_nums = [int(r["md_line_num"]) for r in rows]
        assert all(n >= 1 for n in line_nums), "Line numbers must be 1-based"

    def test_text_truncated_at_200_chars(self, tmp_path):
        long_line = "A" * 250
        script = f"THE 413 Season 1: Episode 1: Test\n\n===\n\nCOLD OPEN\n\nADAM {long_line}\n\n===\n\nEND OF EPISODE 1\n"
        script_file = tmp_path / "long_script.md"
        script_file.write_text(script, encoding="utf-8")
        csv_path = str(tmp_path / "long_debug.csv")
        parser.parse_script(str(script_file), debug_output=csv_path)
        rows = self._read_csv(csv_path)
        dialogue_rows = [r for r in rows if r["type"] == "dialogue"]
        assert dialogue_rows
        assert len(dialogue_rows[0]["text"]) <= 200

    def test_md_raw_truncated_at_200_chars(self, tmp_path):
        long_text = "B" * 250
        script = f"THE 413 Season 1: Episode 1: Test\n\n===\n\nCOLD OPEN\n\nADAM {long_text}\n\n===\n\nEND OF EPISODE 1\n"
        script_file = tmp_path / "long_script2.md"
        script_file.write_text(script, encoding="utf-8")
        csv_path = str(tmp_path / "long_debug2.csv")
        parser.parse_script(str(script_file), debug_output=csv_path)
        rows = self._read_csv(csv_path)
        for row in rows:
            assert len(row["md_raw"]) <= 200

    def test_section_header_row_present(self, tmp_path):
        csv_path = self._parse_with_debug(tmp_path)
        rows = self._read_csv(csv_path)
        section_rows = [r for r in rows if r["type"] == "section_header"]
        assert section_rows, "Should have a section_header row"
        assert section_rows[0]["section"] == "cold-open"


# ─── Tests: --episode validation ───

class TestEpisodeValidation:
    @pytest.fixture
    def script_file(self, tmp_path):
        script_file = tmp_path / "test_script.md"
        script_file.write_text(MINIMAL_SCRIPT, encoding="utf-8")
        return str(script_file)

    def test_episode_matches_header(self, script_file, tmp_path):
        """No error when --episode matches script header."""
        output = str(tmp_path / "out.json")
        with unittest.mock.patch("sys.argv", [
            "XILP001", script_file, "--episode", "S01E01",
            "--output", output, "--quiet",
        ]):
            parser.main()
        assert os.path.exists(output)

    def test_episode_mismatch_exits(self, script_file, tmp_path):
        """SystemExit when --episode doesn't match script header."""
        output = str(tmp_path / "out.json")
        with pytest.raises(SystemExit):
            with unittest.mock.patch("sys.argv", [
                "XILP001", script_file, "--episode", "S99E99",
                "--output", output, "--quiet",
            ]):
                parser.main()

    def test_no_episode_arg_works(self, script_file, tmp_path):
        """Parser works normally without --episode."""
        output = str(tmp_path / "out.json")
        with unittest.mock.patch("sys.argv", [
            "XILP001", script_file, "--output", output, "--quiet",
        ]):
            parser.main()
        assert os.path.exists(output)


# ─── Tests: generate_cast_config ───

class TestGenerateCastConfig:
    @pytest.fixture
    def parsed(self, tmp_path):
        script_file = tmp_path / "test_script.md"
        script_file.write_text(MINIMAL_SCRIPT, encoding="utf-8")
        return parser.parse_script(str(script_file))

    def test_creates_cast_file_when_absent(self, parsed, tmp_path):
        cast_path = str(tmp_path / "cast_the413_S01E01.json")
        parser.generate_cast_config(parsed, cast_path)
        assert os.path.exists(cast_path)

    def test_cast_has_correct_speakers(self, parsed, tmp_path):
        cast_path = str(tmp_path / "cast_the413_S01E01.json")
        parser.generate_cast_config(parsed, cast_path)
        with open(cast_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        assert "adam" in config["cast"]
        assert "dez" in config["cast"]
        assert "mr_patterson" in config["cast"]

    def test_cast_has_tbd_voice_ids(self, parsed, tmp_path):
        cast_path = str(tmp_path / "cast_the413_S01E01.json")
        parser.generate_cast_config(parsed, cast_path)
        with open(cast_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        for member in config["cast"].values():
            assert member["voice_id"] == "TBD"

    def test_cast_metadata_from_script(self, parsed, tmp_path):
        cast_path = str(tmp_path / "cast_the413_S01E01.json")
        parser.generate_cast_config(parsed, cast_path)
        with open(cast_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        assert config["show"] == "THE 413"
        assert config["season"] == 1
        assert config["episode"] == 1

    def test_cast_member_defaults(self, parsed, tmp_path):
        cast_path = str(tmp_path / "cast.json")
        parser.generate_cast_config(parsed, cast_path)
        with open(cast_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        member = config["cast"]["adam"]
        assert member["pan"] == 0.0
        assert member["filter"] is False
        assert member["role"] == "TBD"

    def test_skips_when_cast_exists(self, parsed, tmp_path, capsys):
        """main() should not overwrite existing cast config."""
        script_file = tmp_path / "test_script.md"
        script_file.write_text(MINIMAL_SCRIPT, encoding="utf-8")
        cast_path = tmp_path / "cast_the413_S01E01.json"
        cast_path.write_text('{"existing": true}', encoding="utf-8")
        output = str(tmp_path / "out.json")
        original_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            with unittest.mock.patch("sys.argv", [
                "XILP001", str(script_file), "--episode", "S01E01",
                "--output", output, "--quiet",
            ]):
                parser.main()
        finally:
            os.chdir(original_cwd)
        with open(str(cast_path), "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == {"existing": True}


# ─── Tests: generate_sfx_config ───

class TestGenerateSfxConfig:
    @pytest.fixture
    def parsed(self, tmp_path):
        script_file = tmp_path / "test_script.md"
        script_file.write_text(MINIMAL_SCRIPT, encoding="utf-8")
        return parser.parse_script(str(script_file))

    def test_creates_sfx_file_when_absent(self, parsed, tmp_path):
        sfx_path = str(tmp_path / "sfx_the413_S01E01.json")
        parser.generate_sfx_config(parsed, sfx_path)
        assert os.path.exists(sfx_path)

    def test_beat_is_silence_type(self, parsed, tmp_path):
        sfx_path = str(tmp_path / "sfx.json")
        parser.generate_sfx_config(parsed, sfx_path)
        with open(sfx_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        assert config["effects"]["BEAT"]["type"] == "silence"
        assert config["effects"]["BEAT"]["duration_seconds"] == 1.0

    def test_sfx_has_prompt(self, parsed, tmp_path):
        sfx_path = str(tmp_path / "sfx.json")
        parser.generate_sfx_config(parsed, sfx_path)
        with open(sfx_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        assert "prompt" in config["effects"]["SFX: DOOR OPENS"]

    def test_ambience_has_loop_true(self, parsed, tmp_path):
        sfx_path = str(tmp_path / "sfx.json")
        parser.generate_sfx_config(parsed, sfx_path)
        with open(sfx_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        ambience = config["effects"]["AMBIENCE: RADIO STATION"]
        assert ambience["loop"] is True
        assert ambience["duration_seconds"] == 30.0

    def test_music_duration(self, parsed, tmp_path):
        sfx_path = str(tmp_path / "sfx.json")
        parser.generate_sfx_config(parsed, sfx_path)
        with open(sfx_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        assert config["effects"]["MUSIC: THEME"]["duration_seconds"] == 15.0

    def test_sfx_metadata_from_script(self, parsed, tmp_path):
        sfx_path = str(tmp_path / "sfx.json")
        parser.generate_sfx_config(parsed, sfx_path)
        with open(sfx_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        assert config["show"] == "THE 413"
        assert config["season"] == 1
        assert config["episode"] == 1
        assert config["defaults"]["prompt_influence"] == 0.3

    def test_skips_when_sfx_exists(self, parsed, tmp_path, capsys):
        """main() should not overwrite existing sfx config."""
        script_file = tmp_path / "test_script.md"
        script_file.write_text(MINIMAL_SCRIPT, encoding="utf-8")
        sfx_path = tmp_path / "sfx_the413_S01E01.json"
        sfx_path.write_text('{"existing": true}', encoding="utf-8")
        # Also need cast to exist to avoid creating it
        cast_path = tmp_path / "cast_the413_S01E01.json"
        cast_path.write_text('{"existing": true}', encoding="utf-8")
        output = str(tmp_path / "out.json")
        original_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            with unittest.mock.patch("sys.argv", [
                "XILP001", str(script_file), "--episode", "S01E01",
                "--output", output, "--quiet",
            ]):
                parser.main()
        finally:
            os.chdir(original_cwd)
        with open(str(sfx_path), "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == {"existing": True}

    def test_unique_effects_only(self, parsed, tmp_path):
        """Duplicate direction entries should produce one effect."""
        sfx_path = str(tmp_path / "sfx.json")
        parser.generate_sfx_config(parsed, sfx_path)
        with open(sfx_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        # AMBIENCE: DINER appears via scene header split
        effect_keys = list(config["effects"].keys())
        assert len(effect_keys) == len(set(effect_keys))
