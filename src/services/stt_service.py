import logging
import io
from config.settings import settings

logger = logging.getLogger(__name__)


class STTService:
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY

    async def transcribe_audio_bytes(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
        """
        Транскрибирует аудиосообщение Telegram (OGG/Opus) в текст:
        1. Если указан GROQ_API_KEY -> использует 100% бесплатный Whisper-Large-v3-Turbo от Groq.
        2. Если указан OPENAI_API_KEY -> использует OpenAI Whisper API.
        3. Если ключей нет -> возвращает тестовый пример.
        """
        from openai import AsyncOpenAI

        if settings.GROQ_API_KEY:
            client = AsyncOpenAI(
                api_key=settings.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1"
            )
            try:
                transcript = await client.audio.transcriptions.create(
                    model="whisper-large-v3-turbo",
                    file=(filename, audio_bytes),
                    language="ru",
                    prompt="Строительный отчет прораба: фреонопроводы, медь 6-ка, 9-ка, изоляция, кабель 3х2,5, хомуты, дренаж."
                )
                text = transcript.text.strip()
                if not text:
                    raise RuntimeError("Аудио пустое или слова не удалось расслышать.")
                return text
            except Exception as e:
                logger.error(f"Groq Whisper failed: {e}", exc_info=True)
                raise RuntimeError(f"Ошибка распознавания через Groq Whisper: {e}")

        if settings.has_openai_credentials:
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

        logger.warning("No STT API key provided. Using fallback STT mock.")
        return "Сегодня проложили медь 6-ку 15 м и 9-ку 15 м, изоляцию на них столько же, кабель 3х2,5 — 56 м, поставили 10 хомутов под фреон"


stt_service = STTService()
