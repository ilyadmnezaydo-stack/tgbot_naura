"""
Speech-to-text service for Telegram voice and audio messages.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests
from telegram import Bot, Message

from src.config import settings

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover - optional dependency
    WhisperModel = None

logger = logging.getLogger(__name__)


class SpeechToTextError(Exception):
    """Base error for speech transcription failures."""


class SpeechToTextUnavailable(SpeechToTextError):
    """Raised when the speech-to-text backend cannot be reached or used."""


class UnsupportedSpeechMessage(SpeechToTextError):
    """Raised when a Telegram message does not contain supported audio media."""


class SpeechFileTooLarge(SpeechToTextError):
    """Raised when an audio file exceeds the configured upload limit."""

    def __init__(self, max_file_mb: int):
        self.max_file_mb = max_file_mb
        super().__init__(f"Audio file exceeds {max_file_mb} MB limit")


class EmptyTranscription(SpeechToTextError):
    """Raised when the backend returns an empty transcript."""


@dataclass(slots=True)
class SpeechTranscription:
    """Normalized transcript returned to the bot flow."""

    text: str
    source: str
    duration_seconds: int | None = None


@dataclass(slots=True)
class _SpeechAttachment:
    """Telegram audio attachment metadata."""

    file_id: str
    source: str
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    duration_seconds: int | None = None


class SpeechToTextService:
    """Transcribe Telegram voice notes and audio files through an OpenAI-compatible API."""

    def __init__(self) -> None:
        remote_base_url = settings.TRANSCRIPTION_BASE_URL or settings.LLM_BASE_URL
        self.base_url = remote_base_url.rstrip("/") if settings.TRANSCRIPTION_REMOTE_ENABLED and remote_base_url else ""
        self.api_key = settings.TRANSCRIPTION_API_KEY or settings.LLM_API_KEY
        self.model = settings.TRANSCRIPTION_MODEL
        self.language = settings.TRANSCRIPTION_LANGUAGE.strip() or None
        self.timeout_seconds = settings.TRANSCRIPTION_TIMEOUT_SECONDS
        self.max_file_bytes = settings.TRANSCRIPTION_MAX_FILE_MB * 1024 * 1024
        self.local_fallback_enabled = settings.TRANSCRIPTION_LOCAL_FALLBACK_ENABLED
        self.local_model = settings.TRANSCRIPTION_LOCAL_MODEL
        self.local_device = settings.TRANSCRIPTION_LOCAL_DEVICE
        self.local_compute_type = settings.TRANSCRIPTION_LOCAL_COMPUTE_TYPE
        self.local_cpu_threads = settings.TRANSCRIPTION_LOCAL_CPU_THREADS

    @staticmethod
    def _extract_attachment(message: Message) -> _SpeechAttachment:
        """Pick the Telegram media object that can be transcribed."""
        if message.voice:
            voice = message.voice
            return _SpeechAttachment(
                file_id=voice.file_id,
                source="voice",
                file_name="voice.ogg",
                mime_type=voice.mime_type or "audio/ogg",
                file_size=voice.file_size,
                duration_seconds=voice.duration,
            )

        if message.audio:
            audio = message.audio
            return _SpeechAttachment(
                file_id=audio.file_id,
                source="audio",
                file_name=audio.file_name,
                mime_type=audio.mime_type,
                file_size=audio.file_size,
                duration_seconds=audio.duration,
            )

        raise UnsupportedSpeechMessage("Message does not contain a voice note or audio file")

    @staticmethod
    def _guess_suffix(attachment: _SpeechAttachment) -> str:
        """Infer a useful filename suffix for the downloaded audio."""
        file_name = attachment.file_name or ""
        suffix = Path(file_name).suffix
        if suffix:
            return suffix

        guessed = mimetypes.guess_extension(attachment.mime_type or "")
        return guessed or ".ogg"

    @staticmethod
    def _normalize_transcript(text: str | None) -> str:
        """Collapse noisy whitespace returned by some backends."""
        if not text:
            return ""
        return " ".join(text.split()).strip()

    @staticmethod
    @lru_cache(maxsize=4)
    def _get_local_model(
        model_name: str,
        device: str,
        compute_type: str,
        cpu_threads: int,
    ):
        """Load and cache one local faster-whisper model."""
        if WhisperModel is None:
            raise SpeechToTextUnavailable("Local faster-whisper dependency is not installed")

        kwargs = {
            "device": device,
            "compute_type": compute_type,
        }
        if cpu_threads > 0:
            kwargs["cpu_threads"] = cpu_threads

        return WhisperModel(model_name, **kwargs)

    async def transcribe_message(self, bot: Bot, message: Message) -> SpeechTranscription:
        """Download a Telegram media file, transcribe it, and clean up the temp file."""
        if not self.base_url and not self.local_fallback_enabled:
            raise SpeechToTextUnavailable("Speech-to-text settings are incomplete")

        attachment = self._extract_attachment(message)
        if attachment.file_size and attachment.file_size > self.max_file_bytes:
            raise SpeechFileTooLarge(settings.TRANSCRIPTION_MAX_FILE_MB)

        telegram_file = await bot.get_file(attachment.file_id)
        with NamedTemporaryFile(delete=False, suffix=self._guess_suffix(attachment)) as temp_file:
            temp_path = Path(temp_file.name)

        try:
            await telegram_file.download_to_drive(custom_path=temp_path)
            try:
                if self.base_url:
                    raw_text = await asyncio.to_thread(
                        self._transcribe_file_remote,
                        temp_path,
                        attachment,
                    )
                elif self.local_fallback_enabled:
                    raw_text = await asyncio.to_thread(self._transcribe_file_local, temp_path)
                else:
                    raise SpeechToTextUnavailable("Speech-to-text settings are incomplete")
            except SpeechToTextUnavailable:
                if not self.local_fallback_enabled:
                    raise
                raw_text = await asyncio.to_thread(self._transcribe_file_local, temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

        transcript = self._normalize_transcript(raw_text)
        if not transcript:
            raise EmptyTranscription("Transcription returned no text")

        return SpeechTranscription(
            text=transcript,
            source=attachment.source,
            duration_seconds=attachment.duration_seconds,
        )

    def _transcribe_file_remote(self, file_path: Path, attachment: _SpeechAttachment) -> str:
        """Send one multipart transcription request with short retries."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = {
            "model": self.model,
            "temperature": "0",
        }
        if self.language:
            data["language"] = self.language

        last_error: Exception | None = None

        for attempt in range(3):
            try:
                with file_path.open("rb") as file_obj:
                    response = requests.post(
                        f"{self.base_url}/audio/transcriptions",
                        headers=headers,
                        data=data,
                        files={
                            "file": (
                                attachment.file_name or file_path.name,
                                file_obj,
                                attachment.mime_type or "application/octet-stream",
                            )
                        },
                        timeout=self.timeout_seconds,
                    )

                if response.status_code == 503 and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue

                if response.status_code in {404, 405}:
                    raise SpeechToTextUnavailable("Transcription endpoint is unavailable")

                response.raise_for_status()

                if "application/json" in response.headers.get("content-type", "").lower():
                    try:
                        payload = response.json()
                    except ValueError:
                        payload = None
                    if isinstance(payload, dict):
                        text = payload.get("text") or payload.get("transcript") or payload.get("output_text")
                        if isinstance(text, str):
                            return text

                return response.text.strip()
            except SpeechToTextUnavailable:
                raise
            except requests.RequestException as exc:
                last_error = exc
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code == 503 and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                if status_code in {404, 405}:
                    raise SpeechToTextUnavailable("Transcription endpoint is unavailable") from exc
                if status_code is None and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                break

        logger.warning("Speech transcription request failed: %s", last_error)
        raise SpeechToTextUnavailable("Could not reach the speech-to-text backend") from last_error

    def _transcribe_file_local(self, file_path: Path) -> str:
        """Transcribe audio locally with faster-whisper."""
        try:
            model = self._get_local_model(
                self.local_model,
                self.local_device,
                self.local_compute_type,
                self.local_cpu_threads,
            )
            segments, _ = model.transcribe(
                str(file_path),
                language=self.language,
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            return " ".join(segment.text.strip() for segment in segments if segment.text).strip()
        except SpeechToTextUnavailable:
            raise
        except Exception as exc:
            logger.warning("Local speech transcription failed: %s", exc)
            raise SpeechToTextUnavailable("Local faster-whisper transcription failed") from exc
