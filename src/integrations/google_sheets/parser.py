import re
import csv
from typing import List, Dict, Tuple, Optional
from src.core.models import Position


HOMOGLYPH_MAP = {
    'T': 'Т', 'y': 'у', 'p': 'р', 'o': 'о', 'm': 'т', 'a': 'а', 'c': 'с', 'e': 'е', 'x': 'х', 'u': 'и',
    'A': 'А', 'B': 'В', 'E': 'Е', 'K': 'К', 'M': 'М', 'H': 'Н', 'O': 'О', 'P': 'Р', 'C': 'С', 'X': 'Х',
    'k': 'к',
}

KNOWN_REPLACEMENTS = [
    (r"\bсберлен[uи]е\b", "сверление"),
    (r"\bomвepcmuй\b", "отверстий"),
    (r"\bтрубопрубопровод\b", "трубопровод"),
    (r"\bсичтемы\b", "системы"),
    (r"\bстальна\b", "стальная"),
    (r"\bгильзх\b", "гильз"),
    (r"\bкапилярная\b", "капиллярная"),
    (r"\bдренажныи\b", "дренажный"),
    (r"\bаля\b", "для"),
    (r"\bomводаa\b", "отвода"),
    (r"\bотводаа\b", "отвода"),
    (r"\bконаенсата\b", "конденсата"),
]


def clean_text(text: str) -> str:
    """Удаляет артефакты, нормализует пробелы, гомоглифы и частые опечатки."""
    if not text:
        return ""
    
    text = text.replace('\xa0', ' ').strip()
    text = re.sub(r'\s+', ' ', text)
    
    for pattern, repl in KNOWN_REPLACEMENTS:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    chars = []
    for ch in text:
        chars.append(HOMOGLYPH_MAP.get(ch, ch))
    result = "".join(chars)

    for pattern, repl in KNOWN_REPLACEMENTS:
        result = re.sub(pattern, repl, result, flags=re.IGNORECASE)

    return re.sub(r'\s+', ' ', result).strip()


def parse_float(val: str) -> float:
    if not val:
        return 0.0
    val_clean = str(val).strip().replace(',', '.').replace(' ', '')
    try:
        return float(val_clean)
    except ValueError:
        return 0.0


class EstimateSheetParser:
    """
    Парсер сметных таблиц (Google Sheets / CSV).
    Устойчив к сложной многоуровневой шапке, объединениям ячеек,
    пустым строкам и опечаткам.
    """

    def __init__(self, raw_rows: List[List[str]]):
        self.raw_rows = raw_rows
        self.date_col_map: Dict[str, int] = {}
        self.date_row_index: int = -1
        self.positions: List[Position] = []

    def parse(self) -> Tuple[List[Position], Dict[str, int]]:
        self._find_dates()
        self._parse_positions()
        return self.positions, self.date_col_map

    def _find_dates(self):
        """Поиск строки с датами (формат YYYY-MM-DD или DD.MM.YYYY)."""
        date_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})$')
        
        for r_idx, row in enumerate(self.raw_rows[:10]):
            found_dates = {}
            for c_idx, cell in enumerate(row):
                val = cell.strip()
                if date_pattern.match(val):
                    if val not in found_dates:
                        found_dates[val] = c_idx

                    if re.match(r'^\d{2}\.\d{2}\.\d{4}$', val):
                        d, m, y = val.split('.')
                        iso_val = f"{y}-{m}-{d}"
                        if iso_val not in found_dates:
                            found_dates[iso_val] = c_idx
                    elif re.match(r'^\d{4}-\d{2}-\d{2}$', val):
                        y, m, d = val.split('-')
                        ru_val = f"{d}.{m}.{y}"
                        if ru_val not in found_dates:
                            found_dates[ru_val] = c_idx
            
            if len(found_dates) >= 3:
                self.date_row_index = r_idx
                self.date_col_map = found_dates
                break

    def _parse_positions(self):
        current_section = ""
        current_subsection = None

        start_row = self.date_row_index + 1 if self.date_row_index != -1 else 4

        for r_idx in range(start_row, len(self.raw_rows)):
            row = self.raw_rows[r_idx]
            if not row:
                continue

            col_no = row[0].strip() if len(row) > 0 else ""
            raw_name = row[1].strip() if len(row) > 1 else ""
            unit = row[2].strip() if len(row) > 2 else ""
            qty_str = row[3].strip() if len(row) > 3 else ""
            rate_str = row[4].strip() if len(row) > 4 else ""
            tot_sal_str = row[5].strip() if len(row) > 5 else ""
            rem_str = row[6].strip() if len(row) > 6 else ""
            exec_str = row[8].strip() if len(row) > 8 else ""

            if not raw_name:
                continue

            cleaned_name = clean_text(raw_name)
            name_lower = cleaned_name.lower()
            name_upper = cleaned_name.upper()

            if any(marker in name_upper for marker in ["ИТОГО ПО", "ВСЕГО ЗА", "ИТОГО"]):
                continue

            if cleaned_name in ["ОВ 3", "ОВ3", "ЭМ3", "ЭМ 3"] or (not unit and not qty_str and ("ОВ" in cleaned_name or "ЭМ" in cleaned_name)):
                current_section = cleaned_name
                current_subsection = None
                continue

            if not unit and not qty_str:
                current_subsection = cleaned_name
                continue

            norm_unit = unit.strip().lower()
            plan_qty = parse_float(qty_str)
            rate = parse_float(rate_str)
            tot_salary = parse_float(tot_sal_str)
            exec_qty = parse_float(exec_str)

            if rem_str:
                rem_qty = parse_float(rem_str)
            else:
                rem_qty = max(0.0, plan_qty - exec_qty)

            position = Position(
                row_index=r_idx + 1,
                item_no=col_no if col_no else None,
                section=current_section,
                subsection=current_subsection,
                name=raw_name,
                normalized_name=name_lower,
                unit=norm_unit,
                plan_volume=plan_qty,
                rate=rate,
                total_salary=tot_salary,
                executed_volume=exec_qty,
                remaining_volume=round(rem_qty, 3)
            )
            self.positions.append(position)


def parse_csv_file(file_path: str) -> Tuple[List[Position], Dict[str, int]]:
    """Вспомогательная функция для чтения локального CSV-файла."""
    rows = []
    with open(file_path, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(row)
    parser = EstimateSheetParser(rows)
    return parser.parse()
