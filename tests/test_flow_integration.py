import pytest
from config.settings import settings
from src.integrations.google_sheets.repository import GoogleSheetsRepository
from src.integrations.bitrix24.client import bitrix_client
from src.services.llm_service import llm_service
from src.services.matching_service import matching_service
from src.core.models import ReportDraft, MatchStatus


@pytest.mark.asyncio
async def test_end_to_end_report_recording(monkeypatch):
    # Изолируем автотест от реальных сетевых вызовов, тестируя полный цикл бизнес-логики
    monkeypatch.setattr(settings, "GOOGLE_SPREADSHEET_ID", None)
    monkeypatch.setattr(settings, "BITRIX24_WEBHOOK_URL", None)

    # 1. Initialize repo with local fallback
    repo = GoogleSheetsRepository()
    catalog = await repo.get_catalog(force_refresh=True)
    assert len(catalog) > 50

    # 2. Simulate message from foreman
    foreman_text = (
        "Сегодня проложили медь 6-ку 15 м и 9-ку 15 м, "
        "изоляцию на них столько же, кабель 3х2,5 — 56 м, поставили 10 хомутов под фреон"
    )

    # 3. LLM extraction
    extraction = await llm_service.extract_items(foreman_text)
    assert not extraction.is_question
    assert len(extraction.items) == 6

    # 4. Hybrid Matching
    matched = matching_service.match_all(extraction.items, catalog)
    assert all(m.status == MatchStatus.CONFIRMED for m in matched)

    draft = ReportDraft(
        user_id=12345678,
        chat_id=12345678,
        raw_message=foreman_text,
        items=matched
    )
    assert not draft.has_unresolved

    # 5. Record daily volumes (Summation mode)
    target_date = "2026-11-05"
    records = [(item.position, item.extracted.volume) for item in draft.items]
    
    # Store initial values
    cable_pos = next(p for p, _ in records if "3х2,5" in p.name)
    initial_cable_exec = cable_pos.executed_volume

    gs_ok, gs_msg = await repo.record_daily_volumes(target_date, records)
    assert gs_ok
    assert "Строка" in gs_msg
    assert cable_pos.executed_volume == initial_cable_exec + 56.0

    # 6. Bitrix24 Task Creation
    b24_ok, b24_msg = await bitrix_client.create_daily_report_task(
        date_str=target_date,
        user_name="Иван Прораб",
        records=records,
        raw_text=foreman_text
    )
    assert b24_ok
    assert "зафиксировано" in b24_msg.lower() or "успешно" in b24_msg.lower()
