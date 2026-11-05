import logging
import io
from typing import Optional
from config.settings import settings

logger = logging.getLogger(__name__)


class STTService:
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY

    async def transcribe_audio_bytes(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
        """Транскрибирует аудиосообщение Telegram (OGG/Opus) в текст через Whisper API."""
        if not settings.has_openai_credentials:
            logger.warning("No OpenAI API key provided. Using fallback STT mock.")
            return "Сегодня проложили медь 6-ку 15 м и 9-ку 15 м, изоляцию на них столько же, кабель 3х2,5 — 56 м, поставили 10 хомутов под фреон"

        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=settings.OPENAI_BASE_URL
        )

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        try:
            transcript = await client.audio.transcriptions.create(
                model=settings.WHISPER_MODEL,
                file=audio_file,
                language="ru",
                prompt="Строительный отчет прораба: фреонопроводы, медь 6-ка, 9-ка, изоляция, кабель 3х2,5, хомуты, дренаж."
            )
            return transcript.text.strip()
        except Exception as e:
            logger.error(f"Whisper STT failed: {e}", exc_info=True)
            raise RuntimeError(f"Не удалось распознать голосовое сообщение: {e}")


stt_service = STTService()
