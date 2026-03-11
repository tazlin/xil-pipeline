"""Tests for XILP005_the413_daw_export.py — DAW layer export."""

import importlib.util
import json
import os
import unittest.mock

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

# ─── Import XILP005 ───

_daw_path = os.path.join(
    os.path.dirname(__file__), "..", "XILP005_the413_daw_export.py"
)
spec = importlib.util.spec_from_file_location("daw_export", _daw_path)
daw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daw)


# ─── Helpers ───

def _make_tone(duration_ms: int = 200) -> AudioSegment:
    return Sine(440).to_audio_segment(duration=duration_ms)


def _write_mp3(path: str, duration_ms: int = 200) -> None:
    _make_tone(duration_ms).export(path, format="mp3")


# ─── Fixtures ───

@pytest.fixture
def cast_data():
    return {
        "show": "THE 413",
        "season": 1,
        "episode": 1,
        "title": "Test Episode",
        "cast": {
            "adam": {"full_name": "Adam Santos", "voice_id": "abc123",
                     "pan": 0.0, "filter": False, "role": "Host"},
            "ava":  {"full_name": "Ava", "voice_id": "def456",
                     "pan": 0.3, "filter": True, "role": "Guest"},
        },
    }


@pytest.fixture
def cast_file(tmp_path, cast_data):
    p = tmp_path / "cast_the413_S01E01.json"
    p.write_text(json.dumps(cast_data), encoding="utf-8")
    return str(p)


@pytest.fixture
def parsed_data():
    return {
        "show": "THE 413", "season": 1, "episode": 1, "title": "Test",
        "source_file": "test.md",
        "entries": [
            {"seq": 1, "type": "section_header", "section": "cold-open",
             "scene": None, "speaker": None, "direction": None,
             "text": "COLD OPEN", "direction_type": None},
            {"seq": 2, "type": "direction", "section": "cold-open",
             "scene": None, "speaker": None, "direction": None,
             "text": "AMBIENCE: DINER", "direction_type": "AMBIENCE"},
            {"seq": 3, "type": "dialogue", "section": "cold-open",
             "scene": None, "speaker": "adam", "direction": None,
             "text": "Hello.", "direction_type": None},
            {"seq": 4, "type": "direction", "section": "cold-open",
             "scene": None, "speaker": None, "direction": None,
             "text": "BEAT", "direction_type": "BEAT"},
            {"seq": 5, "type": "dialogue", "section": "cold-open",
             "scene": None, "speaker": "ava", "direction": None,
             "text": "Hi.", "direction_type": None},
            {"seq": 6, "type": "direction", "section": "cold-open",
             "scene": None, "speaker": None, "direction": None,
             "text": "MUSIC: STING", "direction_type": "MUSIC"},
        ],
        "stats": {"total_entries": 6, "dialogue_lines": 2, "direction_lines": 3,
                  "characters_for_tts": 9, "speakers": ["adam", "ava"],
                  "sections": ["cold-open"]},
    }


@pytest.fixture
def parsed_file(tmp_path, parsed_data):
    p = tmp_path / "parsed_the413_S01E01.json"
    p.write_text(json.dumps(parsed_data), encoding="utf-8")
    return str(p)


@pytest.fixture
def stems_dir(tmp_path):
    """Stems directory with dialogue, ambience, beat, and music stems."""
    d = tmp_path / "stems" / "S01E01"
    d.mkdir(parents=True)
    _write_mp3(str(d / "003_cold-open_adam.mp3"), duration_ms=300)   # dialogue
    _write_mp3(str(d / "005_cold-open_ava.mp3"),  duration_ms=250)   # dialogue
    _write_mp3(str(d / "002_cold-open_sfx.mp3"),  duration_ms=500)   # ambience
    _write_mp3(str(d / "004_cold-open_sfx.mp3"),  duration_ms=100)   # beat
    _write_mp3(str(d / "006_cold-open_sfx.mp3"),  duration_ms=200)   # music
    return str(d)


@pytest.fixture
def config(cast_data):
    return {
        "adam": {"id": "abc123", "pan": 0.0, "filter": False},
        "ava":  {"id": "def456", "pan": 0.3, "filter": True},
    }


# ─── Tests: module import ───

class TestModuleImport:
    def test_daw_export_importable(self):
        assert daw is not None

    def test_no_elevenlabs_import(self):
        import ast
        with open(_daw_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        assert not any("elevenlabs" in imp for imp in imports)

    def test_main_function_exists(self):
        assert callable(getattr(daw, "main", None))


# ─── Tests: _make_audacity_script ───

class TestMakeAudacityScript:
    def test_returns_string(self):
        result = daw._make_audacity_script("S01E01", [("Dialogue", "d.wav")])
        assert isinstance(result, str)

    def test_contains_tag(self):
        result = daw._make_audacity_script("S01E02", [("Dialogue", "d.wav")])
        assert "S01E02" in result

    def test_contains_layer_names(self):
        layers = [("Dialogue", "d.wav"), ("Ambience", "a.wav")]
        result = daw._make_audacity_script("S01E01", layers)
        assert "Dialogue" in result
        assert "Ambience" in result

    def test_contains_manual_instructions(self):
        result = daw._make_audacity_script("S01E01", [("Dialogue", "d.wav")])
        assert "Import" in result


# ─── Tests: dry_run_daw ───

class TestDryRunDaw:
    def test_prints_summary(self, stems_dir, parsed_file, config, capsys):
        from mix_common import load_entries_index, collect_stem_plans
        idx = load_entries_index(parsed_file)
        plans = collect_stem_plans(stems_dir, idx)
        daw.dry_run_daw("S01E01", plans, idx, "daw/S01E01")
        out = capsys.readouterr().out
        assert "S01E01" in out
        assert "dialogue" in out.lower()
        assert "ambience" in out.lower()


# ─── Tests: export_daw_layers ───

class TestExportDawLayers:
    def test_creates_four_wav_files(self, config, stems_dir, parsed_file, tmp_path):
        output_dir = str(tmp_path / "daw" / "S01E01")
        daw.export_daw_layers(config, stems_dir, parsed_file, output_dir, "S01E01")
        for _, suffix, _ in daw.LAYERS:
            assert os.path.exists(os.path.join(output_dir, f"S01E01_{suffix}.wav"))

    def test_creates_audacity_script(self, config, stems_dir, parsed_file, tmp_path):
        output_dir = str(tmp_path / "daw" / "S01E01")
        daw.export_daw_layers(config, stems_dir, parsed_file, output_dir, "S01E01")
        assert os.path.exists(os.path.join(output_dir, "S01E01_open_in_audacity.py"))

    def test_all_layers_same_duration(self, config, stems_dir, parsed_file, tmp_path):
        output_dir = str(tmp_path / "daw" / "S01E01")
        daw.export_daw_layers(config, stems_dir, parsed_file, output_dir, "S01E01")
        durations = []
        for _, suffix, _ in daw.LAYERS:
            seg = AudioSegment.from_file(
                os.path.join(output_dir, f"S01E01_{suffix}.wav")
            )
            durations.append(len(seg))
        assert len(set(durations)) == 1, f"Layer durations differ: {durations}"

    def test_dialogue_layer_is_stereo(self, config, stems_dir, parsed_file, tmp_path):
        output_dir = str(tmp_path / "daw" / "S01E01")
        daw.export_daw_layers(config, stems_dir, parsed_file, output_dir, "S01E01")
        seg = AudioSegment.from_file(
            os.path.join(output_dir, "S01E01_layer_dialogue.wav")
        )
        assert seg.channels == 2

    def test_no_stems_prints_warning(self, config, parsed_file, tmp_path, capsys):
        empty_stems = str(tmp_path / "empty_stems")
        os.makedirs(empty_stems)
        output_dir = str(tmp_path / "daw")
        daw.export_daw_layers(config, empty_stems, parsed_file, output_dir, "S01E01")
        assert "No stems found" in capsys.readouterr().out

    def test_dialogue_layer_not_all_silence(self, config, stems_dir, parsed_file, tmp_path):
        output_dir = str(tmp_path / "daw" / "S01E01")
        daw.export_daw_layers(config, stems_dir, parsed_file, output_dir, "S01E01")
        seg = AudioSegment.from_file(
            os.path.join(output_dir, "S01E01_layer_dialogue.wav")
        )
        assert seg.dBFS > -80, "Dialogue layer should contain audio, not silence"


# ─── Tests: XILP005 main() ───

class TestDawExportMain:
    def test_main_dry_run(self, cast_file, parsed_file, stems_dir, tmp_path, capsys):
        cast_path = cast_file
        parsed_path = parsed_file
        original_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            with unittest.mock.patch(
                "sys.argv",
                ["XILP005", "--episode", "S01E01",
                 "--parsed", parsed_path,
                 "--output-dir", str(tmp_path / "daw" / "S01E01"),
                 "--dry-run"],
            ):
                daw.main()
        finally:
            os.chdir(original_cwd)
        out = capsys.readouterr().out
        assert "Dry Run" in out or "dry" in out.lower()

    def test_main_exits_gracefully_no_parsed(self, cast_file, tmp_path, capsys):
        original_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            with unittest.mock.patch(
                "sys.argv",
                ["XILP005", "--episode", "S01E01",
                 "--parsed", str(tmp_path / "nonexistent.json")],
            ):
                daw.main()
        finally:
            os.chdir(original_cwd)
        out = capsys.readouterr().out
        assert "not found" in out or "Run XILP001" in out
