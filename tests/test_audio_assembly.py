"""Tests for XILP003_the413_audio_assembly.py — standalone audio assembly."""

import importlib.util
import json
import os
import unittest.mock

import pytest

# Import the assembly module — no ElevenLabs mock needed
_assembly_path = os.path.join(
    os.path.dirname(__file__), "..", "XILP003_the413_audio_assembly.py"
)
spec = importlib.util.spec_from_file_location(
    "audio_assembly", _assembly_path
)
assembly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembly)


# ─── Fixtures ───

@pytest.fixture
def sample_cast(tmp_path):
    cast = {
        "show": "TEST SHOW",
        "episode": 1,
        "cast": {
            "adam": {"full_name": "Adam Santos", "voice_id": "voice_adam_123",
                     "pan": 0.0, "filter": False, "role": "Host"},
            "frank": {"full_name": "Frank", "voice_id": "TBD",
                      "pan": 0.0, "filter": True, "role": "Minor"},
        }
    }
    cast_file = tmp_path / "cast.json"
    cast_file.write_text(json.dumps(cast), encoding="utf-8")
    return str(cast_file)


@pytest.fixture
def config():
    return {
        "adam": {"id": "voice_adam_123", "pan": 0.0, "filter": False},
        "frank": {"id": "voice_frank", "pan": 0.0, "filter": True},
    }


@pytest.fixture
def stems_with_audio(tmp_path):
    """Create minimal valid MP3 stems for assembly testing."""
    from pydub import AudioSegment
    from pydub.generators import Sine
    stems_dir = tmp_path / "stems"
    stems_dir.mkdir()
    for name in ["003_cold-open_adam", "007_act1-scene-1_frank"]:
        tone = Sine(440).to_audio_segment(duration=200)
        tone.export(str(stems_dir / f"{name}.mp3"), format="mp3")
    return stems_dir


# ─── Tests: module import ───

class TestModuleImport:
    def test_audio_assembly_importable(self):
        assert assembly is not None

    def test_no_elevenlabs_import(self):
        """XILP003 must not import elevenlabs — assembly is API-free."""
        import ast
        with open(_assembly_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        assert not any("elevenlabs" in imp for imp in imports), (
            "XILP003 must not import elevenlabs"
        )


# ─── Tests: apply_phone_filter ───

class TestApplyPhoneFilter:
    def test_returns_audio_segment(self):
        from pydub import AudioSegment
        from pydub.generators import Sine
        tone = Sine(440).to_audio_segment(duration=100)
        filtered = assembly.apply_phone_filter(tone)
        assert isinstance(filtered, AudioSegment)
        assert len(filtered) > 0


# ─── Tests: assemble_audio ───

class TestAssembleAudio:
    def test_assembles_to_mp3(self, config, stems_with_audio, tmp_path):
        original_dir = assembly.STEMS_DIR
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        assembly.STEMS_DIR = str(stems_with_audio)
        try:
            with unittest.mock.patch("os.system"):
                assembly.assemble_audio(config)
            assert (tmp_path / "the413_ep01_master.mp3").exists()
        finally:
            assembly.STEMS_DIR = original_dir
            os.chdir(original_cwd)

    def test_no_stems_prints_warning(self, config, tmp_path, capsys):
        empty_dir = tmp_path / "empty_stems"
        empty_dir.mkdir()
        original_dir = assembly.STEMS_DIR
        assembly.STEMS_DIR = str(empty_dir)
        try:
            assembly.assemble_audio(config)
        finally:
            assembly.STEMS_DIR = original_dir
        out = capsys.readouterr().out
        assert "No stems found" in out

    def test_applies_phone_filter_for_frank(self, config, stems_with_audio, tmp_path):
        original_dir = assembly.STEMS_DIR
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        assembly.STEMS_DIR = str(stems_with_audio)
        try:
            with unittest.mock.patch("os.system"):
                with unittest.mock.patch.object(
                    assembly, "apply_phone_filter",
                    wraps=assembly.apply_phone_filter
                ) as mock_filter:
                    assembly.assemble_audio(config)
                    mock_filter.assert_called_once()  # only frank gets filtered
        finally:
            assembly.STEMS_DIR = original_dir
            os.chdir(original_cwd)


# ─── Tests: standalone config loading from cast file ───

class TestAssembleAudioFromCastFile:
    """XILP003 builds config directly from cast_the413.json, no load_production()."""

    def test_main_loads_config_from_cast_json(self, sample_cast, tmp_path, capsys):
        """main() reads cast file and passes config to assemble_audio."""
        empty_stems = tmp_path / "stems"
        empty_stems.mkdir()
        original_dir = assembly.STEMS_DIR
        assembly.STEMS_DIR = str(empty_stems)
        try:
            with unittest.mock.patch(
                "sys.argv",
                ["XILP003", "--cast", sample_cast]
            ):
                assembly.main()
        finally:
            assembly.STEMS_DIR = original_dir
        out = capsys.readouterr().out
        # Should attempt assembly (no stems = warning), not crash on config load
        assert "No stems found" in out
