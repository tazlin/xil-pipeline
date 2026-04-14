# SPDX-FileCopyrightText: 2025 John Brissette <xilcmd@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pluggable TTS provider interface and concrete implementations.

Defines a :class:`TTSProvider` :pep:`544` Protocol and three concrete
backends — ElevenLabs (paid API), gTTS (free draft), and Chatterbox
(local GPU).  The producer passes a single provider instance through the
generation pipeline instead of branching on backend name strings.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Any, Protocol, runtime_checkable

from xil_pipeline.log_config import get_logger

logger = get_logger(__name__)

TAG_RE = re.compile(r"\[[^\]]*\]")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class TTSProvider(Protocol):
    """Contract for a text-to-speech backend.

    Every provider must be able to turn a text string into an MP3 file on
    disk.  Quota / voice-ID semantics vary by backend; callers inspect
    :pyattr:`requires_voice_id` and call :pymeth:`has_enough_quota` to
    adapt pre-flight checks without knowing which backend is active.
    """

    @property
    def name(self) -> str:
        """Human-readable provider name for log messages."""
        ...

    @property
    def requires_voice_id(self) -> bool:
        """Whether the provider needs a per-speaker ``voice_id``."""
        ...

    def generate(
        self,
        text: str,
        out_path: str,
        *,
        voice_id: str | None = None,
        speaker_key: str | None = None,
        speed: float | None = None,
        voice_settings: dict[str, Any] | None = None,
        previous_text: str | None = None,
        next_text: str | None = None,
        language_code: str | None = None,
    ) -> None:
        """Synthesise *text* and write an MP3 to *out_path*.

        Provider-specific parameters (``voice_settings``, ``previous_text``,
        etc.) are silently ignored by backends that do not support them.
        """
        ...

    def check_quota(self) -> int | None:
        """Return remaining character quota, or ``None`` if not applicable."""
        ...

    def has_enough_quota(self, text: str) -> bool:
        """Return whether the provider can synthesise *text* right now."""
        ...

    def get_model(self) -> str:
        """Return the model identifier the provider will use for the next call."""
        ...

    def close(self) -> None:
        """Release any held resources (subprocess, network connection, …)."""
        ...


# ---------------------------------------------------------------------------
# ElevenLabs
# ---------------------------------------------------------------------------


class ElevenLabsProvider:
    """ElevenLabs TTS API backend.

    The SDK client is created lazily on first use so importing this module
    does not require an API key.

    Exposes :pyattr:`client` so callers that need the raw SDK (e.g. SFX
    generation via ``client.text_to_sound_effects``) can access it.
    """

    _SSML_TAG_RE = re.compile(
        r"<(?:break|emphasis|prosody|say-as|phoneme|sub|speak|p|s)\b",
        re.IGNORECASE,
    )
    _SAFE_THRESHOLD = 5000

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        self._client: Any | None = None

    # -- lazy client ---------------------------------------------------

    @property
    def client(self) -> Any:
        """Return the :class:`elevenlabs.client.ElevenLabs` instance, creating it on first access."""
        if self._client is None:
            from elevenlabs.client import ElevenLabs

            self._client = ElevenLabs(api_key=self._api_key)
        return self._client

    # -- protocol ------------------------------------------------------

    @property
    def name(self) -> str:
        return "ElevenLabs"

    @property
    def requires_voice_id(self) -> bool:
        return True

    def generate(
        self,
        text: str,
        out_path: str,
        *,
        voice_id: str | None = None,
        speaker_key: str | None = None,
        speed: float | None = None,
        voice_settings: dict[str, Any] | None = None,
        previous_text: str | None = None,
        next_text: str | None = None,
        language_code: str | None = None,
    ) -> None:
        from elevenlabs import VoiceSettings

        if not voice_id:
            raise ValueError("ElevenLabsProvider.generate() requires a voice_id")

        model = self._select_model(text)
        logger.info(
            "   > TTS (%d chars) → %s [%s]",
            len(text),
            os.path.basename(out_path),
            model,
        )

        # Build VoiceSettings from dict + speed override
        vs: VoiceSettings | None = None
        if voice_settings or speed is not None:
            fields: dict[str, Any] = dict(voice_settings) if voice_settings else {}
            if speed is not None:
                fields["speed"] = speed
            vs = VoiceSettings(**fields)

        extra_kwargs: dict[str, Any] = {}
        if language_code and model != "eleven_v3":
            extra_kwargs["language_code"] = language_code
        if previous_text and model != "eleven_v3":
            extra_kwargs["previous_text"] = previous_text
        if next_text and model != "eleven_v3":
            extra_kwargs["next_text"] = next_text

        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(out_path) or ".",
            suffix=".tmp",
        )
        os.close(tmp_fd)
        try:
            audio_stream = self.client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id=model,
                output_format="mp3_44100_128",
                voice_settings=vs,
                **extra_kwargs,
            )
            with open(tmp_path, "wb") as f:
                for chunk in audio_stream:
                    if chunk:
                        f.write(chunk)
            os.replace(tmp_path, out_path)
            tmp_path = None
        finally:
            if tmp_path is not None:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(tmp_path)

    def check_quota(self) -> int | None:
        from elevenlabs.core.api_error import ApiError

        try:
            user_info = self.client.user.get()
            sub = user_info.subscription
            used = sub.character_count
            limit = sub.character_limit
            remaining = limit - used

            logger.info("\n" + "=" * 40)
            logger.info("ELEVENLABS API STATUS:")
            logger.info("  Tier:      %s", sub.tier.upper())
            logger.info("  Usage:     %s / %s characters", f"{used:,}", f"{limit:,}")
            logger.info("  Remaining: %s", f"{remaining:,}")
            logger.info("=" * 40 + "\n")
            return remaining
        except ApiError as e:
            logger.warning("API Error: Unable to fetch user subscription data.")
            logger.warning("    Details: %s", e)
            return None

    def has_enough_quota(self, text: str) -> bool:
        from elevenlabs.core.api_error import ApiError

        try:
            user_info = self.client.user.get()
            remaining = user_info.subscription.character_limit - user_info.subscription.character_count
            required = len(text)
            if remaining >= required:
                logger.info(" [Guard] Quota OK: %d required, %s left.", required, f"{remaining:,}")
                return True
            logger.info(
                " [Guard] STOP: Line requires %d chars, but only %s remain.",
                required,
                f"{remaining:,}",
            )
            return False
        except ApiError:
            logger.warning(" [Guard] Permission 'user_read' missing. Skipping quota check.")
            return True

    def get_model(self) -> str:
        from elevenlabs.core.api_error import ApiError

        try:
            user_info = self.client.user.get()
            remaining = user_info.subscription.character_limit - user_info.subscription.character_count
            if remaining > self._SAFE_THRESHOLD:
                logger.info(
                    " [Budget] Healthy Balance: %s left. Using 'eleven_v3'.",
                    f"{remaining:,}",
                )
            else:
                logger.warning(
                    " [Budget] LOW BALANCE: %s left. Continuing with 'eleven_v3' — "
                    "audio tags like [pause] require v3 and cannot fall back to flash.",
                    f"{remaining:,}",
                )
            return "eleven_v3"
        except ApiError:
            logger.info(" [Budget] API Check Failed. Defaulting to 'eleven_v3'.")
            return "eleven_v3"

    def close(self) -> None:
        pass

    # -- internal ------------------------------------------------------

    def _select_model(self, text: str) -> str:
        if self._SSML_TAG_RE.search(text):
            logger.warning(
                "   [!] SSML tag detected in TTS text — eleven_v3 does not honour SSML. "
                "Replace <break> / <emphasis> etc. with native audio tags like [pause]. "
                "Text: %.60s",
                text,
            )
        return self.get_model()


# ---------------------------------------------------------------------------
# gTTS (Google Translate TTS — free, flat single voice)
# ---------------------------------------------------------------------------


class GttsProvider:
    """Draft-quality TTS via Google Translate TTS.

    Produces a flat single voice regardless of ``voice_id`` / ``speaker_key``.
    Strips ElevenLabs v3 inline audio tags before synthesis.
    """

    def __init__(self) -> None:
        try:
            from gtts import gTTS as _gTTS  # noqa: F401
        except ImportError:
            raise RuntimeError("gTTS not installed. Run: pip install xil-pipeline[tts-alt]") from None

    @property
    def name(self) -> str:
        return "gTTS"

    @property
    def requires_voice_id(self) -> bool:
        return False

    def generate(
        self,
        text: str,
        out_path: str,
        *,
        voice_id: str | None = None,
        speaker_key: str | None = None,
        speed: float | None = None,
        voice_settings: dict[str, Any] | None = None,
        previous_text: str | None = None,
        next_text: str | None = None,
        language_code: str | None = None,
    ) -> None:
        from gtts import gTTS

        cleaned = TAG_RE.sub("", text).strip()
        if not cleaned:
            return

        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(out_path) or ".",
            suffix=".tmp",
        )
        os.close(tmp_fd)
        try:
            logger.info(
                "   > gTTS (%d chars) → %s",
                len(cleaned),
                os.path.basename(out_path),
            )
            gTTS(text=cleaned, lang="en").save(tmp_path)
            os.replace(tmp_path, out_path)
            tmp_path = None
        finally:
            if tmp_path is not None:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(tmp_path)

    def check_quota(self) -> int | None:
        return None

    def has_enough_quota(self, text: str) -> bool:
        return True

    def get_model(self) -> str:
        return "gtts"

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Chatterbox (local GPU TTS with zero-shot voice cloning)
# ---------------------------------------------------------------------------


class ChatterboxProvider:
    """Local Chatterbox TTS with per-character voice cloning.

    Manages a persistent subprocess running :mod:`chatterbox_worker` under a
    separate Python venv.  The worker keeps the model loaded in GPU memory
    across generation calls.

    Args:
        python_path: Path to the chatterbox venv Python executable.
        voice_refs_dir: Directory containing ``<speaker_key>.wav`` clips.
        device: ``"cuda"`` or ``"cpu"``.
        exaggeration: Emotion exaggeration 0.0–1.0.
        cfg_weight: CFG weight controlling pacing/delivery.
    """

    _WORKER = os.path.join(os.path.dirname(__file__), "chatterbox_worker.py")

    def __init__(
        self,
        python_path: str,
        voice_refs_dir: str = "voice_refs",
        device: str = "cuda",
        exaggeration: float = 0.5,
        cfg_weight: float = 0.5,
    ) -> None:
        self._python = python_path
        self._voice_refs_dir = voice_refs_dir
        self._device = device
        self._exaggeration = exaggeration
        self._cfg_weight = cfg_weight
        self._proc: subprocess.Popen | None = None

    # -- protocol ------------------------------------------------------

    @property
    def name(self) -> str:
        return "Chatterbox"

    @property
    def requires_voice_id(self) -> bool:
        return False

    def generate(
        self,
        text: str,
        out_path: str,
        *,
        voice_id: str | None = None,
        speaker_key: str | None = None,
        speed: float | None = None,
        voice_settings: dict[str, Any] | None = None,
        previous_text: str | None = None,
        next_text: str | None = None,
        language_code: str | None = None,
    ) -> None:
        if self._proc is None:
            self._start()

        ref = self._ref_for(speaker_key or "")
        if ref:
            logger.info("   ref: %s", os.path.basename(ref))

        req = {
            "text": text,
            "out_path": out_path,
            "ref_audio": ref,
            "exaggeration": self._exaggeration,
            "cfg_weight": self._cfg_weight,
        }
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("Chatterbox worker process is not running.")

        self._proc.stdin.write(json.dumps(req) + "\n")
        self._proc.stdin.flush()

        raw = self._proc.stdout.readline()
        if not raw:
            raise RuntimeError("Chatterbox worker closed pipe unexpectedly.")
        resp = json.loads(raw)
        if "error" in resp:
            raise RuntimeError(f"Chatterbox: {resp['error']}")

    def check_quota(self) -> int | None:
        return None

    def has_enough_quota(self, text: str) -> bool:
        return True

    def get_model(self) -> str:
        return "chatterbox"

    def close(self) -> None:
        if self._proc is not None:
            with contextlib.suppress(Exception):
                if self._proc.stdin:
                    self._proc.stdin.close()
            with contextlib.suppress(Exception):
                self._proc.wait(timeout=15)
            self._proc = None

    # -- internal ------------------------------------------------------

    def _start(self) -> None:
        logger.info("Starting Chatterbox worker (%s, %s)…", self._python, self._device)
        if not os.path.exists(self._WORKER):
            raise RuntimeError(f"Chatterbox worker script not found: {self._WORKER}")

        self._proc = subprocess.Popen(
            [self._python, self._WORKER, self._device],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
        )

        if self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("Failed to start Chatterbox worker process.")

        while True:
            raw = self._proc.stdout.readline()
            if not raw:
                raise RuntimeError(
                    "Chatterbox worker exited before sending ready signal. "
                    "Check that venv-chatterbox is correctly set up and the model is downloaded."
                )
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("Chatterbox worker startup: %s", raw)
                continue
            if msg.get("ready"):
                break
            logger.debug("Chatterbox worker startup: %s", raw)
        logger.info("Chatterbox worker ready (sample_rate=%d)", msg["sr"])

    def _ref_for(self, speaker_key: str) -> str | None:
        for ext in (".wav", ".mp3"):
            p = os.path.join(self._voice_refs_dir, f"{speaker_key}{ext}")
            if os.path.exists(p):
                return p
        return None
