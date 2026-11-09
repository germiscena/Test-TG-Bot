import io
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from rapidfuzz import fuzz

from src.bot.states import ReportStates
from src.bot.keyboards import get_clarification_keyboard, get_review_keyboard
from src.bot.formatters import format_draft_message, format_position_info, format_clarification_message
from src.core.models import ReportDraft
from src.services.stt_service import stt_service
from src.services.llm_service import llm_service
from src.services.matching_service import matching_service
from src.integrations.google_sheets.repository import sheets_repo

logger = logging.getLogger(__name__)
router = Router(name="report_router")


@router.message(F.voice)
async def handle_voice_report(message: Message, state: FSMContext, bot: Bot):
    status_msg = await message.answer("🎧 <i>Слушаю голосовое сообщение...</i>", parse_mode="HTML")
    try:
        file_io = io.BytesIO()
        await bot.download(message.voice, destination=file_io)
        voice_bytes = file_io.getvalue()

        recognized_text = await stt_service.transcribe_audio_bytes(voice_bytes)
        await status_msg.edit_text(f"🎙 <b>Распознано:</b> «{recognized_text}»", parse_mode="HTML")

        await process_report_text(recognized_text, is_voice=True, message=message, state=state)
    except Exception as e:
        logger.error(f"Voice handling error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Ошибка обработки голосового сообщения: {e}")


@router.message(F.text, ~F.text.startswith("/"))
async def handle_text_report(message: Message, state: FSMContext):
    await process_report_text(message.text, is_voice=False, message=message, state=state)


async def process_report_text(text: str, is_voice: bool, message: Message, state: FSMContext):
    extraction = await llm_service.extract_items(text)
    catalog = await sheets_repo.get_catalog()

    if extraction.is_question and extraction.question_query:
        query = extraction.question_query.lower()
        best_pos = None
        best_score = 0
        for pos in catalog:
            score = fuzz.token_set_ratio(query, pos.normalized_name)
            if score > best_score:
                best_score = score
                best_pos = pos

        if best_pos and best_score >= 60:
            await message.answer(format_position_info(best_pos), parse_mode="HTML")
        else:
            await message.answer(f"По запросу <i>«{query}»</i> позиция в смете не найдена.", parse_mode="HTML")
        return

    if not extraction.items:
        await message.answer(
            "Не удалось распознать работы и объемы в сообщении.\n"
            "Пожалуйста, укажите материал/работу и числовой объем, например:\n"
            "<i>«Проложили кабель 3х2,5 — 40 м и поставили 5 автоматов 16А»</i>",
            parse_mode="HTML"
        )
        return

    matched_items = matching_service.match_all(extraction.items, catalog)

    draft = ReportDraft(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        raw_message=text,
        is_voice=is_voice,
        items=matched_items
    )

    await state.update_data(draft=draft.model_dump())

    if draft.has_unresolved:
        first_unresolved = draft.unresolved_items[0]
        await state.set_state(ReportStates.clarifying_item)
        await message.answer(
            format_clarification_message(first_unresolved),
            reply_markup=get_clarification_keyboard(first_unresolved),
            parse_mode="HTML"
        )
    else:
        await state.set_state(ReportStates.reviewing_draft)
        await message.answer(
            format_draft_message(draft),
            reply_markup=get_review_keyboard(),
            parse_mode="HTML"
        )
