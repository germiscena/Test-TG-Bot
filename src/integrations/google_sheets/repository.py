import asyncio
import logging
import time
from typing import List, Dict, Tuple, Optional

from config.settings import settings
from src.core.models import Position
from src.integrations.google_sheets.parser import EstimateSheetParser, parse_csv_file

logger = logging.getLogger(__name__)


class GoogleSheetsRepository:
    def __init__(self):
        self._cached_positions: Optional[List[Position]] = None
        self._cached_dates: Optional[Dict[str, int]] = None
        self._cache_time: float = 0
        self._lock = asyncio.Lock()

    def invalidate_cache(self):
        self._cached_positions = None
        self._cached_dates = None
        self._cache_time = 0

    async def get_catalog(self, force_refresh: bool = False) -> List[Position]:
        """Возвращает актуальный справочник позиций с кэшированием."""
        async with self._lock:
            now = time.time()
            if (
                not force_refresh
                and self._cached_positions is not None
                and (now - self._cache_time) < settings.CACHE_TTL_SECONDS
            ):
                return self._cached_positions

            if settings.has_google_credentials:
                try:
                    positions, dates = await asyncio.to_thread(self._fetch_from_google_sheets)
                    self._cached_positions = positions
                    self._cached_dates = dates
                    self._cache_time = now
                    logger.info(f"Loaded {len(positions)} positions from live Google Sheet")
                    return positions
                except Exception as e:
                    logger.error(f"Failed to fetch from Google Sheets: {e}. Falling back to CSV.")

            positions, dates = parse_csv_file(settings.FALLBACK_CSV_PATH)
            self._cached_positions = positions
            self._cached_dates = dates
            self._cache_time = now
            logger.info(f"Loaded {len(positions)} positions from local CSV fallback")
            return positions

    def _fetch_from_google_sheets(self) -> Tuple[List[Position], Dict[str, int]]:
        import gspread
        gc = gspread.service_account(filename=settings.GOOGLE_SERVICE_ACCOUNT_FILE)
        sh = gc.open_by_key(settings.GOOGLE_SPREADSHEET_ID)
        worksheet = sh.worksheet(settings.GOOGLE_SHEET_NAME)
        all_values = worksheet.get_all_values()
        parser = EstimateSheetParser(all_values)
        return parser.parse()

    async def record_daily_volumes(
        self,
        date_str: str,
        records: List[Tuple[Position, float]],
        overwrite: bool = False
    ) -> Tuple[bool, str]:
        """
        Записывает выполненные объемы в столбец с датой date_str (YYYY-MM-DD).
        Если overwrite=False: прибавляет к имеющемуся значению (накопление).
        Если overwrite=True: заменяет имеющееся значение (исправление за сегодня).
        """
        if not records:
            return False, "Список позиций для записи пуст."

        if not settings.has_google_credentials:
            summary_lines = []
            for pos, vol in records:
                if overwrite:
                    pos.executed_volume = vol
                    pos.remaining_volume = max(0.0, pos.plan_volume - vol)
                    summary_lines.append(f"Строка {pos.row_index}: заменено на {vol} {pos.unit} ({pos.short_name})")
                else:
                    pos.executed_volume += vol
                    pos.remaining_volume = max(0.0, pos.remaining_volume - vol)
                    summary_lines.append(f"Строка {pos.row_index}: +{vol} {pos.unit} ({pos.short_name})")
            details = "\n".join(summary_lines)
            action_desc = "исправлено (замена)" if overwrite else "дополнено (накопление)"
            return True, f"Записано в локальном режиме ({action_desc}):\n{details}"

        try:
            return await asyncio.to_thread(self._write_to_google_sheets, date_str, records, overwrite)
        except Exception as e:
            logger.error(f"Error writing to Google Sheets: {e}", exc_info=True)
            return False, f"Ошибка записи в Google Sheets: {str(e)}"

    def _write_to_google_sheets(
        self,
        date_str: str,
        records: List[Tuple[Position, float]],
        overwrite: bool = False
    ) -> Tuple[bool, str]:
        import gspread
        gc = gspread.service_account(filename=settings.GOOGLE_SERVICE_ACCOUNT_FILE)
        sh = gc.open_by_key(settings.GOOGLE_SPREADSHEET_ID)
        worksheet = sh.worksheet(settings.GOOGLE_SHEET_NAME)

        all_values = worksheet.get_all_values()
        parser = EstimateSheetParser(all_values)
        _, date_col_map = parser.parse()

        date_row_idx = parser.date_row_index
        if date_row_idx == -1:
            date_row_idx = 2

        if date_str in date_col_map:
            col_idx_0based = date_col_map[date_str]
        else:
            max_col = max(date_col_map.values()) if date_col_map else 9
            col_idx_0based = max_col + 1
            col_1based = col_idx_0based + 1

            if col_1based > worksheet.col_count:
                worksheet.add_cols(col_1based - worksheet.col_count + 5)

            header_updates = [
                {'range': gspread.utils.rowcol_to_a1(date_row_idx + 1, col_1based), 'values': [[date_str]]},
                {'range': gspread.utils.rowcol_to_a1(date_row_idx + 2, col_1based), 'values': [['объем']]}
            ]
            worksheet.batch_update(header_updates)
            date_col_map[date_str] = col_idx_0based

        col_1based = col_idx_0based + 1

        if col_1based > worksheet.col_count:
            worksheet.add_cols(col_1based - worksheet.col_count + 5)

        updates = []
        summary = []
        for pos, new_volume in records:
            row_1based = pos.row_index
            existing_val_str = ""
            if row_1based - 1 < len(all_values) and col_idx_0based < len(all_values[row_1based - 1]):
                existing_val_str = all_values[row_1based - 1][col_idx_0based].strip()

            existing_val = 0.0
            if existing_val_str:
                try:
                    existing_val = float(existing_val_str.replace(',', '.'))
                except ValueError:
                    existing_val = 0.0

            if overwrite:
                total_val = round(new_volume, 3)
                diff = new_volume - existing_val
                summary_action = f"заменено на {new_volume} {pos.unit} (было {existing_val})"
            else:
                total_val = round(existing_val + new_volume, 3)
                diff = new_volume
                summary_action = f"{existing_val} + {new_volume} = {total_val} {pos.unit}"

            val_to_write = int(total_val) if total_val.is_integer() else total_val

            cell_coord = gspread.utils.rowcol_to_a1(row_1based, col_1based)
            updates.append({
                'range': cell_coord,
                'values': [[val_to_write]]
            })
            summary.append(f"Строка {row_1based}: {summary_action}")

            pos.executed_volume += diff
            pos.remaining_volume = max(0.0, pos.remaining_volume - diff)

        worksheet.batch_update(updates)
        self.invalidate_cache()
        mode_text = "Исправлено (перезапись)" if overwrite else "Дополнено (накопление)"
        return True, f"Успешно записано в Google Sheets [{mode_text}] ({date_str}):\n" + "\n".join(summary)

    async def get_today_records(self, date_str: str) -> List[Tuple[Position, float]]:
        """Возвращает список позиций, которые уже имеют ненулевой объем за указанную дату."""
        if not settings.has_google_credentials:
            return []

        try:
            return await asyncio.to_thread(self._fetch_today_records, date_str)
        except Exception as e:
            logger.error(f"Error fetching today records: {e}")
            return []

    def _fetch_today_records(self, date_str: str) -> List[Tuple[Position, float]]:
        import gspread
        gc = gspread.service_account(filename=settings.GOOGLE_SERVICE_ACCOUNT_FILE)
        sh = gc.open_by_key(settings.GOOGLE_SPREADSHEET_ID)
        worksheet = sh.worksheet(settings.GOOGLE_SHEET_NAME)

        all_values = worksheet.get_all_values()
        parser = EstimateSheetParser(all_values)
        positions, date_col_map = parser.parse()

        col_idx = date_col_map.get(date_str)
        if col_idx is None:
            return []

        result = []
        for pos in positions:
            r = pos.row_index - 1
            if r < len(all_values) and col_idx < len(all_values[r]):
                val_s = all_values[r][col_idx].strip()
                if val_s:
                    try:
                        v = float(val_s.replace(',', '.'))
                        if v > 0:
                            result.append((pos, v))
                    except ValueError:
                        pass
        return result


sheets_repo = GoogleSheetsRepository()
