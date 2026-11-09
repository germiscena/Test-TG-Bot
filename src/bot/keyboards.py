from typing import Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from src.core.models import MatchedItem, ReportDraft
from src.bot.formatters import format_number
from config.settings import settings


def get_clarification_keyboard(item: MatchedItem) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру для выбора правильной позиции при неоднозначности."""
    buttons = []
    for idx, cand in enumerate(item.candidates, 1):
        pos = cand.position
        short_title = cand.reason if cand.reason and len(cand.reason) <= 40 else pos.short_name
        rem_str = format_number(pos.remaining_volume)
        btn_text = f"{idx}. {short_title} (ост. {rem_str} {pos.unit})"
        cb_data = f"clarify:{item.id}:{pos.row_index}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])

    buttons.append([InlineKeyboardButton(text="❌ Пропустить эту позицию", callback_data=f"clarify_skip:{item.id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_review_keyboard() -> InlineKeyboardMarkup:
    """Генерирует главную клавиатуру подтверждения черновика отчета."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Записать (прибавить к сегодня)", callback_data="draft:confirm_add")
        ],
        [
            InlineKeyboardButton(text="🔄 Заменить (исправить данные за сегодня)", callback_data="draft:confirm_overwrite")
        ],
        [
            InlineKeyboardButton(text="✏️ Изменить объем", callback_data="draft:edit"),
            InlineKeyboardButton(text="➕ Добавить позицию", callback_data="draft:add")
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить позицию", callback_data="draft:delete"),
            InlineKeyboardButton(text="❌ Отменить отчет", callback_data="draft:cancel")
        ]
    ])


def get_item_select_keyboard(draft: ReportDraft, action_prefix: str) -> InlineKeyboardMarkup:
    """Клавиатура для выбора позиции при редактировании или удалении."""
    buttons = []
    for idx, item in enumerate(draft.items, 1):
        name = item.position.short_name if item.position else item.extracted.raw_text
        vol = format_number(item.extracted.volume)
        unit = item.position.unit if item.position else item.extracted.unit or "ед."
        btn_text = f"{idx}. {name} — {vol} {unit}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"{action_prefix}:{item.id}")])

    buttons.append([InlineKeyboardButton(text="🔙 Назад к отчету", callback_data="draft:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_success_keyboard(sheet_url: Optional[str] = None) -> InlineKeyboardMarkup:
    """Клавиатура после успешной записи со ссылкой на Google Таблицу."""
    url = sheet_url or settings.sheet_web_url
    buttons = []
    if url:
        buttons.append([InlineKeyboardButton(text="📊 Открыть Google Таблицу", url=url)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
