import pytest
from config.settings import settings
from src.integrations.google_sheets.repository import GoogleSheetsRepository
from src.integrations.google_sheets.parser import EstimateSheetParser, parse_csv_file
from src.services.llm_service import llm_service
from src.services.matching_service import matching_service
from src.core.models import MatchStatus, ReportDraft


@pytest.fixture
def sample_catalog():
    positions, _ = parse_csv_file("data/sample_estimate.csv")
    return positions


@pytest.mark.asyncio
async def test_add_item_to_draft(sample_catalog):
    """Тест требования 3: возможность добавить позицию в черновик отчета."""
    initial_text = "кабель 3х2,5 — 20 м"
    ext1 = await llm_service.extract_items(initial_text)
    matched1 = matching_service.match_all(ext1.items, sample_catalog)

    draft = ReportDraft(
        user_id=1,
        chat_id=1,
        raw_message=initial_text,
        items=matched1
    )
    assert len(draft.items) == 1

    add_text = "автомат 16А — 2 шт"
    ext2 = await llm_service.extract_items(add_text)
    matched2 = matching_service.match_all(ext2.items, sample_catalog)
    
    draft.items.extend(matched2)
    assert len(draft.items) == 2
    assert any("автоматический выключатель" in it.position.normalized_name for it in draft.items)


@pytest.mark.asyncio
async def test_overwrite_vs_accumulation_mode(monkeypatch, sample_catalog):
    """Тест требования 6: исправление (перезапись) данных за сегодня vs накопление."""
    monkeypatch.setattr(settings, "GOOGLE_SPREADSHEET_ID", None)
    monkeypatch.setattr(settings, "BITRIX24_WEBHOOK_URL", None)

    repo = GoogleSheetsRepository()
    cable_pos = next(p for p in sample_catalog if "3х2,5" in p.name)
    initial_exec = cable_pos.executed_volume

    ok, msg = await repo.record_daily_volumes("2026-11-05", [(cable_pos, 20.0)], overwrite=False)
    assert ok
    assert cable_pos.executed_volume == initial_exec + 20.0

    ok, msg = await repo.record_daily_volumes("2026-11-05", [(cable_pos, 10.0)], overwrite=False)
    assert ok
    assert cable_pos.executed_volume == initial_exec + 30.0

    ok, msg = await repo.record_daily_volumes("2026-11-05", [(cable_pos, 15.0)], overwrite=True)
    assert ok
    assert "заменено" in msg.lower() or "исправлено" in msg.lower()
    assert cable_pos.executed_volume == 15.0


def test_date_parser_supports_multiple_formats():
    """Тест поддержки различных форматов дат (YYYY-MM-DD и DD.MM.YYYY)."""
    raw_header = [
        ["х", "Наименование", "ед изм", "к-во", "", "", "", "", "", "2026-08-19", "20.08.2026", "2026-08-21"],
        ["", "", "", "", "", "", "", "", "", "объем", "объем", "объем"],
        ["1", "Тестовая позиция", "м", "100", "10", "1000", "100", "0", "0", "10", "20", "30"]
    ]
    parser = EstimateSheetParser(raw_header)
    _, date_map = parser.parse()

    assert "2026-08-19" in date_map
    assert "20.08.2026" in date_map
    assert "2026-08-20" in date_map


@pytest.mark.asyncio
async def test_additional_slang_extraction_and_matching(sample_catalog):
    """Тест распознавания автоматов, шпилек и дренажных труб."""
    text = "поставили 3 автомата 16А, 10 шпилек М8 и проложили 15 м дренаж ПП"
    ext = await llm_service.extract_items(text)
    assert len(ext.items) == 3

    matched = matching_service.match_all(ext.items, sample_catalog)
    assert all(m.status == MatchStatus.CONFIRMED for m in matched)

    cb = next(m for m in matched if "автомат" in m.extracted.raw_text)
    assert "16А" in cb.position.name or "16а" in cb.position.normalized_name
    assert cb.extracted.volume == 3.0

    stud = next(m for m in matched if "шпилька" in m.extracted.raw_text)
    assert "шпилька" in stud.position.normalized_name
    assert stud.extracted.volume == 10.0

    drain = next(m for m in matched if "дренаж" in m.extracted.raw_text)
    assert "дренажный" in drain.position.normalized_name
    assert drain.extracted.volume == 15.0


@pytest.mark.asyncio
async def test_stt_transcription_groq_or_mock():
    """Тест STT сервиса с проверкой подключения Groq Whisper или мока."""
    import io
    import wave
    import struct
    from src.services.stt_service import stt_service

    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(struct.pack('<' + 'h'*16000, *([0]*16000)))
    raw_wav = buf.getvalue()

    result = await stt_service.transcribe_audio_bytes(raw_wav, filename="test.wav")
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_copper_ambiguity_and_distinct_buttons(sample_catalog):
    """
    Тест: обработка нестандартного диаметра («медь 7-ка»).
    1. Кандидаты должны содержать четкие различимые наименования с диаметрами.
    2. Клавиатура не должна содержать одинаковых вариантов.
    3. Кнопки и текст содержат конкретные диаметры и остатки.
    """
    from src.bot.formatters import format_clarification_message
    from src.bot.keyboards import get_clarification_keyboard

    text = "Сегодня положили медь 7-ку, 60 метров, и десятку, 20 метров. Изоляция на них столько же, кабель 3х25, 52 метров. Поставили 20 хомутов под фреон."
    ext = await llm_service.extract_items(text)
    matched = matching_service.match_all(ext.items, sample_catalog)

    cu7 = next(m for m in matched if "7-ка" in m.extracted.raw_text and "медь" in m.extracted.raw_text)
    assert cu7.status == MatchStatus.NEEDS_CLARIFICATION
    assert len(cu7.candidates) == 3

    kb = get_clarification_keyboard(cu7)
    button_texts = [btn.text for row in kb.inline_keyboard for btn in row if "Пропустить" not in btn.text]
    assert len(button_texts) == 3
    assert len(set(button_texts)) == 3

    assert any("6,35" in t for t in button_texts)
    assert any("9,52" in t for t in button_texts)
    assert any("12,7" in t or "12.7" in t for t in button_texts)

    msg = format_clarification_message(cu7)
    assert "В смете нет указанного диаметра" in msg
    assert "Фреонопровод Д6,35" in msg
    assert "Фреонопровод Д9,52" in msg
