"""Tests for Pydantic data models (TDD — tests written before models)."""

import importlib.util
import os
import sys

import pytest

# Import models using importlib (consistent with other test files)
_models_path = os.path.join(os.path.dirname(__file__), "..", "models.py")
spec = importlib.util.spec_from_file_location("models", _models_path)
models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(models)


# ---------------------------------------------------------------------------
# Phase 0 — Foundation
# ---------------------------------------------------------------------------

class TestFoundation:
    """Verify pydantic is installed and models module is importable."""

    def test_models_module_importable(self):
        assert models is not None
        assert hasattr(models, "__doc__")

    def test_pydantic_available(self):
        import pydantic
        major = int(pydantic.VERSION.split(".")[0])
        assert major >= 2, f"Pydantic v2+ required, got {pydantic.VERSION}"


# ---------------------------------------------------------------------------
# Phase 1 — Script Models
# ---------------------------------------------------------------------------

from pydantic import ValidationError


class TestScriptEntry:
    """Tests for the ScriptEntry model."""

    def _make(self, **overrides):
        defaults = {
            "seq": 1,
            "type": "dialogue",
            "section": "cold-open",
            "scene": None,
            "speaker": "adam",
            "direction": "on-air voice",
            "text": "Hello world.",
            "direction_type": None,
        }
        defaults.update(overrides)
        return models.ScriptEntry(**defaults)

    def test_valid_dialogue_entry(self):
        entry = self._make()
        assert entry.seq == 1
        assert entry.type == "dialogue"
        assert entry.speaker == "adam"

    def test_valid_direction_entry(self):
        entry = self._make(
            type="direction", speaker=None, direction=None,
            text="[SFX: phone rings]", direction_type="SFX",
        )
        assert entry.type == "direction"
        assert entry.direction_type == "SFX"

    def test_valid_section_header(self):
        entry = self._make(
            type="section_header", speaker=None, direction=None,
            text="ACT ONE",
        )
        assert entry.type == "section_header"

    def test_valid_scene_header(self):
        entry = self._make(
            type="scene_header", speaker=None, direction=None,
            text="SCENE 1: The Studio",
        )
        assert entry.type == "scene_header"

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            self._make(type="unknown")

    def test_seq_must_be_positive(self):
        with pytest.raises(ValidationError):
            self._make(seq=0)
        with pytest.raises(ValidationError):
            self._make(seq=-1)

    def test_direction_type_literal_validated(self):
        for dt in ("SFX", "MUSIC", "AMBIENCE", "BEAT", None):
            entry = self._make(direction_type=dt)
            assert entry.direction_type == dt
        with pytest.raises(ValidationError):
            self._make(direction_type="INVALID")

    def test_model_dump_roundtrip(self):
        raw = {
            "seq": 3,
            "type": "dialogue",
            "section": "cold-open",
            "scene": None,
            "speaker": "adam",
            "direction": "on-air voice, warm",
            "text": "It's 2:47 AM on a Wednesday...",
            "direction_type": None,
        }
        assert models.ScriptEntry(**raw).model_dump() == raw


class TestScriptStats:
    """Tests for the ScriptStats model."""

    def _make(self, **overrides):
        defaults = {
            "total_entries": 127,
            "dialogue_lines": 80,
            "direction_lines": 47,
            "characters_for_tts": 12463,
            "speakers": ["adam", "dez"],
            "sections": ["cold-open", "act1"],
        }
        defaults.update(overrides)
        return models.ScriptStats(**defaults)

    def test_valid_stats(self):
        stats = self._make()
        assert stats.total_entries == 127
        assert stats.speakers == ["adam", "dez"]

    def test_total_entries_non_negative(self):
        with pytest.raises(ValidationError):
            self._make(total_entries=-1)

    def test_model_dump_roundtrip(self):
        raw = {
            "total_entries": 10,
            "dialogue_lines": 6,
            "direction_lines": 4,
            "characters_for_tts": 500,
            "speakers": ["adam"],
            "sections": ["act1"],
        }
        assert models.ScriptStats(**raw).model_dump() == raw


class TestParsedScript:
    """Tests for the ParsedScript model."""

    def _make_entry(self, **overrides):
        defaults = {
            "seq": 1, "type": "dialogue", "section": "cold-open",
            "scene": None, "speaker": "adam", "direction": None,
            "text": "Hello.", "direction_type": None,
        }
        defaults.update(overrides)
        return defaults

    def _make_stats(self):
        return {
            "total_entries": 1, "dialogue_lines": 1, "direction_lines": 0,
            "characters_for_tts": 6, "speakers": ["adam"], "sections": ["cold-open"],
        }

    def test_valid_parsed_script(self):
        ps = models.ParsedScript(
            show="THE 413", episode=1, title="Test",
            source_file="test.md",
            entries=[models.ScriptEntry(**self._make_entry())],
            stats=models.ScriptStats(**self._make_stats()),
        )
        assert ps.show == "THE 413"
        assert len(ps.entries) == 1

    def test_accepts_raw_dicts(self):
        """Pydantic should coerce raw dicts into nested models."""
        ps = models.ParsedScript(
            show="THE 413", episode=1, title="Test",
            source_file="test.md",
            entries=[self._make_entry()],
            stats=self._make_stats(),
        )
        assert isinstance(ps.entries[0], models.ScriptEntry)
        assert isinstance(ps.stats, models.ScriptStats)

    def test_model_dump_roundtrip(self):
        raw = {
            "show": "THE 413", "episode": 1, "season": 1, "title": "Test",
            "source_file": "test.md",
            "entries": [self._make_entry()],
            "stats": self._make_stats(),
        }
        assert models.ParsedScript(**raw).model_dump() == raw

    def test_season_field_valid(self):
        ps = models.ParsedScript(
            show="THE 413", episode=1, season=1, title="Test",
            source_file="test.md",
            entries=[self._make_entry()],
            stats=self._make_stats(),
        )
        assert ps.season == 1

    def test_season_can_be_none(self):
        ps = models.ParsedScript(
            show="THE 413", episode=1, title="Test",
            source_file="test.md",
            entries=[self._make_entry()],
            stats=self._make_stats(),
        )
        assert ps.season is None

    def test_season_in_model_dump(self):
        ps = models.ParsedScript(
            show="THE 413", episode=1, season=2, title="Test",
            source_file="test.md",
            entries=[self._make_entry()],
            stats=self._make_stats(),
        )
        assert ps.model_dump()["season"] == 2


# ---------------------------------------------------------------------------
# Phase 2 — Cast / Production Models
# ---------------------------------------------------------------------------


class TestCastMember:
    """Tests for the CastMember model."""

    def _make(self, **overrides):
        defaults = {
            "full_name": "Adam Santos",
            "voice_id": "onwK4e9ZLuTAKqWW03F9",
            "pan": 0.0,
            "filter": False,
            "role": "Host/Narrator",
        }
        defaults.update(overrides)
        return models.CastMember(**defaults)

    def test_valid_cast_member(self):
        cm = self._make()
        assert cm.full_name == "Adam Santos"
        assert cm.pan == 0.0

    def test_pan_range_validated(self):
        self._make(pan=-1.0)  # boundary OK
        self._make(pan=1.0)   # boundary OK
        with pytest.raises(ValidationError):
            self._make(pan=1.5)
        with pytest.raises(ValidationError):
            self._make(pan=-1.5)

    def test_voice_id_non_empty(self):
        with pytest.raises(ValidationError):
            self._make(voice_id="")

    def test_voice_id_tbd_accepted(self):
        cm = self._make(voice_id="TBD")
        assert cm.voice_id == "TBD"

    def test_model_dump_roundtrip(self):
        raw = {
            "full_name": "Dez Williams",
            "voice_id": "JBFqnCBsd6RMkjVDRZzb",
            "pan": -0.15,
            "filter": False,
            "role": "Supporting",
        }
        assert models.CastMember(**raw).model_dump() == raw


class TestCastConfiguration:
    """Tests for the CastConfiguration model."""

    def _make_cast(self):
        return {
            "adam": {
                "full_name": "Adam Santos",
                "voice_id": "onwK4e9ZLuTAKqWW03F9",
                "pan": 0.0,
                "filter": False,
                "role": "Host/Narrator",
            },
        }

    def test_valid_cast_config(self):
        cc = models.CastConfiguration(
            show="THE 413", episode=1, title="Test",
            cast=self._make_cast(),
        )
        assert cc.show == "THE 413"
        assert "adam" in cc.cast

    def test_accepts_raw_dicts_for_cast_members(self):
        cc = models.CastConfiguration(
            show="THE 413", episode=1, title="Test",
            cast=self._make_cast(),
        )
        assert isinstance(cc.cast["adam"], models.CastMember)

    def test_model_dump_roundtrip(self):
        raw = {
            "show": "THE 413", "episode": 1, "season": None, "title": "Test",
            "cast": self._make_cast(),
        }
        assert models.CastConfiguration(**raw).model_dump() == raw

    def test_season_optional_in_cast_config(self):
        """Existing cast files without season still validate."""
        cc = models.CastConfiguration(
            show="THE 413", episode=1, title="Test",
            cast=self._make_cast(),
        )
        assert cc.season is None

    def test_season_captured_in_cast_config(self):
        cc = models.CastConfiguration(
            show="THE 413", episode=1, season=1, title="Test",
            cast=self._make_cast(),
        )
        assert cc.season == 1


class TestVoiceConfig:
    """Tests for the VoiceConfig model (simplified cast for production)."""

    def _make(self, **overrides):
        defaults = {"id": "onwK4e9ZLuTAKqWW03F9", "pan": 0.0, "filter": False}
        defaults.update(overrides)
        return models.VoiceConfig(**defaults)

    def test_valid_voice_config(self):
        vc = self._make()
        assert vc.id == "onwK4e9ZLuTAKqWW03F9"

    def test_pan_range_validated(self):
        self._make(pan=-1.0)
        self._make(pan=1.0)
        with pytest.raises(ValidationError):
            self._make(pan=2.0)

    def test_model_dump_uses_id_not_voice_id(self):
        d = self._make().model_dump()
        assert "id" in d
        assert "voice_id" not in d


class TestDialogueEntry:
    """Tests for the DialogueEntry model."""

    def _make(self, **overrides):
        defaults = {
            "speaker": "adam",
            "text": "Hello world.",
            "stem_name": "003_cold-open_adam",
            "seq": 3,
            "direction": None,
        }
        defaults.update(overrides)
        return models.DialogueEntry(**defaults)

    def test_valid_dialogue_entry(self):
        de = self._make()
        assert de.speaker == "adam"
        assert de.stem_name == "003_cold-open_adam"

    def test_seq_must_be_positive(self):
        with pytest.raises(ValidationError):
            self._make(seq=0)

    def test_model_dump_roundtrip(self):
        raw = {
            "speaker": "dez",
            "text": "What's up?",
            "stem_name": "005_act1_dez",
            "seq": 5,
            "direction": "excited",
        }
        assert models.DialogueEntry(**raw).model_dump() == raw
