"""
config.py - Centralized configuration for the Telegram Music Bot.
All settings are loaded from environment variables with safe defaults.
"""

import os
import logging
from pathlib import Path

# ─────────────────────────────────────────────
#  BOT CREDENTIALS
# ─────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN","8650241437:AAGlv1B3VWlJ8md4auPvpfsMzHGbsmatIsQ")

if not BOT_TOKEN:
    raise EnvironmentError(
        "❌  BOT_TOKEN is not set!\n"
        "    Run:  export BOT_TOKEN='your_token_here'\n"
        "    Then restart the bot."
    )

# ─────────────────────────────────────────────
#  PATHS
# ─────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).parent.resolve()
DOWNLOAD_DIR: Path = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE: Path = BASE_DIR / "bot.log"

# ─────────────────────────────────────────────
#  SETTINGS
# ─────────────────────────────────────────────
MAX_DURATION_SEC: int = int(os.getenv("MAX_DURATION", "600"))
MAX_FILE_BYTES: int = 50 * 1024 * 1024  # 50 MB
SEARCH_RESULTS_COUNT: int = int(os.getenv("SEARCH_RESULTS", "5"))
MAX_QUEUE_SIZE: int = int(os.getenv("MAX_QUEUE", "20"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
YDL_FORMAT: str = "bestaudio/best"
YDL_OUTPUT_TEMPLATE: str = str(DOWNLOAD_DIR / "%(id)s.%(ext)s")

# ─────────────────────────────────────────────
#  BOT MESSAGES
# ─────────────────────────────────────────────
MSG_START = (
    "🎵 *Welcome to Music Bot!*\n\n"
    "I can search and send you music straight inside Telegram.\n\n"
    "Try `/play Bohemian Rhapsody` to get started.\n"
    "Use `/help` to see all commands."
)

MSG_HELP = (
    "🎵 *Music Bot — Commands*\n\n"
    "▶️  `/play <song name>` — Search & queue a song\n"
    "⏸  `/pause` — Pause the current download queue\n"
    "▶️  `/resume` — Resume the download queue\n"
    "⏹  `/stop` — Stop & clear the entire queue\n"
    "📋  `/queue` — Show songs waiting in queue\n"
    "🔍  `/search <song>` — Show top 5 results to choose\n"
    "ℹ️  `/help` — Show this message\n\n"
    "_Songs are sent as Telegram audio files you can play directly._"
)
