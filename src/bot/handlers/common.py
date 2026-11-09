from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from config.settings import settings
from src.bot.keyboards import get_success_keyboard
from src.bot.formatters import format_number
from src.integrations.google_sheets.repository import sheets_repo

router = Router(name="common_router")


@router.message(CommandStart())
async def cmd_start(message: Message):
    welcome_text = (
        "👋 <b>Приветствую, мастер!</b>\n\n"
        "Я AI-ассистент для строительного учета выполненных работ.\n\n"
        "<b>Как отправить отчет:</b>\n"
        "• Отправьте <b>голосовое сообщение</b> или <b>текст</b> в свободной форме прямо сюда.\n"
        "<i>Пример: «Сегодня проложили медь 6-ку 15 м и 9-ку 15 м, изоляцию на них столько же, кабель 3х2,5 — 56 м, поставили 10 хомутов под фреон»</i>\n\n"
        "<b>Дополнительные возможности:</b>\n"
        "• Спросите остаток: <i>«Сколько осталось по кабелю 3х2,5?»</i>\n"
        "• /today — посмотреть, что уже записано за сегодня\n"
        "• /sheet — ссылка на рабочую Google Таблицу\n"
        "• /sync — обновить справочник позиций из Google Таблицы\n"
        "• /catalog — посмотреть структуру сметы и количество позиций\n"
        "• /help — подробная справка"
    )
    await message.answer(welcome_text, parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "🛠 <b>Справка по боту:</b>\n\n"
        "1. <b>Голосовой отчет:</b> зажмите микрофон и надиктуйте, что сделали за день.\n"
        "2. <b>Подтверждение:</b> бот сопоставит ваши слова со сметой и покажет карточку для проверки. "
        "Вы можете изменить цифры, удалить ошибочные строки или добавить забытое.\n"
        "3. <b>Выбор режима записи:</b>\n"
        "   • <i>«Записать (прибавить к сегодня)»</i> — суммирует новый объем с уже внесенным.\n"
        "   • <i>«Заменить (исправить данные за сегодня)»</i> — перезаписывает ячейку за сегодня новым значением.\n"
        "4. <b>Просмотр таблицы:</b> команда /sheet или кнопка со ссылкой после сохранения."
    )
    await message.answer(help_text, parse_mode="HTML")


@router.message(Command("sheet", "table"))
async def cmd_sheet(message: Message):
    url = settings.sheet_web_url
    if url:
        await message.answer(
            f"📊 <b>Рабочая Google Таблица объекта:</b>\n{url}",
            reply_markup=get_success_keyboard(),
            parse_mode="HTML"
        )
    else:
        await message.answer("Ссылка на таблицу не настроена в .env.")


@router.message(Command("today"))
async def cmd_today(message: Message):
    try:
        tz = ZoneInfo(settings.TIMEZONE)
    except Exception:
        tz = None
    today = datetime.now(tz=tz).strftime("%Y-%m-%d")

    records = await sheets_repo.get_today_records(today)
    if not records:
        await message.answer(
            f"📅 <b>Данные за сегодня ({today}):</b>\n\n"
            f"За сегодняшнее число еще не внесено ни одной записи.\n"
            f"Отправьте текст или голосовое сообщение с выполненными работами!",
            reply_markup=get_success_keyboard(),
            parse_mode="HTML"
        )
        return

    lines = [f"📅 <b>Внесенные данные за сегодня ({today}):</b>\n"]
    for idx, (pos, vol) in enumerate(records, 1):
        lines.append(f"{idx}. {pos.short_name} — <b>{format_number(vol)} {pos.unit}</b>")

    lines.append(f"\nВсего позиций за сегодня: <b>{len(records)}</b>.")
    lines.append("<i>Чтобы исправить данные, отправьте отчет и нажмите кнопку «Заменить (исправить данные за сегодня)».</i>")

    await message.answer("\n".join(lines), reply_markup=get_success_keyboard(), parse_mode="HTML")


@router.message(Command("sync"))
async def cmd_sync(message: Message):
    await message.answer("🔄 Обновляю справочник позиций из Google Таблицы...")
    try:
        positions = await sheets_repo.get_catalog(force_refresh=True)
        await message.answer(f"✅ Справочник успешно обновлен! Загружено позиций: <b>{len(positions)}</b>", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ошибка обновления справочника: {e}")


@router.message(Command("catalog"))
async def cmd_catalog(message: Message):
    positions = await sheets_repo.get_catalog()
    ov_count = sum(1 for p in positions if "ОВ" in p.section)
    em_count = sum(1 for p in positions if "ЭМ" in p.section)
    await message.answer(
        f"📑 <b>Текущая смета объекта:</b>\n"
        f"• Всего активных позиций: <b>{len(positions)}</b>\n"
        f"• Раздел «ОВ 3» (Кондиционирование/дренаж): <b>{ov_count}</b>\n"
        f"• Раздел «ЭМ3» (Электромонтаж/кабели): <b>{em_count}</b>",
        parse_mode="HTML"
    )
