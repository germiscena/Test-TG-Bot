from src.integrations.google_sheets.parser import parse_csv_file, clean_text


def test_clean_text_homoglyphs():
    raw = "Tpyбoпpoвод дренажныи капилярная аля omводаa конаенсата"
    cleaned = clean_text(raw)
    assert "Трубопровод" in cleaned or "трубопровод" in cleaned
    assert "для отвода конденсата" in cleaned


def test_clean_text_typos():
    raw = "Сберленuе omвepcmuй Д80 L=0,5м "
    cleaned = clean_text(raw)
    assert "сверление отверстий" in cleaned


def test_parse_sample_csv():
    positions, date_col_map = parse_csv_file("data/sample_estimate.csv")
    
    assert len(positions) >= 55, f"Expected ~60 positions, got {len(positions)}"
    
    assert len(date_col_map) > 20
    assert "2026-08-19" in date_col_map
    assert "2026-08-20" in date_col_map
    
    freon_635 = next((p for p in positions if "6,35" in p.name or "6.35" in p.name), None)
    assert freon_635 is not None
    assert freon_635.plan_volume == 265.0
    assert freon_635.executed_volume == 140.0
    assert freon_635.remaining_volume == 125.0
    assert freon_635.unit == "м"

    cable_3x25 = next((p for p in positions if "3х2,5" in p.name or "3х2.5" in p.name), None)
    assert cable_3x25 is not None
    assert cable_3x25.plan_volume == 182.0
    assert cable_3x25.executed_volume == 112.0
    assert cable_3x25.remaining_volume == 70.0
    assert cable_3x25.unit == "м"

    assert freon_635.section == "ОВ 3"
    assert cable_3x25.section == "ЭМ3"

    drilling_positions = [p for p in positions if "сверление отверстий" in p.normalized_name]
    assert len(drilling_positions) == 2
    assert drilling_positions[0].plan_volume == 18.0
    assert drilling_positions[1].plan_volume == 26.0
