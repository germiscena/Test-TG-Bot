import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import asyncio
import logging
import httpx
from config.settings import settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("verifier")


async def check_telegram():
    print("\n--- 1. Проверка Telegram Bot ---")
    if not settings.TELEGRAM_BOT_TOKEN or "mock" in settings.TELEGRAM_BOT_TOKEN:
        print("⚠️ Токен Telegram не настроен или тестовый.")
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getMe"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json().get("result", {})
                print(f"✅ Telegram Bot подключен! Имя бота: @{data.get('username')} ({data.get('first_name')})")
                return True
            else:
                print(f"❌ Ошибка Telegram токена: {resp.text}")
                return False
    except Exception as e:
        print(f"❌ Не удалось подключиться к Telegram API: {e}")
        return False


async def check_google_sheets():
    print("\n--- 2. Проверка Google Sheets ---")
    if not settings.has_google_credentials:
        print("ℹ️ Google Sheets: режим локальной эмуляции (service_account.json или GOOGLE_SPREADSHEET_ID не настроены).")
        return True

    try:
        import gspread
        gc = gspread.service_account(filename=settings.GOOGLE_SERVICE_ACCOUNT_FILE)
        sh = gc.open_by_key(settings.GOOGLE_SPREADSHEET_ID)
        worksheet = sh.worksheet(settings.GOOGLE_SHEET_NAME)
        rows = worksheet.get_all_values()
        print(f"✅ Google Таблица успешно подключена!")
        print(f"   Название таблицы: «{sh.title}»")
        print(f"   Лист: «{worksheet.title}», строк: {len(rows)}")
        return True
    except Exception as e:
        print(f"❌ Ошибка доступа к Google Sheets: {e}")
        print("   Проверьте, выдан ли доступ сервисному аккаунту с правами 'Редактор'.")
        return False


async def check_bitrix24():
    print("\n--- 3. Проверка Битрикс24 ---")
    if not settings.has_bitrix24_credentials:
        print("ℹ️ Битрикс24: режим локальной эмуляции (BITRIX24_WEBHOOK_URL не настроен).")
        return True

    url = settings.BITRIX24_WEBHOOK_URL.rstrip('/') + "/user.current.json"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                user = resp.json().get("result", {})
                name = f"{user.get('NAME', '')} {user.get('LAST_NAME', '')}".strip() or user.get("EMAIL", "Admin")
                print(f"✅ Вебхук Битрикс24 работает! Авторизован как: {name} (ID: {user.get('ID')})")
                return True
            else:
                print(f"❌ Битрикс24 вернул ошибку {resp.status_code}: {resp.text}")
                print("   Проверьте правильность URL вебхука и права доступа (tasks, user).")
                return False
    except Exception as e:
        print(f"❌ Не удалось соединиться с Битрикс24: {e}")
        return False


async def check_openai():
    print("\n--- 4. Проверка OpenAI / LLM ---")
    if not settings.has_openai_credentials:
        print("ℹ️ OpenAI: используется встроенный офлайн-парсер сленга (ключ не указан).")
        return True

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    try:
        resp = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5
        )
        print(f"✅ OpenAI API доступен! Модель: {settings.OPENAI_MODEL}")
        return True
    except Exception as e:
        print(f"⚠️ OpenAI вернул ошибку ({e}). Бот продолжит работу через локальный офлайн-парсер.")
        return False


async def main():
    print("========================================")
    print("   ДИАГНОСТИКА ПОДКЛЮЧЕНИЙ БОТА (М-100) ")
    print("========================================")
    await check_telegram()
    await check_google_sheets()
    await check_bitrix24()
    await check_openai()
    print("\n========================================")
    print("Диагностика завершена.")


if __name__ == "__main__":
    asyncio.run(main())
