import re
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from src.bot.states import ReportStates
from src.bot.keyboards import get_clarification_keyboard, get_review_keyboard
from src.bot.formatters import format_draft_message, format_clarification_message
from src.core.models import ReportDraft, MatchStatus
from src.integrations.google_sheets.repository import sheets_repo

router = Router(name="clarification_router")


@router.callback_query(F.data.startswith("clarify:"))
async def handle_clarification_choice(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    item_id = parts[1]
    chosen_row = int(parts[2])

    data = await state.get_data()
    draft_dict = data.get("draft")
    if not draft_dict:
        await callback.answer("Черновик устарел или не найден.", show_alert=True)
        return

    draft = ReportDraft.model_validate(draft_dict)
    catalog = await sheets_repo.get_catalog()
    chosen_pos = next((p for p in catalog if p.row_index == chosen_row), None)

    if not chosen_pos:
        await callback.answer("Выбранная позиция не найдена в каталоге.", show_alert=True)
        return

    target_item = next((it for it in draft.items if it.id == item_id), None)
    auto_resolved_info = ""
    if target_item:
        target_item.position = chosen_pos
        target_item.status = MatchStatus.CONFIRMED
        target_item.candidates = []
        if target_item.extracted.volume > chosen_pos.remaining_volume:
            target_item.warning = (
                f"⚠️ Внимание: объем {target_item.extracted.volume} {chosen_pos.unit} "
                f"превышает остаток по смете ({chosen_pos.remaining_volume} {chosen_pos.unit})!"
            )
        else:
            target_item.warning = None

        norm_chosen = chosen_pos.normalized_name
        if "фреонопровод медный" in norm_chosen:
            m = re.search(r"[дdД]\s*(\d+(?:[.,]\d+)?)", chosen_pos.name)
            if m:
                target_diam = m.group(1).replace('.', ',')
                for dep in draft.items:
                    if not dep.is_resolved:
                        dep_raw = dep.extracted.raw_text.lower()
                        dep_hint = (dep.extracted.context_hint or "").lower()
                        if "изоляци" in dep_raw or "теплоизоляци" in dep_hint:
                            is_related = (
                                target_item.extracted.raw_text.lower() in dep_raw
                                or target_item.extracted.raw_text.lower() in dep_hint
                                or (len(draft.unresolved_items) <= 2 and dep.extracted.volume == target_item.extracted.volume)
                            )
                            if is_related:
                                matching_ins = next(
                                    (p for p in catalog if "теплоизоляционная" in p.normalized_name and target_diam in p.normalized_name),
                                    None
                                )
                                if matching_ins:
                                    dep.position = matching_ins
                                    dep.status = MatchStatus.CONFIRMED
                                    dep.candidates = []
                                    if dep.extracted.volume > matching_ins.remaining_volume:
                                        dep.warning = (
                                            f"⚠️ Внимание: объем {dep.extracted.volume} {matching_ins.unit} "
                                            f"превышает остаток по смете ({matching_ins.remaining_volume} {matching_ins.unit})!"
                                        )
                                    auto_resolved_info = f" (изоляция: {matching_ins.short_name})"

    await state.update_data(draft=draft.model_dump())
    await callback.answer(f"Выбрано: {chosen_pos.short_name}{auto_resolved_info}")

    if draft.has_unresolved:
        next_unresolved = draft.unresolved_items[0]
        await callback.message.edit_text(
            format_clarification_message(next_unresolved),
            reply_markup=get_clarification_keyboard(next_unresolved),
            parse_mode="HTML"
        )
    else:
        await state.set_state(ReportStates.reviewing_draft)
        await callback.message.edit_text(
            format_draft_message(draft),
            reply_markup=get_review_keyboard(),
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("clarify_skip:"))
async def handle_clarification_skip(callback: CallbackQuery, state: FSMContext):
    item_id = callback.data.split(":")[1]
    data = await state.get_data()
    draft_dict = data.get("draft")
    if not draft_dict:
        await callback.answer("Черновик не найден.", show_alert=True)
        return

    draft = ReportDraft.model_validate(draft_dict)
    target_item = next((it for it in draft.items if it.id == item_id), None)
    if target_item:
        raw_lower = target_item.extracted.raw_text.lower()
        if "медь" in raw_lower or "фреон" in raw_lower:
            draft.items = [
                it for it in draft.items
                if it.id != item_id and not (
                    "изоляци" in it.extracted.raw_text.lower()
                    and target_item.extracted.raw_text.lower() in it.extracted.raw_text.lower()
                )
            ]
        else:
            draft.items = [it for it in draft.items if it.id != item_id]
    else:
        draft.items = [it for it in draft.items if it.id != item_id]

    await state.update_data(draft=draft.model_dump())
    await callback.answer("Позиция пропущена.")

    if draft.has_unresolved:
        next_unresolved = draft.unresolved_items[0]
        await callback.message.edit_text(
            format_clarification_message(next_unresolved),
            reply_markup=get_clarification_keyboard(next_unresolved),
            parse_mode="HTML"
        )
    else:
        if not draft.items:
            await state.clear()
            await callback.message.edit_text("Все позиции были пропущены. Отчет отменен.")
            return

        await state.set_state(ReportStates.reviewing_draft)
        await callback.message.edit_text(
            format_draft_message(draft),
            reply_markup=get_review_keyboard(),
            parse_mode="HTML"
        )
