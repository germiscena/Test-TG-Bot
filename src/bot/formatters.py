from typing import Optional
from src.core.models import ReportDraft, Position


def format_draft_message(draft: ReportDraft) -> str:
    """Форматирует черновик отчета для отображения мастеру в Telegram."""
    lines = ["📋 <b>Предварительный дневной отчет</b>\n"]

    if draft.is_voice:
        lines.append(f"🎙 <i>Голосовое: «{draft.raw_message}»</i>\n")
    else:
        lines.append(f"💬 <i>Текст: «{draft.raw_message}»</i>\n")

    warnings = []
    lines.append("<b>Распознанные позиции:</b>")
    for idx, item in enumerate(draft.items, 1):
        if item.is_resolved:
            pos = item.position
            sec = f"[{pos.section}] " if pos.section else ""
            lines.append(
                f"<b>{idx}. {sec}{pos.name}</b>\n"
                f"   └ Выполнено: <b>{item.extracted.volume} {pos.unit}</b> "
                f"<i>(по смете ост.: {pos.remaining_volume} {pos.unit})</i>"
            )
            if item.warning:
                warnings.append(item.warning)
        else:
            lines.append(
                f"<b>{idx}. ❓ {item.extracted.raw_text}</b> — {item.extracted.volume} "
                f"{item.extracted.unit or ''} (не сопоставлено)"
            )

    if warnings:
        lines.append("\n<b>Предупреждения по смете:</b>")
        for w in warnings:
            lines.append(f"• {w}")

    lines.append("\n<i>Перед записью вы можете скорректировать объемы, удалить ненужные позиции или подтвердить отправку.</i>")
    return "\n".join(lines)


def format_position_info(pos: Position) -> str:
    """Форматирует информацию об остатке позиции по запросу мастера."""
    sec = f"[{pos.section}] " if pos.section else ""
    return (
        f"📊 <b>Информация по позиции:</b>\n\n"
        f"<b>{sec}{pos.name}</b>\n"
        f"• Единица измерения: <b>{pos.unit}</b>\n"
        f"• План по смете: <b>{pos.plan_volume} {pos.unit}</b>\n"
        f"• Уже выполнено: <b>{pos.executed_volume} {pos.unit}</b>\n"
        f"• <b>Остаток к выполнению: {pos.remaining_volume} {pos.unit}</b>\n"
        f"• Тариф за единицу: {pos.rate} руб.\n"
    )
