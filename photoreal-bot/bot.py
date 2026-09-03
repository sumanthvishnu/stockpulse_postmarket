#!/usr/bin/env python3
"""Private Telegram bot: send up to 10 photos at once, convert every one."""

from __future__ import annotations

import asyncio
import logging
import os
from io import BytesIO

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from generate import PromptBlocked, generate_batch, image_from_bytes, jpeg_batch, load_pipeline
from presets import DEFAULT_STRENGTH, MAX_PHOTOS, PRESETS, STRENGTHS

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("photoreal")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED = os.environ.get("ALLOWED_USER_ID", "").strip()
ALBUM_WAIT_SEC = 2.2

gpu_lock = asyncio.Lock()
_album_tasks: dict[str, asyncio.Task] = {}


def _allowed(user_id: int | None) -> bool:
    if not ALLOWED:
        return False
    return str(user_id) == str(ALLOWED)


def _photos(context: ContextTypes.DEFAULT_TYPE) -> list[bytes]:
    return context.user_data.setdefault("photos", [])


def _preset_keyboard() -> InlineKeyboardMarkup:
    rows, row = [], []
    for key, spec in PRESETS.items():
        row.append(InlineKeyboardButton(spec["title"], callback_data=f"p:{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Keep likeness", callback_data="s:keep"),
                InlineKeyboardButton("Restyle", callback_data="s:restyle"),
            ],
            [
                InlineKeyboardButton("Again (all photos)", callback_data="again"),
                InlineKeyboardButton("Clear queue", callback_data="clear"),
            ],
        ]
    )


def _queue_text(n: int, extra: str = "") -> str:
    extra_line = f"\nCaption: {extra}" if extra else ""
    if n >= MAX_PHOTOS:
        return (
            f"Got {n}/{MAX_PHOTOS} photos (max). Pick a preset to convert all of them."
            f"{extra_line}"
        )
    return (
        f"Got {n}/{MAX_PHOTOS} photos. Send more as an album (or one by one), "
        f"or pick a preset to convert all of them."
        f"{extra_line}"
    )


async def _reject(update: Update) -> None:
    if update.message:
        await update.message.reply_text("This bot is private.")
    elif update.callback_query:
        await update.callback_query.answer("This bot is private.", show_alert=True)


async def _send_queue_prompt(bot, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    n = len(_photos(context))
    extra = context.user_data.get("extra", "")
    text = _queue_text(n, extra)
    msg_id = context.user_data.get("prompt_msg_id")
    if msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=_preset_keyboard(),
            )
            return
        except Exception:
            pass
    sent = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=_preset_keyboard(),
    )
    context.user_data["prompt_msg_id"] = sent.message_id


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await _reject(update)
        return
    await update.message.reply_text(
        "Personal photoreal bot. Adults only.\n\n"
        f"Send up to {MAX_PHOTOS} photos at once (Telegram album), or one by one.\n"
        "Optional caption = extra prompt.\n"
        "Then tap a preset — every photo is converted, 1:1.\n\n"
        "/clear — empty the queue"
    )


async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await _reject(update)
        return
    context.user_data["photos"] = []
    context.user_data["extra"] = ""
    context.user_data.pop("prompt_msg_id", None)
    await update.message.reply_text("Queue cleared. Send up to 10 photos.")


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await _reject(update)
        return

    photos = _photos(context)
    if len(photos) >= MAX_PHOTOS:
        await update.message.reply_text(
            f"Already {MAX_PHOTOS} photos queued. Pick a preset or /clear."
        )
        return

    photo = update.message.photo[-1]
    tf = await photo.get_file()
    buf = BytesIO()
    await tf.download_to_memory(buf)
    photos.append(buf.getvalue())

    caption = (update.message.caption or "").strip()
    if caption:
        context.user_data["extra"] = caption
    context.user_data.setdefault("strength", DEFAULT_STRENGTH)

    mgid = update.message.media_group_id
    chat_id = update.effective_chat.id
    if not mgid:
        await _send_queue_prompt(context.bot, chat_id, context)
        return

    # Album: Telegram delivers 10 photos as 10 messages. Wait until the
    # group stops arriving, then send one "got N photos" message.
    key = f"{update.effective_user.id}:{mgid}"
    old = _album_tasks.get(key)
    if old:
        old.cancel()

    async def _flush_album() -> None:
        try:
            await asyncio.sleep(ALBUM_WAIT_SEC)
            await _send_queue_prompt(context.bot, chat_id, context)
        except asyncio.CancelledError:
            return
        finally:
            _album_tasks.pop(key, None)

    _album_tasks[key] = asyncio.create_task(_flush_album())


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await _reject(update)
        return
    if not _photos(context):
        await update.message.reply_text(
            f"Send up to {MAX_PHOTOS} photos first (album is best), then a preset."
        )
        return
    context.user_data["extra"] = update.message.text.strip()
    await _send_queue_prompt(context.bot, update.effective_chat.id, context)


async def _run_job(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photos = list(_photos(context))
    if not photos:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Send photos first (up to 10 at once).",
        )
        return

    preset_id = context.user_data.get("preset", "studio")
    strength_id = context.user_data.get("strength", DEFAULT_STRENGTH)
    extra = context.user_data.get("extra", "")
    spec = PRESETS.get(preset_id, PRESETS["studio"])
    strength = STRENGTHS.get(strength_id, STRENGTHS[DEFAULT_STRENGTH])["value"]
    prompt = spec["prompt"]
    n = len(photos)
    chat_id = update.effective_chat.id

    status = await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"Converting 0/{n} · {spec['title']} · {STRENGTHS[strength_id]['title']}\n"
            "Each photo is converted. Album comes back when all are done."
        ),
    )

    results: list[bytes] = []
    try:
        async with gpu_lock:
            for i, raw in enumerate(photos, start=1):
                try:
                    await status.edit_text(
                        f"Converting {i}/{n} · {spec['title']} · "
                        f"{STRENGTHS[strength_id]['title']}"
                    )
                except Exception:
                    pass

                def _work(photo_bytes=raw):
                    image = image_from_bytes(photo_bytes)
                    return generate_batch(
                        image=image,
                        prompt=prompt,
                        extra=extra,
                        strength=strength,
                        count=1,
                    )

                frames = await asyncio.to_thread(_work)
                results.extend(jpeg_batch(frames))

        media = []
        for i, jpeg in enumerate(results):
            bio = BytesIO(jpeg)
            bio.name = f"gen_{i}.jpg"
            media.append(InputMediaPhoto(bio))
        # Telegram albums are max 10 — matches our queue cap.
        await context.bot.send_media_group(chat_id=chat_id, media=media)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Done — {n} photo{'s' if n != 1 else ''} converted. "
            "Same queue is still loaded:",
            reply_markup=_result_keyboard(),
        )
        try:
            await status.delete()
        except Exception:
            pass
    except PromptBlocked as exc:
        await status.edit_text(str(exc))
    except Exception:
        log.exception("generation failed")
        note = f" Got {len(results)}/{n} before the error." if results else ""
        await status.edit_text(
            "Generation failed. Check the GPU terminal log." + note
        )
        if results:
            media = []
            for i, jpeg in enumerate(results):
                bio = BytesIO(jpeg)
                bio.name = f"gen_{i}.jpg"
                media.append(InputMediaPhoto(bio))
            await context.bot.send_media_group(chat_id=chat_id, media=media)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _allowed(update.effective_user.id):
        await _reject(update)
        return
    await query.answer()
    raw = query.data or ""

    if raw == "clear":
        context.user_data["photos"] = []
        context.user_data["extra"] = ""
        context.user_data.pop("prompt_msg_id", None)
        await query.edit_message_text("Queue cleared. Send up to 10 photos.")
        return

    if raw.startswith("p:"):
        key = raw.split(":", 1)[1]
        if key not in PRESETS:
            return
        context.user_data["preset"] = key
        await _run_job(update, context)
        return

    if raw.startswith("s:"):
        key = raw.split(":", 1)[1]
        if key not in STRENGTHS:
            return
        context.user_data["strength"] = key
        await _run_job(update, context)
        return

    if raw == "again":
        await _run_job(update, context)


def main() -> None:
    if not TOKEN or not ALLOWED:
        raise SystemExit(
            "Missing TELEGRAM_BOT_TOKEN or ALLOWED_USER_ID. "
            "Run scripts/setup_pod.sh so it can write .env"
        )

    log.info("Preloading Z-Image-Turbo (first time downloads the model)...")
    load_pipeline()
    log.info("Bot is ready")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
