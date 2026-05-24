"""
bot/handlers.py
All Telegram command handlers.
"""

import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from config import MAX_QUEUE_SIZE, MSG_HELP, MSG_START, MAX_FILE_BYTES
from music_search import cleanup_file, download_track, search_tracks
from queue_manager import Track, registry
logger = logging.getLogger(__name__)


def _make_play_callback(bot, chat_id: int):
    async def _play(track: Track) -> None:
        status_msg = await bot.send_message(
            chat_id=chat_id,
            text=f"⏳ Downloading *{track.title}*…",
        )
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)

        file_path = await download_track(track)
        if not file_path:
            await status_msg.edit_text(
                f"❌ Failed to download *{track.title}*. Skipping.",
                parse_mode=ParseMode.HTML,
            )
            return

        if os.path.getsize(file_path) > MAX_FILE_BYTES:
            await status_msg.edit_text(
                f"⚠️ *{track.title}* is too large to send.",
parse_mode=ParseMode.HTML
            )
            cleanup_file(file_path)
            return

        caption = (
            f"🎵 *{track.title}*\n⏱ {track.duration_str()}"
            + (f"\n👤 Requested by @{track.requested_by}" if track.requested_by else "")
        )

        try:
            with open(file_path, "rb") as audio_file:
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=audio_file,
                    title=track.title,
                    duration=track.duration or None,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                )
        except Exception as exc:
            logger.error("Send audio failed: %s", exc)
            await bot.send_message(chat_id=chat_id,
                text=f"❌ Could not send *{track.title}*", parse_mode=ParseMode.MARKDOWN)
        finally:
            cleanup_file(file_path)
            await status_msg.delete()

    return _play


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(MSG_START, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(MSG_HELP, parse_mode=ParseMode.MARKDOWN)


async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    query = " ".join(context.args).strip()

    if not query:
        await update.message.reply_text(
            "🎵 Usage: `/play <song name>`", parse_mode=ParseMode.MARKDOWN)
        return

    msg = await update.message.reply_text(
        f"🔍 Searching for *{query}*…", parse_mode=ParseMode.MARKDOWN)

    tracks = await search_tracks(query, n=1)
    if not tracks:
        await msg.edit_text(f"😔 No results for *{query}*.", parse_mode=ParseMode.MARKDOWN)
        return

    track = tracks[0]
    track.requested_by = user.username or user.first_name

    play_fn = _make_play_callback(context.bot, chat_id)
    worker = registry.get_or_create(chat_id, play_fn)

    if worker.queue_size() >= MAX_QUEUE_SIZE:
        await msg.edit_text(f"⚠️ Queue full! Use `/stop` to clear.", parse_mode=ParseMode.MARKDOWN)
        return

    position = worker.add(track)
    worker.ensure_running()

    status = "▶️ Playing now!" if position == 1 else f"📋 Added to queue at position #{position}"
    await msg.edit_text(f"{track}\n\n{status}", parse_mode=ParseMode.MARKDOWN)


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("🔍 Usage: `/search <song name>`", parse_mode=ParseMode.MARKDOWN)
        return

    msg = await update.message.reply_text(f"🔍 Searching *{query}*…", parse_mode=ParseMode.MARKDOWN)
    tracks = await search_tracks(query)

    if not tracks:
        await msg.edit_text(f"😔 No results for *{query}*.", parse_mode=ParseMode.MARKDOWN)
        return

    keyboard = []
    for i, track in enumerate(tracks, 1):
        label = f"{i}. {track.title[:40]} [{track.duration_str()}]"
        cb_data = f"play|||{track.url}|||{track.title}|||{track.duration}"
        keyboard.append([InlineKeyboardButton(label, callback_data=cb_data)])

    await msg.edit_text(
        f"🎵 Results for *{query}*\nTap to queue:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def callback_search_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user = update.effective_user

    try:
        _, url, title, duration_str = query.data.split("|||", 3)
        track = Track(title=title, url=url, duration=int(duration_str),
                      requested_by=user.username or user.first_name)
    except (ValueError, AttributeError):
        await query.edit_message_text("❌ Invalid selection.")
        return

    play_fn = _make_play_callback(context.bot, chat_id)
    worker = registry.get_or_create(chat_id, play_fn)
    position = worker.add(track)
    worker.ensure_running()
    await query.edit_message_text(f"✅ Queued: *{title}*\nPosition #{position}", parse_mode=ParseMode.MARKDOWN)


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    worker = registry.get(update.effective_chat.id)
    if not worker or worker.is_paused:
        await update.message.reply_text("⏸ Already paused or nothing playing.")
        return
    worker.pause()
    await update.message.reply_text("⏸ *Queue paused.* Use `/resume` to continue.", parse_mode=ParseMode.MARKDOWN)


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    worker = registry.get(update.effective_chat.id)
    if not worker or not worker.is_paused:
        await update.message.reply_text("▶️ Queue is already running.")
        return
    worker.resume()
    await update.message.reply_text("▶️ *Resumed!*", parse_mode=ParseMode.MARKDOWN)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    worker = registry.get(chat_id)
    if not worker:
        await update.message.reply_text("📭 Nothing is playing.")
        return
    worker.stop()
    registry.remove(chat_id)
    await update.message.reply_text("⏹ *Stopped & queue cleared.*", parse_mode=ParseMode.MARKDOWN)


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    worker = registry.get(update.effective_chat.id)
    if not worker or (not worker.current and worker.queue_size() == 0):
        await update.message.reply_text("📭 Queue is empty. Use `/play` to add songs!")
        return

    lines = ["📋 *Current Queue*\n"]
    if worker.current:
        lines.append(f"▶️ *Now:* {worker.current.title} [{worker.current.duration_str()}]")

    upcoming = worker.queue_list
    if upcoming:
        lines.append("\n*Up Next:*")
        for i, track in enumerate(upcoming, 1):
            req = f" _(by @{track.requested_by})_" if track.requested_by else ""
            lines.append(f"  `{i}.` {track.title} [{track.duration_str()}]{req}")
    else:
        lines.append("\n_No songs waiting._")

    if worker.is_paused:
        lines.append("\n⏸ _Queue is paused – use /resume_")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


def register_handlers(application) -> None:
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("play", cmd_play))
    application.add_handler(CommandHandler("search", cmd_search))
    application.add_handler(CommandHandler("pause", cmd_pause))
    application.add_handler(CommandHandler("resume", cmd_resume))
    application.add_handler(CommandHandler("stop", cmd_stop))
    application.add_handler(CommandHandler("queue", cmd_queue))
    application.add_handler(CallbackQueryHandler(callback_search_pick, pattern=r"^play\|\|\|"))
