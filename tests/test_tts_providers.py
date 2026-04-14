# SPDX-FileCopyrightText: 2025 John Brissette <xilcmd@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the pluggable TTS provider interface and concrete implementations."""

import os
import unittest.mock

import pytest

from xil_pipeline.tts_providers import (
    ChatterboxProvider,
    ElevenLabsProvider,
    GttsProvider,
    TTSProvider,
)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Verify each concrete provider satisfies the TTSProvider protocol."""

    def test_elevenlabs_is_tts_provider(self):
        prov = ElevenLabsProvider(api_key="fake")
        assert isinstance(prov, TTSProvider)

    def test_gtts_is_tts_provider(self):
        prov = GttsProvider()
        assert isinstance(prov, TTSProvider)

    def test_chatterbox_is_tts_provider(self):
        prov = ChatterboxProvider(python_path="/usr/bin/python3")
        assert isinstance(prov, TTSProvider)


# ---------------------------------------------------------------------------
# ElevenLabsProvider
# ---------------------------------------------------------------------------


class TestElevenLabsProvider:
    def _make_provider(self):
        prov = ElevenLabsProvider(api_key="test_key")
        prov._client = unittest.mock.MagicMock()
        sub = unittest.mock.MagicMock()
        sub.character_count = 0
        sub.character_limit = 100000
        sub.tier = "free"
        user = unittest.mock.MagicMock()
        user.subscription = sub
        prov.client.user.get.return_value = user
        return prov

    def test_name(self):
        assert ElevenLabsProvider(api_key="k").name == "ElevenLabs"

    def test_requires_voice_id(self):
        assert ElevenLabsProvider(api_key="k").requires_voice_id is True

    def test_lazy_client_creation(self):
        prov = ElevenLabsProvider(api_key="k")
        assert prov._client is None

    def test_generate_requires_voice_id(self, tmp_path):
        prov = self._make_provider()
        with pytest.raises(ValueError, match="requires a voice_id"):
            prov.generate("Hello", str(tmp_path / "out.mp3"))

    def test_generate_writes_file(self, tmp_path):
        prov = self._make_provider()
        fake_audio = b"\xff\xfb\x10\x00" * 100
        prov.client.text_to_speech.convert.return_value = [fake_audio]
        out = str(tmp_path / "out.mp3")
        prov.generate("Hello world", out, voice_id="v123")
        assert os.path.exists(out)
        with open(out, "rb") as f:
            assert f.read() == fake_audio

    def test_generate_passes_voice_settings(self, tmp_path):
        prov = self._make_provider()
        prov.client.text_to_speech.convert.return_value = [b"\xff\xfb"]
        out = str(tmp_path / "out.mp3")
        prov.generate("Hi", out, voice_id="v1",
                      voice_settings={"stability": 0.7, "similarity_boost": 0.8})
        call_kwargs = prov.client.text_to_speech.convert.call_args.kwargs
        vs = call_kwargs["voice_settings"]
        assert vs.stability == 0.7
        assert vs.similarity_boost == 0.8

    def test_generate_passes_speed(self, tmp_path):
        prov = self._make_provider()
        prov.client.text_to_speech.convert.return_value = [b"\xff\xfb"]
        out = str(tmp_path / "out.mp3")
        prov.generate("Hi", out, voice_id="v1", speed=0.85)
        call_kwargs = prov.client.text_to_speech.convert.call_args.kwargs
        vs = call_kwargs["voice_settings"]
        assert vs.speed == 0.85

    def test_check_quota_returns_remaining(self):
        prov = self._make_provider()
        sub = unittest.mock.MagicMock()
        sub.character_count = 2000
        sub.character_limit = 10000
        sub.tier = "free"
        user = unittest.mock.MagicMock()
        user.subscription = sub
        prov.client.user.get.return_value = user
        assert prov.check_quota() == 8000

    def test_get_model_returns_v3(self):
        prov = self._make_provider()
        sub = unittest.mock.MagicMock()
        sub.character_count = 0
        sub.character_limit = 100000
        user = unittest.mock.MagicMock()
        user.subscription = sub
        prov.client.user.get.return_value = user
        assert prov.get_model() == "eleven_v3"

    def test_close_is_noop(self):
        prov = self._make_provider()
        prov.close()


# ---------------------------------------------------------------------------
# GttsProvider
# ---------------------------------------------------------------------------


class TestGttsProvider:
    def test_name(self):
        assert GttsProvider().name == "gTTS"

    def test_requires_voice_id_false(self):
        assert GttsProvider().requires_voice_id is False

    def test_check_quota_none(self):
        assert GttsProvider().check_quota() is None

    def test_has_enough_quota_always_true(self):
        assert GttsProvider().has_enough_quota("any") is True

    def test_get_model(self):
        assert GttsProvider().get_model() == "gtts"

    def test_generate_strips_tags_and_writes(self, tmp_path):
        prov = GttsProvider()
        out = str(tmp_path / "out.mp3")
        with unittest.mock.patch("xil_pipeline.tts_providers.GttsProvider.generate") as mock_gen:
            mock_gen.side_effect = lambda text, out_path, **kw: open(out_path, "wb").write(b"audio")
            prov.generate("[pause] Hello world", out)
            mock_gen.assert_called_once()

    def test_generate_skips_empty_after_strip(self, tmp_path):
        """If text is only tags, gTTS should produce nothing."""
        prov = GttsProvider()
        out = str(tmp_path / "out.mp3")
        prov.generate("[sighs]", out)
        # gTTS strips [sighs] → empty → returns early
        assert not os.path.exists(out)

    def test_close_is_noop(self):
        GttsProvider().close()


# ---------------------------------------------------------------------------
# ChatterboxProvider
# ---------------------------------------------------------------------------


class TestChatterboxProvider:
    def test_name(self):
        assert ChatterboxProvider(python_path="/usr/bin/python3").name == "Chatterbox"

    def test_requires_voice_id_false(self):
        assert ChatterboxProvider(python_path="/usr/bin/python3").requires_voice_id is False

    def test_check_quota_none(self):
        assert ChatterboxProvider(python_path="/usr/bin/python3").check_quota() is None

    def test_has_enough_quota_always_true(self):
        assert ChatterboxProvider(python_path="/usr/bin/python3").has_enough_quota("any") is True

    def test_get_model(self):
        assert ChatterboxProvider(python_path="/usr/bin/python3").get_model() == "chatterbox"

    def test_close_when_no_proc(self):
        prov = ChatterboxProvider(python_path="/usr/bin/python3")
        prov.close()

    def test_ref_for_wav(self, tmp_path):
        refs = tmp_path / "voice_refs"
        refs.mkdir()
        (refs / "adam.wav").write_bytes(b"wav_data")
        prov = ChatterboxProvider(python_path="/usr/bin/python3",
                                  voice_refs_dir=str(refs))
        assert prov._ref_for("adam").endswith("adam.wav")

    def test_ref_for_mp3(self, tmp_path):
        refs = tmp_path / "voice_refs"
        refs.mkdir()
        (refs / "adam.mp3").write_bytes(b"mp3_data")
        prov = ChatterboxProvider(python_path="/usr/bin/python3",
                                  voice_refs_dir=str(refs))
        assert prov._ref_for("adam").endswith("adam.mp3")

    def test_ref_for_missing(self, tmp_path):
        refs = tmp_path / "voice_refs"
        refs.mkdir()
        prov = ChatterboxProvider(python_path="/usr/bin/python3",
                                  voice_refs_dir=str(refs))
        assert prov._ref_for("unknown") is None
