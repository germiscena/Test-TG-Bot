import re
import logging
from typing import List
from rapidfuzz import fuzz

from src.core.models import (
    Position,
    ExtractedItem,
    MatchedItem,
    MatchStatus,
    CandidateMatch
)

logger = logging.getLogger(__name__)


SLANG_PATTERNS = [
    (r"(?:изоляци.*(?:6|6[.,]35)|к-флекс.*(?:6|6[.,]35)|термофлекс.*(?:6|6[.,]35))", "теплоизоляционная", "6,35", "м"),
    (r"(?:изоляци.*(?:9|10|9[.,]52)|к-флекс.*(?:9|10|9[.,]52)|термофлекс.*(?:9|10|9[.,]52))", "теплоизоляционная", "9,52", "м"),
    (r"(?:изоляци.*(?:12|12[.,]7)|к-флекс.*(?:12|12[.,]7)|термофлекс.*(?:12|12[.,]7))", "теплоизоляционная", "12.7", "м"),
    (r"(?:медь\s*6|шест[её]рк|фреон.*6[.,]35)", "фреонопровод", "6,35", "м"),
    (r"(?:медь\s*(?:9|10)|девятк|десятк|фреон.*(?:9[.,]52|10))", "фреонопровод", "9,52", "м"),
    (r"(?:медь\s*12|двенашк|фреон.*12[.,]7)", "фреонопровод", "12.7", "м"),
    (r"хомут.*фреон", "хомут для крепления фреонопровода", None, "шт"),
    (r"хомут.*дренаж", "хомут для крепления дренажа", None, "шт"),
    (r"(?:автомат.*16|выключател.*16|16\s*а\b)", "автоматический выключатель", "16а", "шт"),
    (r"(?:автомат.*20|выключател.*20|20\s*а\b)", "автоматический выключатель", "20а", "шт"),
    (r"(?:автомат.*32|выключател.*32|32\s*а\b)", "автоматический выключатель", "32а", "шт"),
    (r"шпильк.*(?:м8|1000|метр)", "шпилька м8", None, "шт"),
    (r"(?:дренаж.*пп|трубопровод.*дренаж.*пп)", "трубопровод дренажный пп", None, "м"),
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

        if "сверлен" in query_text or "отверсти" in query_text:
            drilling_candidates = [p for p in catalog if "сверление отверстий" in p.normalized_name]
            if len(drilling_candidates) >= 2:
                if "фреон" in query_text:
                    chosen = next((p for p in drilling_candidates if p.plan_volume == 18.0), drilling_candidates[0])
                    return self._confirm_match(matched_item, chosen)
                elif "дренаж" in query_text:
                    chosen = next((p for p in drilling_candidates if p.plan_volume == 26.0), drilling_candidates[1])
                    return self._confirm_match(matched_item, chosen)
                else:
                    matched_item.status = MatchStatus.NEEDS_CLARIFICATION
                    matched_item.clarification_title = "Уточните назначение отверстий (фреонопровод или дренаж):"
                    matched_item.candidates = [
                        CandidateMatch(
                            position=p,
                            score=90.0,
                            reason=f"Под фреонопроводы (смета {p.plan_volume:g} шт)" if p.plan_volume == 18.0 else f"Под дренажные трубы (смета {p.plan_volume:g} шт)"
                        )
                        for p in drilling_candidates
                    ]
                    return matched_item

        if "хомут" in query_text and "фреон" not in query_text and "дренаж" not in query_text:
            clamp_candidates = [p for p in catalog if "хомут для крепления" in p.normalized_name]
            if len(clamp_candidates) >= 2:
                matched_item.status = MatchStatus.NEEDS_CLARIFICATION
                matched_item.clarification_title = "Уточните назначение хомутов (фреонопровод или дренаж):"
                matched_item.candidates = [
                    CandidateMatch(
                        position=p,
                        score=85.0,
                        reason=p.short_name
                    )
                    for p in clamp_candidates
                ]
                return matched_item

        cable_match = re.search(r"(\d+[хx]\d+(?:[.,]\d+)?)", query_text)
        if "кабел" in query_text and cable_match:
            sec_target = cable_match.group(1).replace('x', 'х').replace('.', ',')
            if re.match(r"^\d+х25$", sec_target):
                sec_target = sec_target.replace("25", "2,5")
            cables = [p for p in catalog if "кабель" in p.normalized_name and sec_target in p.normalized_name.replace('x', 'х')]
            if len(cables) == 1:
                return self._confirm_match(matched_item, cables[0])
            elif len(cables) > 1:
                cables.sort(key=lambda p: p.plan_volume, reverse=True)
                return self._confirm_match(matched_item, cables[0])

        for pattern, keyword, dimension, unit in SLANG_PATTERNS:
            if re.search(pattern, query_text):
                filtered = [
                    p for p in catalog
                    if keyword in p.normalized_name
                    and (dimension is None or dimension in p.normalized_name)
                ]
                if filtered:
                    return self._confirm_match(matched_item, filtered[0])

        if "изоляци" in query_text or "к-флекс" in query_text or "термофлекс" in query_text:
            ins_candidates = [p for p in catalog if "теплоизоляционная" in p.normalized_name]
            if ins_candidates:
                matched_item.status = MatchStatus.NEEDS_CLARIFICATION
                matched_item.clarification_title = "Уточните диаметр теплоизоляции из сметы:"
                matched_item.candidates = [
                    CandidateMatch(
                        position=p,
                        score=85.0,
                        reason=p.short_name
                    )
                    for p in ins_candidates
                ]
                return matched_item

        if ("медь" in query_text or "фреон" in query_text) and "хомут" not in query_text and "сверлен" not in query_text and "отверсти" not in query_text:
            copper_candidates = [p for p in catalog if "фреонопровод медный" in p.normalized_name]
            if copper_candidates:
                matched_item.status = MatchStatus.NEEDS_CLARIFICATION
                matched_item.clarification_title = "В смете нет указанного диаметра медной трубы. Выберите подходящий фреонопровод:"
                matched_item.candidates = [
                    CandidateMatch(
                        position=p,
                        score=85.0,
                        reason=p.short_name
                    )
                    for p in copper_candidates
                ]
                return matched_item

        scored_candidates: List[CandidateMatch] = []
        for pos in catalog:
            score = fuzz.token_set_ratio(query_text, pos.normalized_name)
            
            if extracted.unit and extracted.unit.lower() == pos.unit.lower():
                score += 5

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

        second = scored_candidates[1] if len(scored_candidates) > 1 else None
        if top.score >= 75 and (not second or (top.score - second.score >= 10)):
            return self._confirm_match(matched_item, top.position, confidence=top.score)

        matched_item.status = MatchStatus.NEEDS_CLARIFICATION
        matched_item.clarification_title = "Найдено несколько похожих позиций в смете. Выберите нужную:"
        matched_item.candidates = [
            CandidateMatch(position=c.position, score=c.score, reason=c.position.short_name)
            for c in scored_candidates[:3]
        ]
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

        if item.extracted.volume > position.remaining_volume:
            item.warning = (
                f"⚠️ Внимание: объем {item.extracted.volume} {position.unit} "
                f"превышает остаток по смете ({position.remaining_volume} {position.unit})!"
            )
        return item

    def match_all(self, items: List[ExtractedItem], catalog: List[Position]) -> List[MatchedItem]:
        return [self.match_item(item, catalog) for item in items]


matching_service = MatchingService()
