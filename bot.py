import os
import sqlite3
import asyncio
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError


# ==================================
# 1. BOT SETTINGS
# ==================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    "bot-data/bot.db"
)

DELETE_AFTER_SECONDS = 30


if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable missing!")

if ADMIN_ID == 0:
    print("WARNING: ADMIN_ID set nahi hai. Admin commands kaam nahi karengi.")


# ==================================
# 2. DATABASE CONNECTION
# ==================================

def get_connection():

    Path(DATABASE_PATH).parent.mkdir(
        parents=True,
        exist_ok=True
    )

    return sqlite3.connect(DATABASE_PATH)


# ==================================
# 3. CREATE DATABASE TABLE
# ==================================

def init_database():

    with get_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS media (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                channel_message_id INTEGER UNIQUE,

                media_type TEXT NOT NULL,

                file_id TEXT NOT NULL,

                caption TEXT

            )
        """)

    print("Database ready!")


# ==================================
# 4. SAVE PHOTO OR VIDEO
# ==================================

def save_media(message, media_type, file_id):

    with get_connection() as conn:

        conn.execute("""
            INSERT OR IGNORE INTO media

            (
                channel_message_id,
                media_type,
                file_id,
                caption
            )

            VALUES (?, ?, ?, ?)

        """, (
            message.message_id,
            media_type,
            file_id,
            message.caption
        ))


# ==================================
# 5. GET ALL MEDIA
# ==================================

def get_all_media():

    with get_connection() as conn:

        return conn.execute("""
            SELECT id, media_type, file_id, caption

            FROM media

            ORDER BY id ASC

        """).fetchall()


# ==================================
# 6. CHANNEL UPLOAD HANDLER
# ==================================

async def channel_media_handler(update, context):

    message = update.channel_post

    if not message:
        return

    if message.chat_id != CHANNEL_ID:
        return

    if message.photo:

        save_media(
            message,
            "photo",
            message.photo[-1].file_id
        )

        print("SUCCESS: Photo saved!")

    elif message.video:

        save_media(
            message,
            "video",
            message.video.file_id
        )

        print("SUCCESS: Video saved!")

    elif message.document:

        mime = message.document.mime_type or ""

        if mime.startswith("image/") or mime.startswith("video/"):

            save_media(
                message,
                "document",
                message.document.file_id
            )

            print("SUCCESS: Media document saved!")

        else:

            print("Unsupported document type.")


# ==================================
# 7. DELETE SENT MESSAGE AFTER 30 SEC
# ==================================

async def delete_later(bot, chat_id, message_id):

    await asyncio.sleep(DELETE_AFTER_SECONDS)

    try:

        await bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )

        print("Sent media deleted after 30 seconds.")

    except TelegramError as error:

        print("Auto delete error:", error)


# ==================================
# 8. SEND ALL MEDIA
# ==================================

async def send_all_media(update, context):

    chat_id = update.effective_chat.id

    media_list = get_all_media()

    if not media_list:

        await update.effective_message.reply_text(
            "Abhi koi saved photo/video nahi hai."
        )

        return

    await update.effective_message.reply_text(
        f"Total {len(media_list)} photos/videos bheji ja rahi hain."
    )

    for media_id, media_type, file_id, caption in media_list:

        try:

            if media_type == "photo":

                sent = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=file_id,
                    caption=caption
                )

            elif media_type == "video":

                sent = await context.bot.send_video(
                    chat_id=chat_id,
                    video=file_id,
                    caption=caption
                )

            else:

                sent = await context.bot.send_document(
                    chat_id=chat_id,
                    document=file_id,
                    caption=caption
                )

            asyncio.create_task(
                delete_later(
                    context.bot,
                    chat_id,
                    sent.message_id
                )
            )

            await asyncio.sleep(0.5)

        except TelegramError as error:

            print(
                f"Media ID {media_id} send error:",
                error
            )


# ==================================
# 9. START COMMAND
# ==================================

async def start(update, context):

    await send_all_media(update, context)


# ==================================
# 10. VIDEO COMMAND
# ==================================

async def video(update, context):

    await send_all_media(update, context)


# ==================================
# 11. ADMIN CHECK
# ==================================

def is_admin(update):

    return (
        ADMIN_ID != 0
        and update.effective_user
        and update.effective_user.id == ADMIN_ID
    )


# ==================================
# 12. LIST ALL MEDIA
# ==================================

async def list_media(update, context):

    if not is_admin(update):

        await update.message.reply_text(
            "Aapko is command ki permission nahi hai."
        )

        return

    media_list = get_all_media()

    if not media_list:

        await update.message.reply_text(
            "Database mein koi media nahi hai."
        )

        return

    text = "SAVED PHOTOS AND VIDEOS\n\n"

    for media_id, media_type, file_id, caption in media_list:

        item = (
            f"ID: {media_id}\n"
            f"Type: {media_type}\n"
            f"Caption: {caption or 'No caption'}\n\n"
        )

        if len(text) + len(item) > 3500:

            await update.message.reply_text(text)

            text = ""

        text += item

    if text:

        await update.message.reply_text(text)


# ==================================
# 13. DELETE ONE MEDIA
# ==================================

async def delete_media(update, context):

    if not is_admin(update):

        await update.message.reply_text(
            "Aapko delete permission nahi hai."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "Use: /delete 5\n"
            "Example: /delete 10"
        )

        return

    try:

        media_id = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "Sahi media ID enter karein."
        )

        return

    with get_connection() as conn:

        cursor = conn.execute(
            "DELETE FROM media WHERE id = ?",
            (media_id,)
        )

    if cursor.rowcount > 0:

        await update.message.reply_text(
            f"Media ID {media_id} database se delete ho gayi."
        )

    else:

        await update.message.reply_text(
            "Ye media ID database mein nahi mili."
        )


# ==================================
# 14. DELETE ALL MEDIA
# ==================================

async def delete_all_media(update, context):

    if not is_admin(update):

        await update.message.reply_text(
            "Aapko permission nahi hai."
        )

        return

    with get_connection() as conn:

        cursor = conn.execute(
            "DELETE FROM media"
        )

        deleted_count = cursor.rowcount

    await update.message.reply_text(
        f"Total {deleted_count} media entries delete ho gayi."
    )


# ==================================
# 15. MAIN FUNCTION
# ==================================

def main():

    init_database()

    app = Application.builder().token(BOT_TOKEN).build()

    # User commands

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("video", video)
    )

    # Admin commands

    app.add_handler(
        CommandHandler("list", list_media)
    )

    app.add_handler(
        CommandHandler("delete", delete_media)
    )

    app.add_handler(
        CommandHandler("deleteall", delete_all_media)
    )

    # Channel photo/video handler

    app.add_handler(
        MessageHandler(
            filters.ChatType.CHANNEL
            & (
                filters.PHOTO
                | filters.VIDEO
                | filters.Document.ALL
            ),
            channel_media_handler
        )
    )

    print("Telegram Bot Running...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ==================================
# 16. RUN BOT
# ==================================

if __name__ == "__main__":

    main()