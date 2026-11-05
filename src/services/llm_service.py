import logging
import json
import re
from typing import List, Optional
from pydantic import BaseModel, Field

from config.settings import settings
from src.core.models import ExtractedItem

logger = logging.getLogger(__name__)


class LLMExtractionResponse(BaseModel):
    is_question: bool = Field(
        default=False,
        description="True, если пользователь задает вопрос (например, 'сколько осталось по кабелю?'), а не сдаёт отчет"
    )
    question_query: Optional[str] = Field(
        default=None,
        description="Ключевые слова позиции для поиска остатка, если это вопрос"
    )
    items: List[ExtractedItem] = Field(
        default_factory=list,
        description="Список распознанных работ и материалов с объемами"
    )


EXTRACTION_SYSTEM_PROMPT = """Ты — ассистент-эксперт по строительным и электромонтажным работам (HVAC / ЭМ).
Твоя задача — извлечь из разговорного отчета мастера выполненные работы, объемы и единицы измерения.

Правила извлечения:
1. Понимай строительный сленг:
   - "медь 6-ка", "шестерка", "6-ку" -> фреонопровод медный Д6,35 (ед. изм: м)
   - "медь 9-ка", "девятка", "9-ку" -> фреонопровод медный Д9,52 (ед. изм: м)
   - "медь 12-ка", "двенашка" -> фреонопровод медный Д12.7 (ед. изм: м)
   - "изоляция на них столько же", "флекс" -> трубка теплоизоляционная К-FLEX соответствующих диаметров (ед. изм: м)
   - "хомуты под фреон" -> хомут для крепления фреонопровода (ед. изм: шт)
   - "хомуты под дренаж" -> хомут для крепления дренажа (ед. изм: шт)
   - "кабель 3 на 2,5" -> кабель 3х2,5 (ед. изм: м)
   - "ПВХ 20" -> труба ПВХ 20 мм (ед. изм: м)
   - "сверление отверстий" / "пробили проходки":
     * если сказано "под фреон" -> context_hint = "под фреон / гильзы фреон"
     * если сказано "под дренаж" -> context_hint = "под дренаж / гильзы дренаж"
     * если назначение не названо -> context_hint = None
2. Разрешай контекстные ссылки и анафоры:
   Если сказано: "медь 6-ку 15 м и 9-ку 15 м, изоляцию на них столько же", 
   ты ОБЯЗАН создать ДВЕ отдельные позиции для изоляции:
   - изоляция на медь 6-ку, объем 15, ед. изм "м", context_hint: "изоляция фреонопровода 6.35"
   - изоляция на медь 9-ку, объем 15, ед. изм "м", context_hint: "изоляция фреонопровода 9.52"
3. Вопросы:
   Если сообщение является вопросом (например, "сколько осталось по кабелю 3х2,5?" или "какой остаток по меди?"),
   установи is_question=True и question_query="кабель 3х2,5". В items ничего не добавляй.
"""


class LLMService:
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY

    async def extract_items(self, user_text: str) -> LLMExtractionResponse:
        """Извлекает сущности из текста мастера с помощью LLM (или fallback-парсера)."""
        if not settings.has_openai_credentials:
            logger.info("Using rule-based fallback extractor (no OpenAI key).")
            return self._rule_based_fallback(user_text)

        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=settings.OPENAI_BASE_URL
        )

        try:
            completion = await client.beta.chat.completions.parse(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_text}
                ],
                response_format=LLMExtractionResponse,
                temperature=0.1
            )
            return completion.choices[0].message.parsed
        except Exception as e:
            logger.error(f"OpenAI extraction failed: {e}. Falling back to rule-based parser.")
            return self._rule_based_fallback(user_text)

    def _rule_based_fallback(self, text: str) -> LLMExtractionResponse:
        """
        Детерминированный офлайн-парсер регулярными выражениями.
        Гарантирует работу тестов и локального запуска без OpenAI API.
        """
        text_lower = text.lower().strip()

        # Проверка на вопрос об остатке
        q_match = re.search(r"сколько\s+осталось\s+по\s+(.+)|какой\s+остаток\s+по\s+(.+)", text_lower)
        if q_match:
            query = q_match.group(1) or q_match.group(2)
            query = query.rstrip('?').strip()
            return LLMExtractionResponse(is_question=True, question_query=query, items=[])

        items: List[ExtractedItem] = []

        # Медь 6-ка
        m6 = re.search(r"(?:медь\s*6(?:-[а-я]+)?|шест[её]рк[а-я]*|6-к[ау])\s*(?:—|-|\s)?\s*(\d+(?:[.,]\d+)?)\s*(м|метр[а-я]*)?", text_lower)
        if m6:
            vol = float(m6.group(1).replace(',', '.'))
            items.append(ExtractedItem(raw_text="медь 6-ка", volume=vol, unit="м", context_hint="фреонопровод 6.35"))

        # Медь 9-ка
        m9 = re.search(r"(?:медь\s*9(?:-[а-я]+)?|девятк[а-я]*|9-к[ау])\s*(?:—|-|\s)?\s*(\d+(?:[.,]\d+)?)\s*(м|метр[а-я]*)?", text_lower)
        if m9:
            vol = float(m9.group(1).replace(',', '.'))
            items.append(ExtractedItem(raw_text="медь 9-ка", volume=vol, unit="м", context_hint="фреонопровод 9.52"))

        # Медь 12-ка
        m12 = re.search(r"(?:медь\s*12(?:-[а-я]+)?|двенашк[а-я]*|12-к[ау])\s*(?:—|-|\s)?\s*(\d+(?:[.,]\d+)?)\s*(м|метр[а-я]*)?", text_lower)
        if m12:
            vol = float(m12.group(1).replace(',', '.'))
            items.append(ExtractedItem(raw_text="медь 12-ка", volume=vol, unit="м", context_hint="фреонопровод 12.7"))

        # Разрешение "изоляцию на них столько же"
        if "изоляци" in text_lower and ("столько же" in text_lower or "на них" in text_lower):
            if m6:
                items.append(ExtractedItem(raw_text="изоляция на медь 6-ку", volume=float(m6.group(1).replace(',', '.')), unit="м", context_hint="теплоизоляция фреонопровода 6.35"))
            if m9:
                items.append(ExtractedItem(raw_text="изоляция на медь 9-ку", volume=float(m9.group(1).replace(',', '.')), unit="м", context_hint="теплоизоляция фреонопровода 9.52"))
            if m12:
                items.append(ExtractedItem(raw_text="изоляция на медь 12-ку", volume=float(m12.group(1).replace(',', '.')), unit="м", context_hint="теплоизоляция фреонопровода 12.7"))

        # Кабели (например, кабель 3х2,5 — 56 м)
        cable_match = re.search(r"кабель\s+(\d+[хx]\d+(?:[.,]\d+)?)\s*(?:—|-|\s)?\s*(\d+(?:[.,]\d+)?)\s*(м|метр[а-я]*)?", text_lower)
        if cable_match:
            sec = cable_match.group(1).replace('x', 'х')
            vol = float(cable_match.group(2).replace(',', '.'))
            items.append(ExtractedItem(raw_text=f"кабель {sec}", volume=vol, unit="м", context_hint=f"кабель силовой {sec}"))

        # Хомуты (например, "поставили 10 хомутов под фреон")
        clam_match = re.search(r"(\d+)\s*хомут[а-я]*\s*(под\s+фреон|под\s+дренаж|фреон|дренаж)?", text_lower)
        if not clam_match:
            clam_match = re.search(r"хомут[а-я]*\s*(под\s+фреон|под\s+дренаж)?\s*(?:—|-|\s)?\s*(\d+)", text_lower)
            if clam_match:
                vol = float(clam_match.group(2))
                hint = clam_match.group(1) or ""
                items.append(ExtractedItem(raw_text=f"хомут {hint}".strip(), volume=vol, unit="шт", context_hint=f"хомут {hint}".strip()))
        else:
            vol = float(clam_match.group(1))
            hint = clam_match.group(2) or ""
            items.append(ExtractedItem(raw_text=f"хомут {hint}".strip(), volume=vol, unit="шт", context_hint=f"хомут {hint}".strip()))

        # Сверление / проходки (например, "просверлили 12 отверстий" или "сверление 4 отверстий под фреон")
        drill_match = re.search(r"(?:просверлили|сверление|отверсти[йя])\s*(\d+)?\s*(?:отверсти[йя])?\s*(под\s+фреон|под\s+дренаж)?", text_lower)
        if drill_match:
            vol_s = drill_match.group(1)
            hint = drill_match.group(2)
            if not vol_s:
                # Попробуем найти число рядом
                v_nearby = re.search(r"(\d+)\s*(?:шт|отверсти)", text_lower)
                if v_nearby:
                    vol_s = v_nearby.group(1)
            if vol_s:
                items.append(ExtractedItem(
                    raw_text="сверление отверстий",
                    volume=float(vol_s),
                    unit="шт",
                    context_hint=hint if hint else None
                ))

        # Труба ПВХ (например "труба пвх 20 50м")
        pvc_match = re.search(r"труб[а-я]*\s*пвх\s*(\d+)\s*(?:—|-|\s)?\s*(\d+(?:[.,]\d+)?)\s*(м|метр[а-я]*)?", text_lower)
        if pvc_match:
            diam = pvc_match.group(1)
            vol = float(pvc_match.group(2).replace(',', '.'))
            items.append(ExtractedItem(raw_text=f"труба пвх {diam}", volume=vol, unit="м", context_hint=f"труба пвх {diam}"))

        return LLMExtractionResponse(is_question=False, items=items)


llm_service = LLMService()
