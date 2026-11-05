import os
import sqlite3
import asyncio
import logging

from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =====================================
# ENVIRONMENT VARIABLES
# =====================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

DATABASE_PATH = os.getenv("DATABASE_PATH", "bot-data/bot.db")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN Render Environment Variables mein set karein.")

if CHANNEL_ID == 0:
    raise ValueError("CHANNEL_ID Render Environment Variables mein set karein.")

# =====================================
# LOGGING
# =====================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# =====================================
# DATABASE
# =====================================

def get_connection():
    folder = os.path.dirname(DATABASE_PATH)

    if folder:
        os.makedirs(folder, exist_ok=True)

    return sqlite3.connect(DATABASE_PATH)


def create_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            caption TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_media(file_id, media_type, caption):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO media (file_id, media_type, caption)
        VALUES (?, ?, ?)
        """,
        (file_id, media_type, caption),
    )

    conn.commit()
    conn.close()


# =====================================
# ADMIN CHECK
# =====================================

def is_admin(user_id):
    return ADMIN_ID != 0 and user_id == ADMIN_ID


# =====================================
# AUTO DELETE MESSAGE AFTER 30 SECONDS
# =====================================

async def delete_later(bot, chat_id, message_id):
    await asyncio.sleep(30)

    try:
        await bot.delete_message(
            chat_id=chat_id,
            message_id=message_id,
        )
    except TelegramError as error:
        logger.warning("Message delete nahi hua: %s", error)


# =====================================
# HEALTH CHECK SERVER FOR RENDER
# =====================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Telegram Bot is Running!")

    def log_message(self, format, *args):
        pass


def run_health_server():
    port = int(os.environ.get("PORT", 10000))

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler,
    )

    logger.info("Health server running on port %s", port)

    server.serve_forever()


# =====================================
# START COMMAND
# =====================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Welcome! 👋\n\n"
        "Video dekhne ke liye /video command bhejein.\n"
        "Help ke liye /help command bhejein."
    )


# =====================================
# HELP COMMAND
# =====================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Bot Commands:\n\n"
        "/start - Bot start karein\n"
        "/video - Saved media dekhein\n"
        "/help - Help message\n\n"
        "Admin Commands:\n"
        "/list - Saved media ki list\n"
        "/delete ID - Ek media delete karein\n"
        "/deleteall - Saare saved media delete karein"
    )


# =====================================
# CHANNEL MEDIA SAVE
# =====================================

async def save_channel_media(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.channel_post

    if not message:
        return

    # Sirf selected channel ka media save hoga
    if message.chat_id != CHANNEL_ID:
        return

    file_id = None
    media_type = None

    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"

    elif message.video:
        file_id = message.video.file_id
        media_type = "video"

    elif message.document:
        mime_type = message.document.mime_type or ""

        if mime_type.startswith("image/"):
            file_id = message.document.file_id
            media_type = "document"

        elif mime_type.startswith("video/"):
            file_id = message.document.file_id
            media_type = "document"

    if file_id and media_type:
        save_media(
            file_id=file_id,
            media_type=media_type,
            caption=message.caption,
        )

        logger.info("Channel se media save hua: %s", media_type)


# =====================================
# VIDEO COMMAND
# =====================================

async def video(update: Update, context: ContextTypes.DEFAULT_TYPE):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, file_id, media_type, caption FROM media ORDER BY id ASC"
    )

    media_list = cursor.fetchall()
    conn.close()

    if not media_list:
        await update.message.reply_text(
            "Abhi koi media saved nahi hai."
        )
        return

    await update.message.reply_text(
        f"Total {len(media_list)} media mil gaye. Sending..."
    )

    for media_id, file_id, media_type, caption in media_list:

        try:
            sent_message = None

            if media_type == "photo":
                sent_message = await update.message.reply_photo(
                    photo=file_id,
                    caption=caption,
                )

            elif media_type == "video":
                sent_message = await update.message.reply_video(
                    video=file_id,
                    caption=caption,
                )

            elif media_type == "document":
                sent_message = await update.message.reply_document(
                    document=file_id,
                    caption=caption,
                )

            if sent_message:
                asyncio.create_task(
                    delete_later(
                        context.bot,
                        sent_message.chat_id,
                        sent_message.message_id,
                    )
                )

        except TelegramError as error:
            logger.warning(
                "Media ID %s send nahi hua: %s",
                media_id,
                error,
            )


# =====================================
# LIST COMMAND - ADMIN ONLY
# =====================================

async def list_media(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Aapko permission nahi hai.")
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, media_type, caption FROM media ORDER BY id DESC LIMIT 50"
    )

    media_list = cursor.fetchall()
    conn.close()

    if not media_list:
        await update.message.reply_text("Database mein koi media nahi hai.")
        return

    response = "Saved Media List:\n\n"

    for media_id, media_type, caption in media_list:
        caption_text = caption or "No caption"

        response += (
            f"ID: {media_id}\n"
            f"Type: {media_type}\n"
            f"Caption: {caption_text[:50]}\n\n"
        )

    await update.message.reply_text(response)


# =====================================
# DELETE COMMAND - ADMIN ONLY
# =====================================

async def delete_media(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Aapko permission nahi hai.")
        return

    if not context.args:
        await update.message.reply_text(
            "Use karein: /delete ID\nExample: /delete 5"
        )
        return

    try:
        media_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Sahi media ID enter karein.")
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM media WHERE id = ?", (media_id,))

    deleted = cursor.rowcount

    conn.commit()
    conn.close()

    if deleted:
        await update.message.reply_text(
            f"Media ID {media_id} database se delete ho gaya."
        )
    else:
        await update.message.reply_text("Ye media ID nahi mili.")


# =====================================
# DELETE ALL COMMAND - ADMIN ONLY
# =====================================

async def delete_all(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Aapko permission nahi hai.")
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM media")

    deleted = cursor.rowcount

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"Database se {deleted} media records delete ho gaye."
    )


# =====================================
# MAIN FUNCTION
# =====================================

def main():

    create_database()

    # Render Web Service ke liye health server
    health_thread = Thread(
        target=run_health_server,
        daemon=True,
    )

    health_thread.start()

    # Telegram bot application
    app = Application.builder().token(BOT_TOKEN).build()

    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("video", video))

    # Admin commands
    app.add_handler(CommandHandler("list", list_media))
    app.add_handler(CommandHandler("delete", delete_media))
    app.add_handler(CommandHandler("deleteall", delete_all))

    # Channel media handler
    app.add_handler(
        MessageHandler(
            filters.ALL,
            save_channel_media,
        )
    )

    logger.info("Telegram Bot start ho raha hai...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =====================================
# RUN BOT
# =====================================

if __name__ == "__main__":
    main()
