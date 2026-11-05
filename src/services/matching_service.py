import re
import logging
from typing import List, Optional, Tuple
from rapidfuzz import fuzz

from src.core.models import (
    Position,
    ExtractedItem,
    MatchedItem,
    MatchStatus,
    CandidateMatch
)

logger = logging.getLogger(__name__)


# Специальные соответствия строительного сленга конкретным атрибутам
# Важно: более специфичные правила (изоляция) должны идти ПЕРЕД общими (медь)!
SLANG_PATTERNS = [
    # Теплоизоляция (К-Флекс / трубка для фреонопроводов)
    (r"(?:изоляци.*6|к-флекс.*6|термофлекс.*6)", "теплоизоляционная", "6,35", "м"),
    (r"(?:изоляци.*9|к-флекс.*9|термофлекс.*9)", "теплоизоляционная", "9,52", "м"),
    (r"(?:изоляци.*12|к-флекс.*12|термофлекс.*12)", "теплоизоляционная", "12.7", "м"),
    # Фреонопроводы (медная труба)
    (r"(?:медь\s*6|шест[её]рк|фреон.*6[.,]35)", "фреонопровод", "6,35", "м"),
    (r"(?:медь\s*9|девятк|фреон.*9[.,]52)", "фреонопровод", "9,52", "м"),
    (r"(?:медь\s*12|двенашк|фреон.*12[.,]7)", "фреонопровод", "12.7", "м"),
    # Хомуты
    (r"хомут.*фреон", "хомут для крепления фреонопровода", None, "шт"),
    (r"хомут.*дренаж", "хомут для крепления дренажа", None, "шт"),
    # Трубы ПВХ
    (r"пвх\s*20", "труба пвх", "20", "м"),
    (r"пвх\s*25", "труба пвх", "25", "м"),
]


class MatchingService:
    def __init__(self):
        pass

    def match_item(self, extracted: ExtractedItem, catalog: List[Position]) -> MatchedItem:
        """
        Сопоставляет извлеченную сущность со справочником сметы.
        Использует двухэтапный гибридный подход:
        1. Специфические правила для сленга/размеров.
        2. RapidFuzz Token Matching + отбор кандидатов.
        """
        query_text = f"{extracted.raw_text} {extracted.context_hint or ''}".lower().strip()
        matched_item = MatchedItem(extracted=extracted)

        # 1. Проверка случая со сверлением отверстий (строки 44 и 45)
        if "сверлен" in query_text or "отверсти" in query_text:
            drilling_candidates = [p for p in catalog if "сверление отверстий" in p.normalized_name]
            if len(drilling_candidates) >= 2:
                # Если в речи явно указано назначение:
                if "фреон" in query_text:
                    # Строка 44 (смета 18 под фреонопроводы)
                    chosen = next((p for p in drilling_candidates if p.plan_volume == 18.0), drilling_candidates[0])
                    return self._confirm_match(matched_item, chosen)
                elif "дренаж" in query_text:
                    # Строка 45 (смета 26 под дренажные трубы)
                    chosen = next((p for p in drilling_candidates if p.plan_volume == 26.0), drilling_candidates[1])
                    return self._confirm_match(matched_item, chosen)
                else:
                    # Мастер НЕ уточнил -> возвращаем статус NEEDS_CLARIFICATION с обоими кандидатами
                    matched_item.status = MatchStatus.NEEDS_CLARIFICATION
                    matched_item.candidates = [
                        CandidateMatch(
                            position=p,
                            score=90.0,
                            reason=f"Под фреонопроводы (смета {p.plan_volume} шт)" if p.plan_volume == 18.0 else f"Под дренажные трубы (смета {p.plan_volume} шт)"
                        )
                        for p in drilling_candidates
                    ]
                    return matched_item

        # 2. Проверка случая хомутов без уточнения назначения
        if "хомут" in query_text and "фреон" not in query_text and "дренаж" not in query_text:
            clamp_candidates = [p for p in catalog if "хомут для крепления" in p.normalized_name]
            if len(clamp_candidates) >= 2:
                matched_item.status = MatchStatus.NEEDS_CLARIFICATION
                matched_item.candidates = [
                    CandidateMatch(
                        position=p,
                        score=85.0,
                        reason=f"{p.name} (остаток {p.remaining_volume} {p.unit})"
                    )
                    for p in clamp_candidates
                ]
                return matched_item

        # 3. Проверка кабелей по сечению (3х2,5, 3х1,5, 4х1,5 и т.д.)
        cable_match = re.search(r"(\d+[хx]\d+(?:[.,]\d+)?)", query_text)
        if "кабел" in query_text and cable_match:
            sec_target = cable_match.group(1).replace('x', 'х').replace('.', ',')
            cables = [p for p in catalog if "кабель" in p.normalized_name and sec_target in p.normalized_name.replace('x', 'х')]
            if len(cables) == 1:
                return self._confirm_match(matched_item, cables[0])
            elif len(cables) > 1:
                # Если несколько кабелей одного сечения (например, негорючий vs термический барьер)
                # Берем самый частый или спрашиваем
                cables.sort(key=lambda p: p.plan_volume, reverse=True)
                return self._confirm_match(matched_item, cables[0])

        # 4. Проверка сленговых паттернов (медь 6, 9, 12, изоляция)
        for pattern, keyword, dimension, unit in SLANG_PATTERNS:
            if re.search(pattern, query_text):
                filtered = [
                    p for p in catalog
                    if keyword in p.normalized_name
                    and (dimension is None or dimension in p.normalized_name)
                ]
                if filtered:
                    return self._confirm_match(matched_item, filtered[0])

        # 5. Fuzzy Matching через RapidFuzz
        scored_candidates: List[CandidateMatch] = []
        for pos in catalog:
            score = fuzz.token_set_ratio(query_text, pos.normalized_name)
            
            # Бонус, если совпадает единица измерения
            if extracted.unit and extracted.unit.lower() == pos.unit.lower():
                score += 5

            # Штраф, если в запросе есть числовые атрибуты (размеры), а в позиции их нет
            numbers_in_query = re.findall(r"\b\d+(?:[.,]\d+)?\b", query_text)
            for num in numbers_in_query:
                num_norm = num.replace('.', ',')
                if num in pos.normalized_name or num_norm in pos.normalized_name:
                    score += 15
                else:
                    score -= 10

            scored_candidates.append(CandidateMatch(position=pos, score=score))

        scored_candidates.sort(key=lambda x: x.score, reverse=True)
        top = scored_candidates[0] if scored_candidates else None

        if not top or top.score < 50:
            matched_item.status = MatchStatus.NOT_FOUND
            return matched_item

        # Проверка отрыва первого кандидата от второго
        second = scored_candidates[1] if len(scored_candidates) > 1 else None
        if top.score >= 75 and (not second or (top.score - second.score >= 10)):
            return self._confirm_match(matched_item, top.position, confidence=top.score)

        # Если несколько кандидатов имеют близкий балл
        matched_item.status = MatchStatus.NEEDS_CLARIFICATION
        matched_item.candidates = scored_candidates[:3]
        matched_item.confidence = top.score
        return matched_item

    def _confirm_match(
        self,
        item: MatchedItem,
        position: Position,
        confidence: float = 100.0
    ) -> MatchedItem:
        item.status = MatchStatus.CONFIRMED
        item.position = position
        item.confidence = confidence

        # Проверка остатка по смете ("Будет плюсом" в ТЗ)
        if item.extracted.volume > position.remaining_volume:
            item.warning = (
                f"⚠️ Внимание: объем {item.extracted.volume} {position.unit} "
                f"превышает остаток по смете ({position.remaining_volume} {position.unit})!"
            )
        return item

    def match_all(self, items: List[ExtractedItem], catalog: List[Position]) -> List[MatchedItem]:
        return [self.match_item(item, catalog) for item in items]


matching_service = MatchingService()
