from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from src.bot.states import ReportStates
from src.bot.keyboards import get_clarification_keyboard, get_review_keyboard
from src.bot.formatters import format_draft_message
from src.core.models import ReportDraft, MatchStatus
from src.integrations.google_sheets.repository import sheets_repo

router = Router(name="clarification_router")


@router.callback_query(F.data.startswith("clarify:"))
async def handle_clarification_choice(callback: CallbackQuery, state: FSMContext):
    # Формат: clarify:{item_id}:{row_index}
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

    # Обновляем выбранный элемент в черновике
    target_item = next((it for it in draft.items if it.id == item_id), None)
    if target_item:
        target_item.position = chosen_pos
        target_item.status = MatchStatus.CONFIRMED
        if target_item.extracted.volume > chosen_pos.remaining_volume:
            target_item.warning = (
                f"⚠️ Внимание: объем {target_item.extracted.volume} {chosen_pos.unit} "
                f"превышает остаток по смете ({chosen_pos.remaining_volume} {chosen_pos.unit})!"
            )
        else:
            target_item.warning = None

    await state.update_data(draft=draft.model_dump())
    await callback.answer(f"Выбрано: {chosen_pos.name[:30]}...")

    # Проверяем, остались ли еще неразрешенные позиции
    if draft.has_unresolved:
        next_unresolved = draft.unresolved_items[0]
        await callback.message.edit_text(
            f"⚠️ <b>Позиция требует уточнения:</b>\n"
            f"В речи: <i>«{next_unresolved.extracted.raw_text}»</i> (объем: {next_unresolved.extracted.volume} {next_unresolved.extracted.unit or ''})\n\n"
            f"Выберите нужную строку из сметы:",
            reply_markup=get_clarification_keyboard(next_unresolved),
            parse_mode="HTML"
        )
    else:
        # Все позиции разрешены - переходим к ревью
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
    # Удаляем пропущенную позицию из черновика
    draft.items = [it for it in draft.items if it.id != item_id]
    await state.update_data(draft=draft.model_dump())
    await callback.answer("Позиция пропущена.")

    if draft.has_unresolved:
        next_unresolved = draft.unresolved_items[0]
        await callback.message.edit_text(
            f"⚠️ <b>Позиция требует уточнения:</b>\n"
            f"В речи: <i>«{next_unresolved.extracted.raw_text}»</i> (объем: {next_unresolved.extracted.volume} {next_unresolved.extracted.unit or ''})\n\n"
            f"Выберите нужную строку из сметы:",
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
