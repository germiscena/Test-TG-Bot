from src.core.models import ReportDraft, Position, MatchedItem


def format_number(val: float) -> str:
    """Форматирует число без лишних нулей в конце."""
    if val.is_integer():
        return str(int(val))
    return f"{round(val, 3)}".rstrip('0').rstrip('.')


def format_draft_message(draft: ReportDraft) -> str:
    """Форматирует черновик отчета для отображения мастеру в Telegram."""
    lines = ["📋 <b>Предварительный дневной отчет</b>\n"]

    if draft.is_voice:
        lines.append(f"🎙 <i>Голосовое: «{draft.raw_message}»</i>\n")
    else:
        lines.append(f"💬 <i>Текст: «{draft.raw_message}»</i>\n")

    warnings = []
    lines.append(f"<b>Распознанные позиции ({len(draft.items)}):</b>")
    for idx, item in enumerate(draft.items, 1):
        vol_str = format_number(item.extracted.volume)
        if item.is_resolved:
            pos = item.position
            sec = f"[{pos.section}] " if pos.section else ""
            rem_str = format_number(pos.remaining_volume)
            lines.append(
                f"<b>{idx}. {sec}{pos.name}</b>\n"
                f"   └ Выполнено: <b>{vol_str} {pos.unit}</b> "
                f"<i>(по смете ост.: {rem_str} {pos.unit})</i>"
            )
            if item.warning:
                warnings.append(item.warning)
        else:
            lines.append(
                f"<b>{idx}. ❓ {item.extracted.raw_text}</b> — {vol_str} "
                f"{item.extracted.unit or ''} (не сопоставлено)"
            )

    if warnings:
        lines.append("\n<b>Предупреждения по смете:</b>")
        for w in warnings:
            lines.append(f"• {w}")

    lines.append("\n<i>Вы можете скорректировать объем, добавить позиции или подтвердить запись:</i>")
    return "\n".join(lines)


def format_position_info(pos: Position) -> str:
    """Форматирует информацию об остатке позиции по запросу мастера."""
    sec = f"[{pos.section}] " if pos.section else ""
    return (
        f"📊 <b>Информация по позиции:</b>\n\n"
        f"<b>{sec}{pos.name}</b>\n"
        f"• Единица измерения: <b>{pos.unit}</b>\n"
        f"• План по смете: <b>{format_number(pos.plan_volume)} {pos.unit}</b>\n"
        f"• Уже выполнено: <b>{format_number(pos.executed_volume)} {pos.unit}</b>\n"
        f"• <b>Остаток к выполнению: {format_number(pos.remaining_volume)} {pos.unit}</b>\n"
        f"• Тариф за единицу: {pos.rate} руб.\n"
    )


def format_clarification_message(item: MatchedItem) -> str:
    """Форматирует сообщение с запросом уточнения позиции и списком кандидатов."""
    vol_str = format_number(item.extracted.volume)
    unit_str = f" {item.extracted.unit}" if item.extracted.unit else ""
    title = item.clarification_title or "Выберите нужную позицию из сметы:"

    lines = [
        "⚠️ <b>Позиция требует уточнения:</b>",
        f"В речи мастера: <i>«{item.extracted.raw_text}»</i> — <b>{vol_str}{unit_str}</b>\n",
        f"ℹ️ <b>{title}</b>\n"
    ]

    for idx, cand in enumerate(item.candidates, 1):
        pos = cand.position
        short = cand.reason if cand.reason and len(cand.reason) < 45 else pos.short_name
        rem_str = format_number(pos.remaining_volume)
        plan_str = format_number(pos.plan_volume)
        sec_prefix = f"[{pos.section}] " if pos.section else ""
        lines.append(
            f"<b>{idx}️⃣ {sec_prefix}{short}</b>\n"
            f"   └ <i>Полное: {pos.name[:65]}...</i>\n"
            f"   └ <i>План: {plan_str} {pos.unit} | Остаток: {rem_str} {pos.unit} (стр. {pos.row_index})</i>"
        )

    return "\n".join(lines)
