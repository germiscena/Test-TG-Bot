from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
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
        "Вы сможете изменить цифры или удалить ошибочные строки перед записью.\n"
        "3. <b>Запись:</b> при подтверждении объемы записываются в Google Таблицу в столбец с текущей датой "
        "и передаются в задачу Битрикс24.\n"
        "4. <b>Повторный отчет:</b> если прислать еще отчет за сегодня — объемы суммируются."
    )
    await message.answer(help_text, parse_mode="HTML")


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
