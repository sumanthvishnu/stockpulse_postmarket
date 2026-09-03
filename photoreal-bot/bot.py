#!/usr/bin/env python3
"""Private Telegram bot: send a photo, pick a preset, get a photoreal batch."""

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
from presets import BATCH_CHOICES, DEFAULT_BATCH, DEFAULT_STRENGTH, PRESETS, STRENGTHS

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("photoreal")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED = os.environ.get("ALLOWED_USER_ID", "").strip()
gpu_lock = asyncio.Lock()


def _allowed(user_id: int | None) -> bool:
    if not ALLOWED:
        return False
    return str(user_id) == str(ALLOWED)


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
                InlineKeyboardButton("Again", callback_data="again"),
                InlineKeyboardButton("Batch of 8", callback_data="b:8"),
            ],
        ]
    )


async def _reject(update: Update) -> None:
    if update.message:
        await update.message.reply_text("This bot is private.")
    elif update.callback_query:
        await update.callback_query.answer("This bot is private.", show_alert=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await _reject(update)
        return
    await update.message.reply_text(
        "Personal photoreal bot. Adults only.\n\n"
        "Send a photo. Optional caption = extra prompt.\n"
        "Then tap a preset. Default batch is 4."
    )


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await _reject(update)
        return
    photo = update.message.photo[-1]
    tf = await photo.get_file()
    buf = BytesIO()
    await tf.download_to_memory(buf)
    context.user_data["photo"] = buf.getvalue()
    context.user_data["extra"] = (update.message.caption or "").strip()
    context.user_data["strength"] = DEFAULT_STRENGTH
    context.user_data["batch"] = DEFAULT_BATCH
    extra = context.user_data["extra"]
    note = f"\nCaption: {extra}" if extra else ""
    await update.message.reply_text(
        "Photo saved. Pick a preset." + note,
        reply_markup=_preset_keyboard(),
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await _reject(update)
        return
    if not context.user_data.get("photo"):
        await update.message.reply_text("Send a photo first, then a preset.")
        return
    context.user_data["extra"] = update.message.text.strip()
    await update.message.reply_text(
        "Got the extra prompt. Pick a preset (or tap Again after a run).",
        reply_markup=_preset_keyboard(),
    )


async def _run_job(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.user_data
    photo = data.get("photo")
    if not photo:
        target = update.effective_message
        await target.reply_text("Send a photo first.")
        return

    preset_id = data.get("preset", "studio")
    strength_id = data.get("strength", DEFAULT_STRENGTH)
    count = int(data.get("batch", DEFAULT_BATCH))
    extra = data.get("extra", "")
    spec = PRESETS.get(preset_id, PRESETS["studio"])
    strength = STRENGTHS.get(strength_id, STRENGTHS[DEFAULT_STRENGTH])["value"]
    prompt = spec["prompt"]

    status = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            f"Generating {count} · {spec['title']} · {STRENGTHS[strength_id]['title']}\n"
            "Usually 30–90 seconds."
        ),
    )

    try:
        async with gpu_lock:
            image = image_from_bytes(photo)

            def _work():
                return generate_batch(
                    image=image,
                    prompt=prompt,
                    extra=extra,
                    strength=strength,
                    count=count,
                )

            frames = await asyncio.to_thread(_work)
        jpegs = jpeg_batch(frames)
        media = []
        for i, jpeg in enumerate(jpegs):
            bio = BytesIO(jpeg)
            bio.name = f"gen_{i}.jpg"
            media.append(InputMediaPhoto(bio))
        await context.bot.send_media_group(
            chat_id=update.effective_chat.id,
            media=media,
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Done. Send another photo, or reuse this one:",
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
        await status.edit_text(
            "Generation failed. Check the GPU terminal log. "
            "If it says CUDA/OOM, try batch of 2."
        )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _allowed(update.effective_user.id):
        await _reject(update)
        return
    await query.answer()
    raw = query.data or ""

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
        context.user_data["batch"] = context.user_data.get("batch", DEFAULT_BATCH)
        await _run_job(update, context)
        return

    if raw.startswith("b:"):
        n = int(raw.split(":", 1)[1])
        if n not in BATCH_CHOICES:
            return
        context.user_data["batch"] = n
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
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
