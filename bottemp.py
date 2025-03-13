import asyncio
import aiohttp
import json
import os
import logging
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackContext
from dotenv import load_dotenv
from urllib.parse import quote

# Load environment variables
load_dotenv()

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
API_URL = "https://api.rgpvnotes.in/timetable"
SENT_TIMETABLES_FILE = "sent_timetables.json"

def encode_url(url):
    """Encode URL spaces to %20"""
    return quote(url, safe=':/')

# # Logging setup
# logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot_logs.log", encoding="utf-8"),  # Log file to save logs
        logging.StreamHandler()  # Also logs to console
    ]
)
logger = logging.getLogger(__name__)

class TimetableManager:
    def __init__(self):
        self.sent_timetables = self.load_sent_timetables()

    def load_sent_timetables(self):
        if os.path.exists(SENT_TIMETABLES_FILE):
            try:
                with open(SENT_TIMETABLES_FILE, "r") as file:
                    return json.load(file)
            except json.JSONDecodeError:
                logger.error("Failed to decode sent timetables file. Starting fresh.")
        return []

    def save_sent_timetables(self):
        try:
            with open(SENT_TIMETABLES_FILE, "w") as file:
                json.dump(self.sent_timetables, file)
        except IOError as e:
            logger.error(f"Failed to save sent timetables: {e}")

async def send_message(bot, message, parse_mode="HTML"):
    logger.info(f"Sending message to group: {message[:100]}...")  # Log only first 100 chars
    try:
        await bot.send_message(chat_id=GROUP_ID, text=message, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        try:
            await bot.send_message(chat_id=GROUP_ID, text=message)
        except Exception as e2:
            logger.error(f"Failed to send plain message too: {e2}")

async def check_for_new_timetables(context: CallbackContext):
    """Check for new timetables and send notifications"""
    logger.info("Checking for new timetables...")
    manager = context.application.manager  # Access the manager from application context

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"API Response: Found {len(data)} programs")

                    bot = context.bot  # Use the bot from context
                    new_timetables = []

                    for program in data:
                        program_name = program.get("programName", "N/A")
                        program_data_list = program.get("programDataList", [])
                        
                        logger.info(f"Processing program: {program_name} with {len(program_data_list)} timetables")
                        
                        for timetable in program_data_list:
                            url = timetable.get('url', '')
                            semester = timetable.get('semester', '')
                            title = timetable.get('title', '')

                            
                            # Enhanced unique ID including title
                            unique_id = f"{program_name}_{semester}_{title}_{url}"
                            logger.debug(f"Checking timetable with unique ID: {unique_id}")
                            
                            if unique_id not in manager.sent_timetables:
                                new_timetables.append((program_name, timetable))
                                manager.sent_timetables.append(unique_id)
                                logger.info(f"New timetable found: {unique_id}")

                    if new_timetables:
                        logger.info(f"New timetables found: {len(new_timetables)}")
                        for program_name, timetable in new_timetables:
                            await asyncio.sleep(5)  # Delay to avoid rate limiting
                            encoded_url = quote(timetable.get('url', 'N/A'))
                            print("Url before message", (timetable.get('url')))
                            # Get the URL
                            original_url = timetable.get('url', 'N/A')

                            # Create HTML link
                            html_link = f'<a href="{original_url}">{original_url}</a>'
                            # message = (
                            message = (
                                f"📅 <b>New Time Table Alert!</b>\n\n"
                                f"📚 <b>Program:</b> {program_name}\n"
                                f"📖 <b>Title:</b> {timetable.get('title', 'N/A')}\n"
                                f"📆 <b>Semester:</b> {timetable.get('semester', 'N/A')}\n"
                                f"🔗 <b>Link:</b> {html_link}"  # HTML Link
                            )

                            # )
                            print("New Bot Url : ",f"🔗 *Link:* {encode_url(timetable.get('url', 'N/A'))}")
                            print("Url After message", (timetable.get('url')))
                            await send_message(bot, message, parse_mode="HTML")

                        manager.save_sent_timetables()
                    else:
                        logger.info("No new timetables found.")
                else:
                    logger.error(f"Failed to fetch data. Status Code: {response.status}")
    except Exception as e:
        logger.error(f"Error: {e}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /status command to check if the bot is running."""
    await update.message.reply_text("✅ Bot is running and active!")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    await update.message.reply_text("🤖 RGPV Timetable Alert Bot has started! Use /status to check if I'm running.")

async def manual_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /check command to manually check for new timetables."""
    await update.message.reply_text("🔍 Checking for new timetables...")
    await check_for_new_timetables(context)
    await update.message.reply_text("✅ Check completed!")

async def reset_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /reset command to clear sent timetables data"""
    manager = context.application.manager
    manager.sent_timetables = []
    manager.save_sent_timetables()
    await update.message.reply_text("🗑️ All sent timetable records have been reset. Next check will treat all timetables as new.")

def main():
    """Run the bot without conflicting event loops"""
    logger.info("Bot is starting...")

    # Initialize manager
    manager = TimetableManager()
    
    # Initialize the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Store the manager in application to make it accessible in context
    application.manager = manager
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("check", manual_check))
    application.add_handler(CommandHandler("reset", reset_data))
    
    # Schedule periodic checks using the application's job queue
    application.job_queue.run_repeating(check_for_new_timetables, interval=15*60)  # 15 minutes
    
    # Run initial check when the bot starts
    application.job_queue.run_once(check_for_new_timetables, 0)
    
    # Start the Bot
    logger.info("Starting polling...")
    application.run_polling()

if __name__ == "__main__":
    main()