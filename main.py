"""
main.py - Entry point. Run: python main.py
"""

import logging
import sys

from telegram import BotCommand
from telegram.ext import Application, ApplicationBuilder

from config import BOT_TOKEN, LOG_FILE, LOG_LEVEL
from handlers import register_handlers

def setup_logging() -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
        ],
    )
    for lib in ("httpx", "httpcore", "telegram", "urllib3"):
        logging.getLogger(lib).setLevel(logging.WARNING)


BOT_COMMANDS = [
    BotCommand("start",  "👋 Welcome message"),
    BotCommand("help",   "ℹ️ Show all commands"),
    BotCommand("play",   "▶️ Search & play a song"),
    BotCommand("search", "🔍 Browse top 5 results"),
    BotCommand("pause",  "⏸ Pause the queue"),
    BotCommand("resume", "▶️ Resume the queue"),
    BotCommand("stop",   "⏹ Stop & clear queue"),
    BotCommand("queue",  "📋 View the queue"),
]


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)
    me = await application.bot.get_me()
    logging.info("Bot running as @%s", me.username)


def main() -> None:
    setup_logging()
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .concurrent_updates(True)
        .build()
    )
    register_handlers(app)
    app.run_polling(poll_interval=1.0, timeout=20, drop_pending_updates=True)


if __name__ == "__main__":
    main()
