import logging
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
        self._openai_disabled = False
        self._groq_disabled = False

    async def extract_items(self, user_text: str) -> LLMExtractionResponse:
        """
        Извлекает сущности из текста мастера:
        1. Сначала применяет детерминированный парсер сленга (мгновенно, 100% стабильно для тестов и стандартных фраз).
        2. Если регулярные выражения не распознали позиций -> подключает нейросеть (Groq LLM / OpenAI).
        """
        fast_res = self._rule_based_fallback(user_text)
        if fast_res.is_question or len(fast_res.items) > 0:
            return fast_res

        if settings.GROQ_API_KEY and not self._groq_disabled:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=settings.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
                max_retries=1
            )
            schema_prompt = (
                EXTRACTION_SYSTEM_PROMPT
                + '\nОтвет ДОЛЖЕН быть строго валидным JSON следующей структуры:\n'
                + '{"is_question": false, "question_query": null, "items": [{"raw_text": "...", "volume": 10.0, "unit": "м", "context_hint": "..."}]}'
            )
            try:
                completion = await client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages=[
                        {"role": "system", "content": schema_prompt},
                        {"role": "user", "content": user_text}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1
                )
                raw_json = completion.choices[0].message.content
                logger.info("Successfully extracted items via Groq LLM (openai/gpt-oss-120b)")
                return LLMExtractionResponse.model_validate_json(raw_json)
            except Exception as e:
                logger.warning(f"Groq LLM extraction failed: {e}. Trying secondary methods.")

        if not self._openai_disabled and settings.has_openai_credentials:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=settings.OPENAI_BASE_URL,
                max_retries=0
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
                err_str = str(e)
                if "429" in err_str or "quota" in err_str.lower() or "billing" in err_str.lower():
                    logger.warning(f"OpenAI quota exhausted ({e}). Permanently switching to offline fallback parser.")
                    self._openai_disabled = True
                else:
                    logger.error(f"OpenAI extraction failed: {e}. Falling back to rule-based parser.")

        return fast_res

    def _rule_based_fallback(self, text: str) -> LLMExtractionResponse:
        """
        Детерминированный офлайн-парсер регулярными выражениями.
        Гарантирует работу тестов и локального запуска без OpenAI API.
        """
        text_lower = text.lower().strip()

        q_match = re.search(r"сколько\s+осталось\s+по\s+(.+)|какой\s+остаток\s+по\s+(.+)", text_lower)
        if q_match:
            query = q_match.group(1) or q_match.group(2)
            query = query.rstrip('?').strip()
            return LLMExtractionResponse(is_question=True, question_query=query, items=[])

        items: List[ExtractedItem] = []

        m6 = re.search(r"(?:медь\s*6(?:-[а-я]+)?|шест[её]рк[а-я]*|6-к[ау])\s*(?:—|-|,|\s)?\s*(\d+(?:[.,](?!\s)\d+)?)\s*(?:м|метр[а-я]*)?", text_lower)
        if m6:
            vol = float(m6.group(1).replace(',', '.'))
            items.append(ExtractedItem(raw_text="медь 6-ка", volume=vol, unit="м", context_hint="фреонопровод 6.35"))

        m9 = re.search(r"(?:медь\s*(?:9|10)(?:-[а-я]+)?|девятк[а-я]*|десятк[а-я]*|9-к[ау]|10-к[ау])\s*(?:—|-|,|\s)?\s*(\d+(?:[.,](?!\s)\d+)?)\s*(?:м|метр[а-я]*)?", text_lower)
        if m9:
            vol = float(m9.group(1).replace(',', '.'))
            items.append(ExtractedItem(raw_text="медь 9-ка (десятка)", volume=vol, unit="м", context_hint="фреонопровод 9.52"))

        m12 = re.search(r"(?:медь\s*12(?:-[а-я]+)?|двенашк[а-я]*|12-к[ау])\s*(?:—|-|,|\s)?\s*(\d+(?:[.,](?!\s)\d+)?)\s*(?:м|метр[а-я]*)?", text_lower)
        if m12:
            vol = float(m12.group(1).replace(',', '.'))
            items.append(ExtractedItem(raw_text="медь 12-ка", volume=vol, unit="м", context_hint="фреонопровод 12.7"))

        for m_other in re.finditer(r"(?:медь|фреонопровод)[^\d]*(\d+)(?:-[а-я]+|-к[ау])?[^\d]*?(\d+(?:[.,](?!\s)\d+)?)\s*(?:м|метр[а-я]*)?", text_lower):
            d_str = m_other.group(1)
            vol_str = m_other.group(2)
            if d_str not in ("6", "9", "10", "12"):
                items.append(ExtractedItem(
                    raw_text=f"медь {d_str}-ка",
                    volume=float(vol_str.replace(',', '.')),
                    unit="м",
                    context_hint=f"фреонопровод диаметр {d_str}"
                ))

        if "изоляци" in text_lower and ("столько" in text_lower or "на них" in text_lower):
            copper_items = [it for it in items if "медь" in it.raw_text or "фреон" in it.raw_text]
            for c in copper_items:
                items.append(ExtractedItem(
                    raw_text=f"изоляция на {c.raw_text}",
                    volume=c.volume,
                    unit="м",
                    context_hint=f"теплоизоляция для {c.raw_text}"
                ))

        cable_match = re.search(
            r"кабель\s+(\d+[хx]\d+(?:[.,](?!\s)\d+)?)\s*(?:—|-|,|\s)+\s*(\d+(?:[.,](?!\s)\d+)?)\s*(?:м|метр[а-я]*)?",
            text_lower
        )
        if cable_match:
            sec = cable_match.group(1).replace('x', 'х')
            if re.match(r"^\d+х25$", sec):
                sec = sec.replace("25", "2,5")
            vol = float(cable_match.group(2).replace(',', '.'))
            items.append(ExtractedItem(raw_text=f"кабель {sec}", volume=vol, unit="м", context_hint=f"кабель силовой {sec}"))

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

        drill_match = re.search(r"(?:просверлили|сверление|отверсти[йя])\s*(\d+)?\s*(?:отверсти[йя])?\s*(под\s+фреон|под\s+дренаж)?", text_lower)
        if drill_match:
            vol_s = drill_match.group(1)
            hint = drill_match.group(2)
            if not vol_s:
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

        pvc_match = re.search(r"труб[а-я]*\s*пвх\s*(\d+)\s*(?:—|-|\s)?\s*(\d+(?:[.,]\d+)?)\s*(м|метр[а-я]*)?", text_lower)
        if pvc_match:
            diam = pvc_match.group(1)
            vol = float(pvc_match.group(2).replace(',', '.'))
            items.append(ExtractedItem(raw_text=f"труба пвх {diam}", volume=vol, unit="м", context_hint=f"труба пвх {diam}"))

        cb_match = re.search(r"(?:автомат[а-я]*|выключател[а-я]*)\s*(?:на\s*)?(16|20|32)\s*[аa]?\s*(?:—|-|\s)?\s*(\d+)?", text_lower)
        if not cb_match:
            cb_match = re.search(r"(\d+)\s*(?:автомат[а-я]*|выключател[а-я]*)\s*(?:на\s*)?(16|20|32)\s*[аa]?", text_lower)
            if cb_match:
                vol = float(cb_match.group(1))
                rating = cb_match.group(2)
                items.append(ExtractedItem(raw_text=f"автомат {rating}А", volume=vol, unit="шт", context_hint=f"автоматический выключатель {rating}А"))
        else:
            rating = cb_match.group(1)
            vol_s = cb_match.group(2) or "1"
            pre_num = re.search(r"(\d+)\s*(?:автомат|выключател)", text_lower)
            if pre_num:
                vol_s = pre_num.group(1)
            items.append(ExtractedItem(raw_text=f"автомат {rating}А", volume=float(vol_s), unit="шт", context_hint=f"автоматический выключатель {rating}А"))

        stud_match = re.search(r"(\d+)\s*(?:шт\s*)?шпил[ье][а-я]*\s*(?:м8)?", text_lower)
        if not stud_match:
            stud_match = re.search(r"шпил[ье][а-я]*\s*(?:м8)?\s*(?:—|-|\s)?\s*(\d+)", text_lower)
        if stud_match:
            vol = float(stud_match.group(1))
            items.append(ExtractedItem(raw_text="шпилька М8", volume=vol, unit="шт", context_hint="шпилька М8"))

        drain_match = re.search(r"(?:дренаж[а-я]*\s*пп|трубопровод[а-я]*\s*дренаж[а-я]*)\s*(?:—|-|\s)?\s*(\d+(?:[.,]\d+)?)", text_lower)
        if not drain_match:
            drain_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:м|метр[а-я]*)?\s*(?:дренаж[а-я]*\s*пп|трубопровод[а-я]*\s*дренаж[а-я]*)", text_lower)
        if drain_match:
            vol = float(drain_match.group(1).replace(',', '.'))
            items.append(ExtractedItem(raw_text="трубопровод дренажный ПП", volume=vol, unit="м", context_hint="дренаж ПП"))

        return LLMExtractionResponse(is_question=False, items=items)

        return LLMExtractionResponse(is_question=False, items=items)


llm_service = LLMService()
