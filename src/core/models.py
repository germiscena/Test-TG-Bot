from enum import Enum
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class MatchStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    NOT_FOUND = "NOT_FOUND"


class Position(BaseModel):
    row_index: int
    item_no: Optional[str] = None
    section: str = ""
    subsection: Optional[str] = None
    name: str
    normalized_name: str
    unit: str
    plan_volume: float = 0.0
    rate: float = 0.0
    total_salary: float = 0.0
    executed_volume: float = 0.0
    remaining_volume: float = 0.0

    @property
    def short_name(self) -> str:
        """
        Возвращает компактное и информативное наименование позиции для интерфейса Telegram.
        Извлекает ключевые отличительные характеристики (диаметры труб/изоляции,
        сечения кабелей, номиналы автоматов, назначение хомутов/отверстий).
        """
        import re
        name = self.name.strip()
        norm = self.normalized_name

        if "фреонопровод медный" in norm:
            m = re.search(r"[дdД]\s*(\d+(?:[.,]\d+)?)", name)
            diam = m.group(1).replace(".", ",") if m else ""
            inch_map = {"6,35": '1/4"', "9,52": '3/8"', "12,7": '1/2"', "12.7": '1/2"'}
            inch = f" ({inch_map[diam]})" if diam in inch_map else ""
            return f"Фреонопровод Д{diam}{inch}"

        if "теплоизоляцион" in norm or "к-flex" in norm:
            m = re.search(r"[дdД]\s*(\d+(?:[.,]\d+)?)", name)
            diam = m.group(1).replace(".", ",") if m else ""
            inch_map = {"6,35": '1/4"', "9,52": '3/8"', "12,7": '1/2"', "12.7": '1/2"'}
            inch = f" ({inch_map[diam]})" if diam in inch_map else ""
            return f"Изоляция К-FLEX Д{diam}{inch}"

        if "кабель" in norm:
            m = re.search(r"(\d+\s*[хx]\s*\d+(?:[.,]\d+)?)", name)
            sec = m.group(1).replace("x", "х").replace(" ", "") if m else ""
            extra = " (термобарьер)" if "термическ" in norm else ""
            return f"Кабель {sec}{extra}"

        if "автоматический выключатель" in norm or "выключател" in norm:
            m = re.search(r"iр\s*=\s*(\d+)\s*а", norm)
            if not m:
                m = re.search(r"(\d+)\s*а\b", norm)
            rating = m.group(1) if m else ""
            return f"Автомат {rating}А (1п, C)"

        if "сверление отверстий" in norm:
            if self.plan_volume == 18.0:
                return "Сверление под фреонопроводы (18 шт)"
            elif self.plan_volume == 26.0:
                return "Сверление под дренаж (26 шт)"
            return f"Сверление Д80 ({self.plan_volume:g} шт)"

        if "хомут" in norm:
            if "фреон" in norm:
                return "Хомут фреонопровода М8 32 мм"
            elif "дренаж" in norm:
                return "Хомут дренажа М8 25 мм"

        if "труба пвх" in norm:
            m = re.search(r"(\d+)\s*мм", norm)
            d = m.group(1) if m else ""
            return f"Труба ПВХ {d} мм"

        if "шпилька" in norm:
            return "Шпилька М8 1000 мм"

        if len(name) <= 45:
            return name
        return name[:42] + "..."


class ExtractedItem(BaseModel):
    raw_text: str = Field(description="Фрагмент текста мастера, описывающий работу/материал")
    volume: float = Field(description="Численное значение выполненного объема")
    unit: Optional[str] = Field(default=None, description="Единица измерения (м, шт, компл, кг и т.д.)")
    context_hint: Optional[str] = Field(default=None, description="Контекстная подсказка: под фреон, под дренаж, кабель, сечение и т.п.")


class CandidateMatch(BaseModel):
    position: Position
    score: float
    reason: str = ""


class MatchedItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    extracted: ExtractedItem
    status: MatchStatus = MatchStatus.CONFIRMED
    position: Optional[Position] = None
    candidates: List[CandidateMatch] = Field(default_factory=list)
    confidence: float = 0.0
    warning: Optional[str] = None
    clarification_title: Optional[str] = None

    @property
    def is_resolved(self) -> bool:
        return self.status == MatchStatus.CONFIRMED and self.position is not None


class ReportDraft(BaseModel):
    draft_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: int
    chat_id: int
    created_at: datetime = Field(default_factory=datetime.now)
    raw_message: str
    is_voice: bool = False
    items: List[MatchedItem] = Field(default_factory=list)

    @property
    def has_unresolved(self) -> bool:
        return any(not item.is_resolved for item in self.items)

    @property
    def unresolved_items(self) -> List[MatchedItem]:
        return [item for item in self.items if not item.is_resolved]
