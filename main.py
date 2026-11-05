import asyncio
import sys
from src.bot.bot import run_bot


def main():
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        print("\nБот остановлен пользователем.")


if __name__ == "__main__":
    main()
