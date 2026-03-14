"""Tests for collect_stem_plans() stale-stem detection in mix_common.py."""

import importlib.util
import os

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

# ─── Import mix_common ───

_mix_common_path = os.path.join(os.path.dirname(__file__), "..", "mix_common.py")
spec = importlib.util.spec_from_file_location("mix_common", _mix_common_path)
mix_common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mix_common)

collect_stem_plans = mix_common.collect_stem_plans
collect_preamble_plans = mix_common.collect_preamble_plans


# ─── Helpers ───

def _write_mp3(path: str, duration_ms: int = 100) -> None:
    Sine(440).to_audio_segment(duration=duration_ms).export(path, format="mp3")


# ─── Tests ───

class TestCollectStemPlans:
    def test_sfx_stem_matching_dialogue_entry_is_skipped(self, tmp_path, capsys):
        """A `_sfx.mp3` stem whose seq maps to a dialogue entry must be skipped."""
        stem = tmp_path / "005_act-one_sfx.mp3"
        _write_mp3(str(stem))
        index = {5: {"seq": 5, "type": "dialogue", "direction_type": None, "text": "Hello"}}

        plans = collect_stem_plans(str(tmp_path), index)

        assert plans == []
        captured = capsys.readouterr()
        assert "[W]" in captured.out
        assert "005_act-one_sfx.mp3" in captured.out
        assert "dialogue" in captured.out

    def test_dialogue_stem_matching_direction_entry_is_skipped(self, tmp_path, capsys):
        """A speaker-named stem whose seq maps to a direction entry must be skipped."""
        stem = tmp_path / "005_act-one_adam.mp3"
        _write_mp3(str(stem))
        index = {5: {"seq": 5, "type": "direction", "direction_type": "SFX", "text": "SFX: BANG"}}

        plans = collect_stem_plans(str(tmp_path), index)

        assert plans == []
        captured = capsys.readouterr()
        assert "[W]" in captured.out
        assert "005_act-one_adam.mp3" in captured.out
        assert "direction" in captured.out

    def test_valid_dialogue_stem_is_kept(self, tmp_path):
        """A speaker-named stem whose seq maps to a dialogue entry must be kept."""
        stem = tmp_path / "005_act-one_adam.mp3"
        _write_mp3(str(stem))
        index = {5: {"seq": 5, "type": "dialogue", "direction_type": None, "text": "Hello"}}

        plans = collect_stem_plans(str(tmp_path), index)

        assert len(plans) == 1
        assert plans[0].seq == 5
        assert plans[0].entry_type == "dialogue"

    def test_valid_sfx_stem_is_kept(self, tmp_path):
        """A `_sfx.mp3` stem whose seq maps to a direction entry must be kept."""
        stem = tmp_path / "005_act-one_sfx.mp3"
        _write_mp3(str(stem))
        index = {5: {"seq": 5, "type": "direction", "direction_type": "SFX", "text": "SFX: BANG"}}

        plans = collect_stem_plans(str(tmp_path), index)

        assert len(plans) == 1
        assert plans[0].seq == 5
        assert plans[0].direction_type == "SFX"

    def test_unknown_seq_stem_is_kept(self, tmp_path, capsys):
        """A stem whose seq is not in the index must pass through without warnings."""
        stem = tmp_path / "099_act-two_sfx.mp3"
        _write_mp3(str(stem))
        index = {}  # seq 99 not present

        plans = collect_stem_plans(str(tmp_path), index)

        assert len(plans) == 1
        assert plans[0].seq == 99
        assert plans[0].entry_type is None
        captured = capsys.readouterr()
        assert "[W]" not in captured.out

    def test_preamble_files_are_silently_skipped(self, tmp_path, capsys):
        """preamble_tina.mp3 and preamble_music.mp3 have no numeric prefix and must be skipped."""
        _write_mp3(str(tmp_path / "preamble_tina.mp3"))
        _write_mp3(str(tmp_path / "preamble_music.mp3"))
        index = {}

        plans = collect_stem_plans(str(tmp_path), index)

        assert plans == []
        captured = capsys.readouterr()
        assert "[W]" not in captured.out


class TestCollectPreamblePlans:
    def test_both_files_present(self, tmp_path):
        """Both preamble stems present → two plans at seq -2 and -1."""
        _write_mp3(str(tmp_path / "preamble_tina.mp3"))
        _write_mp3(str(tmp_path / "preamble_music.mp3"))

        plans = collect_preamble_plans(None, str(tmp_path))

        assert len(plans) == 2
        voice = next(p for p in plans if p.seq == -2)
        music = next(p for p in plans if p.seq == -1)
        assert voice.entry_type == "dialogue"
        assert voice.direction_type is None
        assert music.entry_type == "direction"
        assert music.direction_type == "MUSIC"
        assert music.text == "INTRO MUSIC"

    def test_music_stem_is_foreground(self, tmp_path):
        """preamble_music.mp3 must be foreground (sequential), not a background overlay."""
        _write_mp3(str(tmp_path / "preamble_music.mp3"))

        plans = collect_preamble_plans(None, str(tmp_path))
        music = plans[0]

        assert music.foreground_override is True
        assert music.is_background is False

    def test_voice_stem_is_foreground(self, tmp_path):
        """preamble_tina.mp3 must be foreground (no special override needed)."""
        _write_mp3(str(tmp_path / "preamble_tina.mp3"))

        plans = collect_preamble_plans(None, str(tmp_path))
        voice = plans[0]

        assert voice.is_background is False

    def test_only_voice_present(self, tmp_path):
        """Only preamble_tina.mp3 → one plan at seq -2."""
        _write_mp3(str(tmp_path / "preamble_tina.mp3"))

        plans = collect_preamble_plans(None, str(tmp_path))

        assert len(plans) == 1
        assert plans[0].seq == -2

    def test_only_music_present(self, tmp_path):
        """Only preamble_music.mp3 → one plan at seq -1."""
        _write_mp3(str(tmp_path / "preamble_music.mp3"))

        plans = collect_preamble_plans(None, str(tmp_path))

        assert len(plans) == 1
        assert plans[0].seq == -1

    def test_no_files_returns_empty(self, tmp_path):
        """No preamble files → empty list."""
        plans = collect_preamble_plans(None, str(tmp_path))
        assert plans == []

    def test_voice_plan_uses_preamble_text(self, tmp_path):
        """When preamble_cfg is provided, voice plan text comes from cfg.text."""
        _write_mp3(str(tmp_path / "preamble_tina.mp3"))

        class FakePreamble:
            text = "Hello, listeners."

        plans = collect_preamble_plans(FakePreamble(), str(tmp_path))
        assert plans[0].text == "Hello, listeners."

    def test_negative_seqs_sort_before_positive(self, tmp_path):
        """Preamble seqs -2 and -1 sort before any parsed entry seq ≥ 1."""
        _write_mp3(str(tmp_path / "preamble_tina.mp3"))
        _write_mp3(str(tmp_path / "preamble_music.mp3"))
        _write_mp3(str(tmp_path / "001_cold-open_adam.mp3"))

        index = {1: {"seq": 1, "type": "dialogue", "direction_type": None, "text": "Hi"}}
        parsed_plans = collect_stem_plans(str(tmp_path), index)
        preamble = collect_preamble_plans(None, str(tmp_path))
        all_plans = sorted(preamble + parsed_plans, key=lambda p: p.seq)

        assert all_plans[0].seq == -2
        assert all_plans[1].seq == -1
        assert all_plans[2].seq == 1
