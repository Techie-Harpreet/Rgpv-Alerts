import asyncio
import json
import logging
import os
import shutil
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from scraper import BASE_URL, RGPVScraper

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# State and logs live here; point it at a persistent volume when running in Docker
DATA_DIR = os.getenv("DATA_DIR") or BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)
TIMETABLES_FILE = os.path.join(DATA_DIR, "rgpv_timetables.json")
SENT_TIMETABLES_FILE = os.path.join(DATA_DIR, "sent_timetables.json")

# Seed an empty volume with the bundled sent list so old timetables aren't re-sent
_bundled_sent = os.path.join(BASE_DIR, "sent_timetables.json")
if not os.path.exists(SENT_TIMETABLES_FILE) and os.path.exists(_bundled_sent):
    shutil.copy(_bundled_sent, SENT_TIMETABLES_FILE)


def write_json_atomic(path, data):
    """Write via a temp file so a crash mid-write can't corrupt the target."""
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


async def get_time_tables_link(context=None):
    """Scrape RGPV and update rgpv_timetables.json; the old file is kept on failure."""
    logger.info("Starting to fetch timetable links...")
    try:
        data = await asyncio.to_thread(RGPVScraper().scrape)
    except Exception as e:
        logger.error(f"Scraping failed, keeping old timetables file: {e}")
        return False

    if not data:
        logger.warning("Scraper returned no programs, keeping old timetables file")
        return False

    write_json_atomic(TIMETABLES_FILE, data)
    total = sum(len(p["programDataList"]) for p in data)
    logger.info(f"Saved {total} timetables from {len(data)} programs")
    return True


def convert_aspx_to_pdf_url(url):
    """'.../frm_download_file.aspx?Filepath=CDN/.../x.pdf' -> direct '.../CDN/.../x.pdf' link."""
    try:
        filepath = parse_qs(urlparse(url).query).get("Filepath", [None])[0]
    except ValueError:
        return url
    if not filepath:
        return url
    return f"{BASE_URL}/{filepath.lstrip('/')}".replace(" ", "%20")
