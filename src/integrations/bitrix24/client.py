import logging
import socket
import httpx
from typing import List, Tuple, Optional
from config.settings import settings
from src.core.models import Position

logger = logging.getLogger(__name__)


def _get_lan_transport() -> Optional[httpx.AsyncHTTPTransport]:
    """
    Находит физический LAN IP (192.168.x.x / 172.x.x), чтобы обойти VPN-туннель
    для обращения к российским облачным сервисам (bitrix24.ru), которые блокируют зарубежные IP.
    """
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip.startswith("192.168.") or ip.startswith("172."):
                return httpx.AsyncHTTPTransport(local_address=ip)
    except Exception:
        pass
    return None


class Bitrix24Client:
    """Клиент для интеграции с Битрикс24 через входящий вебхук REST API."""

    def __init__(self):
        self.webhook_url = settings.BITRIX24_WEBHOOK_URL

    async def create_daily_report_task(
        self,
        date_str: str,
        user_name: str,
        records: List[Tuple[Position, float]],
        raw_text: str = ""
    ) -> Tuple[bool, str]:
        """
        Создает задачу в Битрикс24 (tasks.task.add) с отчетом о выполненных работах.
        """
        if not records:
            return False, "Список позиций пуст."

        desc_lines = [
            f"[B]Ежедневный отчет мастера ({user_name}) за {date_str}[/B]\n",
            f"[B]Исходное сообщение мастера:[/B] \"{raw_text}\"\n",
            "[B]Выполненные объемы:[/B]"
        ]
        
        for idx, (pos, vol) in enumerate(records, 1):
            desc_lines.append(f"{idx}. {pos.name} — [B]{vol} {pos.unit}[/B] (Раздел: {pos.section})")

        description = "\n".join(desc_lines)
        title = f"Дневной отчет о выполненных работах ({date_str}) — {user_name}"

        if not settings.has_bitrix24_credentials:
            logger.info(f"[MOCK Bitrix24] Task would be created: {title}\n{description}")
            return True, f"Зафиксировано в локальном режиме (эмуляция Битрикс24, задача '{title}')"

        url = self.webhook_url.rstrip('/') + "/tasks.task.add.json"
        payload = {
            "fields": {
                "TITLE": title,
                "DESCRIPTION": description,
                "RESPONSIBLE_ID": settings.BITRIX24_RESPONSIBLE_ID,
                "TAGS": ["отчет_прораба", "стройплощадка", "М100"]
            }
        }

        lan_transport = _get_lan_transport()
        transports_to_try = [lan_transport, None] if lan_transport else [None]

        last_error = None
        for transport in transports_to_try:
            try:
                async with httpx.AsyncClient(transport=transport, timeout=12.0) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    task_id = data.get("result", {}).get("task", {}).get("id") or data.get("result", "")
                    logger.info(f"Created Bitrix24 task id: {task_id}")
                    return True, f"Задача в Битрикс24 успешно создана (ID: {task_id})"
            except Exception as e:
                last_error = e
                logger.warning(f"Bitrix24 attempt with transport {transport} failed: {e}")

        logger.error(f"Failed to create Bitrix24 task: {last_error}", exc_info=True)
        return False, f"Ошибка при обращении к Битрикс24: {str(last_error)}"


bitrix_client = Bitrix24Client()
