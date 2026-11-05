import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from config.settings import settings
from src.bot.states import ReportStates
from src.bot.keyboards import get_review_keyboard, get_item_select_keyboard, get_success_keyboard
from src.bot.formatters import format_draft_message
from src.core.models import ReportDraft
from src.integrations.google_sheets.repository import sheets_repo
from src.integrations.bitrix24.client import bitrix_client

logger = logging.getLogger(__name__)
router = Router(name="review_router")


@router.callback_query(F.data == "draft:confirm")
async def handle_draft_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    draft_dict = data.get("draft")
    if not draft_dict:
        await callback.answer("Черновик отчета не найден или устарел.", show_alert=True)
        return

    draft = ReportDraft.model_validate(draft_dict)
    if not draft.items:
        await callback.answer("Отчет пуст.", show_alert=True)
        return

    await callback.message.edit_text("⏳ <i>Записываю объемы в Google Таблицу и Битрикс24...</i>", parse_mode="HTML")

    # 1. Текущая локальная дата объекта
    try:
        tz = ZoneInfo(settings.TIMEZONE)
    except Exception:
        tz = None
    today = datetime.now(tz=tz).strftime("%Y-%m-%d")

    records = [(item.position, item.extracted.volume) for item in draft.items if item.position]
    user_name = callback.from_user.full_name or callback.from_user.username or f"User #{callback.from_user.id}"

    # 2. Запись в Google Таблицу
    gs_success, gs_msg = await sheets_repo.record_daily_volumes(today, records)

    # 3. Запись в Битрикс24
    b24_success, b24_msg = await bitrix_client.create_daily_report_task(
        date_str=today,
        user_name=user_name,
        records=records,
        raw_text=draft.raw_message
    )

    # Очищаем состояние
    await state.clear()

    # 4. Формирование итогового ответа
    status_icon = "✅" if gs_success and b24_success else "⚠️"
    response_text = (
        f"{status_icon} <b>Отчет за {today} успешно зафиксирован!</b>\n\n"
        f"<b>Статус Google Sheets:</b>\n{gs_msg}\n\n"
        f"<b>Статус Битрикс24:</b>\n{b24_msg}"
    )

    await callback.message.edit_text(
        response_text,
        reply_markup=get_success_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer("Успешно сохранено!")


@router.callback_query(F.data == "draft:cancel")
async def handle_draft_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ <b>Отчет отменен.</b> Вы можете отправить новый в любой момент.", parse_mode="HTML")
    await callback.answer("Отменено")


@router.callback_query(F.data == "draft:delete")
async def handle_draft_delete_menu(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    draft = ReportDraft.model_validate(data["draft"])
    await callback.message.edit_text(
        "Выберите позицию, которую хотите <b>удалить</b> из отчета:",
        reply_markup=get_item_select_keyboard(draft, "del_item"),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("del_item:"))
async def handle_item_delete(callback: CallbackQuery, state: FSMContext):
    item_id = callback.data.split(":")[1]
    data = await state.get_data()
    draft = ReportDraft.model_validate(data["draft"])

    draft.items = [it for it in draft.items if it.id != item_id]
    await state.update_data(draft=draft.model_dump())
    await callback.answer("Позиция удалена")

    if not draft.items:
        await state.clear()
        await callback.message.edit_text("Все позиции были удалены. Отчет отменен.")
        return

    await callback.message.edit_text(
        format_draft_message(draft),
        reply_markup=get_review_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "draft:edit")
async def handle_draft_edit_menu(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    draft = ReportDraft.model_validate(data["draft"])
    await callback.message.edit_text(
        "Выберите позицию для изменения объема:",
        reply_markup=get_item_select_keyboard(draft, "edit_vol"),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_vol:"))
async def handle_item_edit_selected(callback: CallbackQuery, state: FSMContext):
    item_id = callback.data.split(":")[1]
    data = await state.get_data()
    draft = ReportDraft.model_validate(data["draft"])
    target_item = next((it for it in draft.items if it.id == item_id), None)

    if not target_item:
        await callback.answer("Позиция не найдена.", show_alert=True)
        return

    await state.update_data(active_edit_item_id=item_id)
    await state.set_state(ReportStates.editing_volume)

    name = target_item.position.name if target_item.position else target_item.extracted.raw_text
    await callback.message.edit_text(
        f"Введите новое числовое значение объема для:\n"
        f"<b>{name}</b>\n"
        f"<i>Текущий объем: {target_item.extracted.volume}</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(ReportStates.editing_volume, F.text)
async def handle_new_volume_input(message: Message, state: FSMContext):
    val_text = message.text.strip().replace(',', '.')
    try:
        new_vol = float(val_text)
        if new_vol <= 0:
            raise ValueError()
    except ValueError:
        await message.answer("Пожалуйста, введите положительное число (например: 15 или 2.5):")
        return

    data = await state.get_data()
    draft = ReportDraft.model_validate(data["draft"])
    edit_id = data.get("active_edit_item_id")

    target_item = next((it for it in draft.items if it.id == edit_id), None)
    if target_item:
        target_item.extracted.volume = new_vol
        if target_item.position and new_vol > target_item.position.remaining_volume:
            target_item.warning = (
                f"⚠️ Внимание: объем {new_vol} {target_item.position.unit} "
                f"превышает остаток по смете ({target_item.position.remaining_volume} {target_item.position.unit})!"
            )
        else:
            target_item.warning = None

    await state.update_data(draft=draft.model_dump())
    await state.set_state(ReportStates.reviewing_draft)

    await message.answer(
        "✅ Объем обновлен!\n\n" + format_draft_message(draft),
        reply_markup=get_review_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "draft:back")
async def handle_draft_back(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    draft = ReportDraft.model_validate(data["draft"])
    await state.set_state(ReportStates.reviewing_draft)
    await callback.message.edit_text(
        format_draft_message(draft),
        reply_markup=get_review_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()
