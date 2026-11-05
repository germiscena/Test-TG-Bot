import pytest
from src.bot.bot import create_dispatcher, create_bot


def test_bot_and_dispatcher_creation():
    bot = create_bot()
    assert bot is not None
    dp = create_dispatcher()
    assert dp is not None
    # Check that routers are included
    assert len(dp.sub_routers) == 4
