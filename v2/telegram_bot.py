import asyncio
import json
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

from telegram import Update
from telegram.ext import Application, CallbackContext, CommandHandler, ContextTypes

from helper import DATA_DIR, SENT_TIMETABLES_FILE, TIMETABLES_FILE, convert_aspx_to_pdf_url, get_time_tables_link, write_json_atomic


# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "7200"))  # seconds
# Telegram user IDs allowed to use /check and /reset; empty means everyone
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

# Use local time for log timestamps
logging.Formatter.converter = time.localtime

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler(os.path.join(DATA_DIR, "bot_logs.log"), maxBytes=5_000_000, backupCount=3, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# httpx logs request URLs, which contain the bot token
logging.getLogger("httpx").setLevel(logging.WARNING)


class TimetableManager:
    def __init__(self):
        self.sent_timetables = self.load_sent_timetables()

    def load_sent_timetables(self):
        if os.path.exists(SENT_TIMETABLES_FILE):
            try:
                with open(SENT_TIMETABLES_FILE, "r", encoding="utf-8") as file:
                    return json.load(file)
            except json.JSONDecodeError:
                logger.error("Failed to decode sent timetables file. Starting fresh.")
        return []

    def save_sent_timetables(self):
        try:
            write_json_atomic(SENT_TIMETABLES_FILE, self.sent_timetables)
        except OSError as e:
            logger.error(f"Failed to save sent timetables: {e}")


async def send_message(bot, message, parse_mode="HTML", disable_web_page_preview=True):
    """Send to the group, falling back to plain text. Returns True on success."""
    logger.info(f"Sending message to group: {message[:100]}...")
    try:
        await bot.send_message(chat_id=GROUP_ID, text=message, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview)
        return True
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        try:
            await bot.send_message(chat_id=GROUP_ID, text=message, disable_web_page_preview=disable_web_page_preview)
            return True
        except Exception as e2:
            logger.error(f"Failed to send plain message too: {e2}")
            return False


async def check_for_new_timetables(context: CallbackContext):
    """Check for new timetables from the local JSON file"""
    logger.info("Checking for new timetables from file...")
    manager = context.application.manager
    # Reload data from file before each check
    manager.sent_timetables = manager.load_sent_timetables()
    sent_ids = set(manager.sent_timetables)

    if not os.path.exists(TIMETABLES_FILE):
        logger.error(f"File not found: {TIMETABLES_FILE}")
        return

    try:
        with open(TIMETABLES_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError:
        logger.error("Failed to parse JSON from file")
        return

    logger.info(f"Found {len(data)} programs in the file")

    # Identify new timetables, grouped by program
    program_grouped = {}
    for program in data:
        program_name = program.get("programName", "N/A")
        for timetable in program.get("programDataList", []):
            url = timetable.get('url', '')
            semester = timetable.get('semester', '')
            title = timetable.get('title', '')

            unique_id = f"{program_name}_{semester}_{title}_{url}"
            if unique_id not in sent_ids:
                program_grouped.setdefault(program_name, []).append((timetable, unique_id))
                logger.info(f"New timetable found: {unique_id}")

    if not program_grouped:
        logger.info("No new timetables found.")
        return

    logger.info(f"New timetables found: {sum(len(v) for v in program_grouped.values())}")

    for program_name, timetables_with_ids in program_grouped.items():
        header = (
            f"📢 <b>New Time Table Update – {program_name}</b>\n\n"
            f"<b>Available Timetables:</b>\n"
        )

        # Split long lists to stay under Telegram's 4096-character limit
        chunks = []  # [(message_lines, unique_ids), ...]
        lines, ids, length = [header], [], len(header)
        for index, (timetable, unique_id) in enumerate(timetables_with_ids, 1):
            url = convert_aspx_to_pdf_url(timetable.get('url', 'N/A'))
            title = timetable.get('title', 'N/A')
            semester = timetable.get('semester', 'N/A')

            entry = (
                f"{index}. 📖 <b>Title:</b> {title}\n"
                f"   📆 <b>Semester:</b> {semester}\n"
                f'   <a href="{url}">🔗 View Timetable</a>\n'
            )
            if ids and length + len(entry) + 1 > 4000:
                chunks.append((lines, ids))
                lines, ids, length = [header], [], len(header)
            lines.append(entry)
            ids.append(unique_id)
            length += len(entry) + 1
        chunks.append((lines, ids))

        for lines, ids in chunks:
            if await send_message(context.bot, "\n".join(lines)):
                manager.sent_timetables.extend(ids)
                manager.save_sent_timetables()
                logger.info(f"Successfully sent and saved {len(ids)} timetables for {program_name}")
            else:
                logger.error(f"Not marking {len(ids)} {program_name} timetables as sent; will retry next check")

            await asyncio.sleep(5)


async def get_time_tables_link_then_timetable(context: ContextTypes.DEFAULT_TYPE):
    await get_time_tables_link(context)
    await check_for_new_timetables(context)


def is_admin(update: Update):
    return not ADMIN_IDS or (update.effective_user and update.effective_user.id in ADMIN_IDS)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /status command to check if the bot is running."""
    await update.message.reply_text("✅ Bot is running and active!")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    await update.message.reply_text("🤖 RGPV Timetable Alert Bot has started! Use /status to check if I'm running.")


async def manual_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /check command: scrape RGPV and send any new timetables."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Only admins can use this command.")
        return
    await update.message.reply_text("🔍 Checking for new timetables...")
    await get_time_tables_link_then_timetable(context)
    await update.message.reply_text("✅ Check completed!")


async def reset_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /reset command to clear sent timetables data"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Only admins can use this command.")
        return
    manager = context.application.manager
    manager.sent_timetables = []
    manager.save_sent_timetables()
    await update.message.reply_text("🗑️ All sent timetable records have been reset. Next check will treat all timetables as new.")


def main():
    if not BOT_TOKEN or not GROUP_ID:
        sys.exit("Set BOT_TOKEN and GROUP_ID in .env (see .env.example)")

    logger.info("Bot is starting...")

    application = Application.builder().token(BOT_TOKEN).build()
    application.manager = TimetableManager()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("check", manual_check))
    application.add_handler(CommandHandler("reset", reset_data))

    # First check immediately, then every CHECK_INTERVAL seconds
    application.job_queue.run_repeating(get_time_tables_link_then_timetable, interval=CHECK_INTERVAL, first=0)

    logger.info(f"Starting polling... (check every {CHECK_INTERVAL}s)")
    application.run_polling()


if __name__ == "__main__":
    main()
