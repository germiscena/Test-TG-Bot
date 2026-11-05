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
    row_index: int  # 1-based row index in Google Sheet
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
    def display_title(self) -> str:
        sec = f"[{self.section}] " if self.section else ""
        return f"{sec}{self.name[:60]}... ({self.unit})" if len(self.name) > 60 else f"{sec}{self.name} ({self.unit})"


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
