"""Tests for XILP002_the413_producer.py — production pipeline (non-API functions)."""

import os
import json
import tempfile
import importlib.util
import pytest

# Import the producer module
spec = importlib.util.spec_from_file_location(
    "producer",
    os.path.join(os.path.dirname(__file__), "..", "XILP002_the413_producer.py")
)
producer = importlib.util.module_from_spec(spec)

# Patch out ElevenLabs client before loading module (no API key needed for these tests)
import unittest.mock
with unittest.mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test_key"}):
    with unittest.mock.patch("elevenlabs.client.ElevenLabs"):
        spec.loader.exec_module(producer)


# ─── Fixtures ───

@pytest.fixture
def sample_cast(tmp_path):
    cast = {
        "show": "TEST SHOW",
        "episode": 1,
        "cast": {
            "adam": {"full_name": "Adam Santos", "voice_id": "voice_adam_123", "pan": 0.0, "filter": False, "role": "Host"},
            "dez": {"full_name": "Dez Williams", "voice_id": "voice_dez_456", "pan": -0.15, "filter": False, "role": "Supporting"},
            "frank": {"full_name": "Frank", "voice_id": "TBD", "pan": 0.0, "filter": True, "role": "Minor"},
        }
    }
    cast_file = tmp_path / "cast.json"
    cast_file.write_text(json.dumps(cast), encoding="utf-8")
    return str(cast_file)


@pytest.fixture
def sample_script(tmp_path):
    script = {
        "show": "TEST SHOW",
        "episode": 1,
        "title": "Test Episode",
        "entries": [
            {"seq": 1, "type": "section_header", "section": "cold-open", "scene": None,
             "speaker": None, "direction": None, "text": "COLD OPEN", "direction_type": None},
            {"seq": 2, "type": "direction", "section": "cold-open", "scene": None,
             "speaker": None, "direction": None, "text": "AMBIENCE: RADIO STATION", "direction_type": "AMBIENCE"},
            {"seq": 3, "type": "dialogue", "section": "cold-open", "scene": None,
             "speaker": "adam", "direction": "on-air voice", "text": "Hello listeners.", "direction_type": None},
            {"seq": 4, "type": "dialogue", "section": "cold-open", "scene": None,
             "speaker": "adam", "direction": None, "text": "Welcome to the show.", "direction_type": None},
            {"seq": 5, "type": "scene_header", "section": "act1", "scene": "scene-1",
             "speaker": None, "direction": None, "text": "SCENE 1: THE DINER", "direction_type": None},
            {"seq": 6, "type": "dialogue", "section": "act1", "scene": "scene-1",
             "speaker": "dez", "direction": "uneasy", "text": "Something happened.", "direction_type": None},
            {"seq": 7, "type": "dialogue", "section": "act1", "scene": "scene-1",
             "speaker": "frank", "direction": None, "text": "Put a fresh pot on.", "direction_type": None},
        ],
        "stats": {"dialogue_lines": 4}
    }
    script_file = tmp_path / "script.json"
    script_file.write_text(json.dumps(script), encoding="utf-8")
    return str(script_file)


# ─── Tests: load_production ───

class TestLoadProduction:
    def test_returns_config_and_entries(self, sample_script, sample_cast):
        config, entries = producer.load_production(sample_script, sample_cast)
        assert isinstance(config, dict)
        assert isinstance(entries, list)

    def test_config_has_voice_ids(self, sample_script, sample_cast):
        config, _ = producer.load_production(sample_script, sample_cast)
        assert config["adam"]["id"] == "voice_adam_123"
        assert config["dez"]["id"] == "voice_dez_456"
        assert config["frank"]["id"] == "TBD"

    def test_config_has_pan_and_filter(self, sample_script, sample_cast):
        config, _ = producer.load_production(sample_script, sample_cast)
        assert config["adam"]["pan"] == 0.0
        assert config["adam"]["filter"] is False
        assert config["frank"]["filter"] is True

    def test_only_dialogue_entries_returned(self, sample_script, sample_cast):
        _, entries = producer.load_production(sample_script, sample_cast)
        assert len(entries) == 4  # Only dialogue, not headers/directions

    def test_entry_has_stem_name(self, sample_script, sample_cast):
        _, entries = producer.load_production(sample_script, sample_cast)
        assert entries[0]["stem_name"] == "003_cold-open_adam"
        assert entries[2]["stem_name"] == "006_act1-scene-1_dez"

    def test_entry_preserves_speaker_and_text(self, sample_script, sample_cast):
        _, entries = producer.load_production(sample_script, sample_cast)
        assert entries[0]["speaker"] == "adam"
        assert entries[0]["text"] == "Hello listeners."

    def test_entry_preserves_direction(self, sample_script, sample_cast):
        _, entries = producer.load_production(sample_script, sample_cast)
        assert entries[0]["direction"] == "on-air voice"
        assert entries[1]["direction"] is None

    def test_entry_seq_preserved(self, sample_script, sample_cast):
        _, entries = producer.load_production(sample_script, sample_cast)
        seqs = [e["seq"] for e in entries]
        assert seqs == [3, 4, 6, 7]


# ─── Tests: dry_run ───

class TestDryRun:
    def test_prints_all_lines(self, sample_script, sample_cast, capsys):
        config, entries = producer.load_production(sample_script, sample_cast)
        producer.dry_run(config, entries)
        output = capsys.readouterr().out
        assert "4 dialogue lines" in output
        assert "Hello listeners." in output
        assert "Something happened." in output

    def test_shows_tbd_warning(self, sample_script, sample_cast, capsys):
        config, entries = producer.load_production(sample_script, sample_cast)
        producer.dry_run(config, entries)
        output = capsys.readouterr().out
        assert "TBD" in output
        assert "frank" in output

    def test_start_from_filters_count(self, sample_script, sample_cast, capsys):
        config, entries = producer.load_production(sample_script, sample_cast)
        producer.dry_run(config, entries, start_from=6)
        output = capsys.readouterr().out
        assert "FROM 6:" in output
        # Only seq 6 and 7 are >= 6
        assert "2 lines" in output

    def test_shows_stem_names(self, sample_script, sample_cast, capsys):
        config, entries = producer.load_production(sample_script, sample_cast)
        producer.dry_run(config, entries)
        output = capsys.readouterr().out
        assert "003_cold-open_adam.mp3" in output
        assert "006_act1-scene-1_dez.mp3" in output

    def test_shows_char_counts(self, sample_script, sample_cast, capsys):
        config, entries = producer.load_production(sample_script, sample_cast)
        producer.dry_run(config, entries)
        output = capsys.readouterr().out
        # "Hello listeners." = 16 chars
        assert "16 chars" in output


# ─── Integration: load from actual project files ───

ACTUAL_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "parsed", "parsed_the413_ep01.json")
ACTUAL_CAST = os.path.join(os.path.dirname(__file__), "..", "cast_the413.json")


@pytest.mark.skipif(
    not (os.path.exists(ACTUAL_SCRIPT) and os.path.exists(ACTUAL_CAST)),
    reason="Actual parsed script or cast config not present"
)
class TestLoadActualProduction:
    def test_loads_without_error(self):
        config, entries = producer.load_production(ACTUAL_SCRIPT, ACTUAL_CAST)
        assert len(entries) > 100
        assert "adam" in config

    def test_all_speakers_in_config(self):
        config, entries = producer.load_production(ACTUAL_SCRIPT, ACTUAL_CAST)
        speakers_in_script = set(e["speaker"] for e in entries)
        for speaker in speakers_in_script:
            assert speaker in config, f"Speaker '{speaker}' missing from cast config"

    def test_stem_names_are_unique(self):
        _, entries = producer.load_production(ACTUAL_SCRIPT, ACTUAL_CAST)
        stem_names = [e["stem_name"] for e in entries]
        assert len(stem_names) == len(set(stem_names)), "Duplicate stem names found"


# ─── Tests: check_elevenlabs_quota ───

class TestCheckElevenLabsQuota:
    def _make_sub(self, used, limit, tier="free"):
        sub = unittest.mock.MagicMock()
        sub.character_count = used
        sub.character_limit = limit
        sub.tier = tier
        return sub

    def test_returns_remaining(self, capsys):
        sub = self._make_sub(1000, 10000, "free")
        user_info = unittest.mock.MagicMock()
        user_info.subscription = sub
        producer.client.user.get.return_value = user_info

        result = producer.check_elevenlabs_quota()
        assert result == 9000

    def test_prints_status(self, capsys):
        sub = self._make_sub(500, 5000, "starter")
        user_info = unittest.mock.MagicMock()
        user_info.subscription = sub
        producer.client.user.get.return_value = user_info

        producer.check_elevenlabs_quota()
        out = capsys.readouterr().out
        assert "ELEVENLABS API STATUS" in out
        assert "STARTER" in out

    def test_returns_none_on_exception(self, capsys):
        producer.client.user.get.side_effect = Exception("API error")
        result = producer.check_elevenlabs_quota()
        assert result is None
        producer.client.user.get.side_effect = None


# ─── Tests: has_enough_characters ───

class TestHasEnoughCharacters:
    def _set_quota(self, remaining):
        sub = unittest.mock.MagicMock()
        sub.character_limit = 10000
        sub.character_count = 10000 - remaining
        user_info = unittest.mock.MagicMock()
        user_info.subscription = sub
        producer.client.user.get.return_value = user_info

    def test_returns_true_when_enough(self):
        self._set_quota(1000)
        assert producer.has_enough_characters("short text") is True

    def test_returns_false_when_insufficient(self, capsys):
        self._set_quota(5)
        assert producer.has_enough_characters("this is a much longer text than 5 chars") is False

    def test_returns_true_on_api_exception(self):
        producer.client.user.get.side_effect = Exception("no user_read")
        assert producer.has_enough_characters("any text") is True
        producer.client.user.get.side_effect = None


# ─── Tests: get_best_model_for_budget ───

class TestGetBestModelForBudget:
    def _set_quota(self, remaining):
        sub = unittest.mock.MagicMock()
        sub.character_limit = 100000
        sub.character_count = 100000 - remaining
        user_info = unittest.mock.MagicMock()
        user_info.subscription = sub
        producer.client.user.get.return_value = user_info

    def test_returns_v3_when_healthy(self):
        self._set_quota(50000)
        model = producer.get_best_model_for_budget()
        assert model == "eleven_v3"

    def test_returns_flash_when_low(self):
        self._set_quota(100)
        model = producer.get_best_model_for_budget()
        assert model == "eleven_flash_v2_5"

    def test_returns_fallback_on_exception(self):
        producer.client.user.get.side_effect = Exception("fail")
        model = producer.get_best_model_for_budget()
        assert model == "eleven_multilingual_v2"
        producer.client.user.get.side_effect = None


# ─── Tests: generate_voices ───

class TestGenerateVoices:
    @pytest.fixture
    def config(self):
        return {
            "adam": {"id": "voice_adam_123", "pan": 0.0, "filter": False},
            "dez": {"id": "TBD", "pan": -0.15, "filter": False},
        }

    @pytest.fixture
    def entries(self):
        return [
            {"seq": 3, "speaker": "adam", "text": "Hello listeners.", "stem_name": "003_cold-open_adam"},
            {"seq": 6, "speaker": "dez", "text": "Something happened.", "stem_name": "006_act1_dez"},
        ]

    def _setup_api(self, fake_audio=b"\xff\xfb\x10\x00" * 100):
        """Set up quota and TTS mocks."""
        sub = unittest.mock.MagicMock()
        sub.character_limit = 100000
        sub.character_count = 0
        user_info = unittest.mock.MagicMock()
        user_info.subscription = sub
        producer.client.user.get.return_value = user_info
        producer.client.text_to_speech.convert.return_value = [fake_audio]

    def test_skips_tbd_voice(self, config, entries, tmp_path, capsys):
        self._setup_api()
        original_dir = producer.STEMS_DIR
        producer.STEMS_DIR = str(tmp_path)
        try:
            producer.generate_voices(config, entries)
        finally:
            producer.STEMS_DIR = original_dir

        out = capsys.readouterr().out
        assert "No voice_id for dez" in out
        # dez stem should NOT exist
        assert not (tmp_path / "006_act1_dez.mp3").exists()

    def test_skips_existing_stem(self, config, entries, tmp_path, capsys):
        self._setup_api()
        # Pre-create the adam stem
        (tmp_path / "003_cold-open_adam.mp3").write_bytes(b"existing")
        original_dir = producer.STEMS_DIR
        producer.STEMS_DIR = str(tmp_path)
        try:
            producer.generate_voices(config, entries)
        finally:
            producer.STEMS_DIR = original_dir

        out = capsys.readouterr().out
        assert "skipping" in out

    def test_halts_when_quota_exhausted(self, config, entries, tmp_path, capsys):
        sub = unittest.mock.MagicMock()
        sub.character_limit = 1  # only 1 char left
        sub.character_count = 0
        user_info = unittest.mock.MagicMock()
        user_info.subscription = sub
        producer.client.user.get.return_value = user_info

        original_dir = producer.STEMS_DIR
        producer.STEMS_DIR = str(tmp_path)
        try:
            producer.generate_voices(config, entries)
        finally:
            producer.STEMS_DIR = original_dir

        out = capsys.readouterr().out
        assert "halted" in out

    def test_start_from_skips_earlier_entries(self, config, entries, tmp_path, capsys):
        self._setup_api()
        original_dir = producer.STEMS_DIR
        producer.STEMS_DIR = str(tmp_path)
        try:
            producer.generate_voices(config, entries, start_from=6)
        finally:
            producer.STEMS_DIR = original_dir

        out = capsys.readouterr().out
        # adam (seq=3) should not appear in generation output
        assert "003" not in out


# ─── Contract Tests: load_production output validates against Pydantic models ───

_models_path = os.path.join(os.path.dirname(__file__), "..", "models.py")
_models_spec = importlib.util.spec_from_file_location("models", _models_path)
models = importlib.util.module_from_spec(_models_spec)
_models_spec.loader.exec_module(models)


class TestLoadProductionModelContract:
    """Verify load_production output is valid against Pydantic models."""

    def test_config_values_are_valid_voice_configs(self, sample_script, sample_cast):
        config, _ = producer.load_production(sample_script, sample_cast)
        for key, val in config.items():
            models.VoiceConfig(**val)

    def test_entries_are_valid_dialogue_entries(self, sample_script, sample_cast):
        _, entries = producer.load_production(sample_script, sample_cast)
        for entry in entries:
            models.DialogueEntry(**entry)


# ─── Tests: truncate_to_words ───

class TestTruncateToWords:
    def test_three_words_from_long_line(self):
        result = producer.truncate_to_words("Hello listeners, welcome to the show.")
        assert result == "Hello listeners, welcome"

    def test_exactly_three_words(self):
        assert producer.truncate_to_words("One two three") == "One two three"

    def test_fewer_than_three_words(self):
        assert producer.truncate_to_words("Hello there") == "Hello there"

    def test_single_word(self):
        assert producer.truncate_to_words("Hello.") == "Hello."

    def test_empty_string(self):
        assert producer.truncate_to_words("") == ""

    def test_custom_word_count(self):
        assert producer.truncate_to_words("one two three four five", n=2) == "one two"


# ─── Tests: --terse mode ───

class TestTerseMode:
    def test_dry_run_shows_truncated_text(self, sample_script, sample_cast, capsys):
        config, entries = producer.load_production(sample_script, sample_cast)
        terse_entries = [
            {**e, "text": producer.truncate_to_words(e["text"])} for e in entries
        ]
        producer.dry_run(config, terse_entries)
        output = capsys.readouterr().out
        # "Hello listeners." → "Hello listeners." (only 2 words, unchanged)
        # "Welcome to the" instead of "Welcome to the show."
        assert "Welcome to the" in output
        assert "Welcome to the show." not in output

    def test_dry_run_char_count_reduced(self, sample_script, sample_cast, capsys):
        config, entries = producer.load_production(sample_script, sample_cast)
        # Full run char count
        producer.dry_run(config, entries)
        full_out = capsys.readouterr().out
        # Terse run char count
        terse_entries = [
            {**e, "text": producer.truncate_to_words(e["text"])} for e in entries
        ]
        producer.dry_run(config, terse_entries)
        terse_out = capsys.readouterr().out
        # Extract total chars from each output
        import re
        full_total = int(re.search(r"(\d+) TTS characters", full_out).group(1).replace(",", ""))
        terse_total = int(re.search(r"(\d+) TTS characters", terse_out).group(1).replace(",", ""))
        assert terse_total < full_total

    def test_generate_voices_sends_truncated_text(self, sample_script, sample_cast, tmp_path):
        """--terse entries reach the ElevenLabs API call with truncated text."""
        self._setup_api()
        config, entries = producer.load_production(sample_script, sample_cast)
        terse_entries = [
            {**e, "text": producer.truncate_to_words(e["text"])}
            for e in entries
            if e["speaker"] != "frank"  # skip TBD voice
        ]
        original_dir = producer.STEMS_DIR
        producer.STEMS_DIR = str(tmp_path)
        try:
            producer.generate_voices(config, terse_entries)
        finally:
            producer.STEMS_DIR = original_dir

        calls = producer.client.text_to_speech.convert.call_args_list
        for call in calls:
            text_sent = call.kwargs.get("text") or call.args[0] if call.args else None
            if text_sent:
                assert len(text_sent.split()) <= 3

    def _setup_api(self):
        sub = unittest.mock.MagicMock()
        sub.character_limit = 100000
        sub.character_count = 0
        sub.tier = "free"
        user_info = unittest.mock.MagicMock()
        user_info.subscription = sub
        producer.client.user.get.return_value = user_info
        producer.client.text_to_speech.convert.return_value = iter([b"fake_audio"])
