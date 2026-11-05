import pytest
from src.integrations.google_sheets.parser import parse_csv_file
from src.services.llm_service import llm_service
from src.services.matching_service import matching_service
from src.core.models import MatchStatus


@pytest.fixture(scope="module")
def catalog():
    positions, _ = parse_csv_file("data/sample_estimate.csv")
    return positions


@pytest.mark.asyncio
async def test_tz_main_example(catalog):
    """
    Тест основного примера из ТЗ:
    «Сегодня проложили медь 6-ку 15 м и 9-ку 15 м, изоляцию на них столько же, кабель 3х2,5 — 56 м, поставили 10 хомутов под фреон»
    """
    text = (
        "Сегодня проложили медь 6-ку 15 м и 9-ку 15 м, "
        "изоляцию на них столько же, кабель 3х2,5 — 56 м, поставили 10 хомутов под фреон"
    )

    extraction = await llm_service.extract_items(text)
    assert not extraction.is_question
    assert len(extraction.items) >= 6

    matched = matching_service.match_all(extraction.items, catalog)
    assert len(matched) >= 6

    # 1. Медь 6-ка -> Фреонопровод Д6,35
    m6 = next(m for m in matched if "6-ка" in m.extracted.raw_text)
    assert m6.status == MatchStatus.CONFIRMED
    assert "6,35" in m6.position.name
    assert m6.extracted.volume == 15.0
    assert m6.position.unit == "м"

    # 2. Медь 9-ка -> Фреонопровод Д9,52
    m9 = next(m for m in matched if "9-ка" in m.extracted.raw_text)
    assert m9.status == MatchStatus.CONFIRMED
    assert "9,52" in m9.position.name
    assert m9.extracted.volume == 15.0

    # 3. Изоляция на 6-ку -> Трубка теплоизоляционная Д6,35
    iso6 = next(m for m in matched if "изоляция" in m.extracted.raw_text and "6" in m.extracted.raw_text)
    assert iso6.status == MatchStatus.CONFIRMED
    assert "теплоизоляционная" in iso6.position.name
    assert "6,35" in iso6.position.name
    assert iso6.extracted.volume == 15.0

    # 4. Изоляция на 9-ку -> Трубка теплоизоляционная Д9,52
    iso9 = next(m for m in matched if "изоляция" in m.extracted.raw_text and "9" in m.extracted.raw_text)
    assert iso9.status == MatchStatus.CONFIRMED
    assert "теплоизоляционная" in iso9.position.name
    assert "9,52" in iso9.position.name
    assert iso9.extracted.volume == 15.0

    # 5. Кабель 3х2,5 -> Кабель силовой сечением 3х2,5
    cable = next(m for m in matched if "кабель" in m.extracted.raw_text and "3х2,5" in m.extracted.raw_text)
    assert cable.status == MatchStatus.CONFIRMED
    assert "3х2,5" in cable.position.name
    assert cable.extracted.volume == 56.0

    # 6. Хомуты под фреон -> Хомут для крепления фреонопровода
    clamp = next(m for m in matched if "хомут" in m.extracted.raw_text)
    assert clamp.status == MatchStatus.CONFIRMED
    assert "фреонопровода" in clamp.position.name
    assert clamp.extracted.volume == 10.0


@pytest.mark.asyncio
async def test_drilling_ambiguity_without_hint(catalog):
    """
    Если назначение сверления не указано («Просверлили 12 отверстий»),
    бот должен вернуть NEEDS_CLARIFICATION с 2 кандидатами (под фреон и под дренаж).
    """
    text = "Просверлили 12 отверстий"
    extraction = await llm_service.extract_items(text)
    matched = matching_service.match_all(extraction.items, catalog)

    assert len(matched) == 1
    item = matched[0]
    assert item.status == MatchStatus.NEEDS_CLARIFICATION
    assert len(item.candidates) == 2
    plans = {c.position.plan_volume for c in item.candidates}
    assert plans == {18.0, 26.0}


@pytest.mark.asyncio
async def test_drilling_with_explicit_hint(catalog):
    """
    Если мастер уточнил назначение («4 отверстия под фреон»),
    сопоставление должно пройти автоматически без вопросов.
    """
    text = "Сделали 4 отверстия под фреон"
    extraction = await llm_service.extract_items(text)
    matched = matching_service.match_all(extraction.items, catalog)

    assert len(matched) == 1
    item = matched[0]
    assert item.status == MatchStatus.CONFIRMED
    assert item.position.plan_volume == 18.0  # фреон = 18 шт


@pytest.mark.asyncio
async def test_overbudget_warning(catalog):
    """
    Проверка предупреждения о превышении остатка по смете.
    По кабелю 3х2,5 остаток = 70 м. Если вводим 100 м, должно быть предупреждение.
    """
    text = "Проложили кабель 3х2,5 — 100 м"
    extraction = await llm_service.extract_items(text)
    matched = matching_service.match_all(extraction.items, catalog)

    assert len(matched) == 1
    item = matched[0]
    assert item.status == MatchStatus.CONFIRMED
    assert item.warning is not None
    assert "превышает остаток" in item.warning


@pytest.mark.asyncio
async def test_question_answering(catalog):
    """
    Проверка вопроса мастера об остатке материалов («Сколько осталось по кабелю 3х2,5?»).
    """
    text = "Сколько осталось по кабелю 3х2,5?"
    extraction = await llm_service.extract_items(text)
    assert extraction.is_question
    assert "3х2,5" in extraction.question_query
