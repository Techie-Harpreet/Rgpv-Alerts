import asyncio
import json
import logging
import os
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from scraper import BASE_URL, RGPVScraper

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Logs (and JSON state when R2 is not configured) live here
DATA_DIR = os.getenv("DATA_DIR") or BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)

# Stored JSON documents
TIMETABLES = "rgpv_timetables.json"
SENT_TIMETABLES = "sent_timetables.json"
SENT_NOTICES = "sent_notices.json"

# Cloudflare R2; when configured, JSON state is kept in the bucket instead of DATA_DIR.
# Endpoint comes from R2_ENDPOINT (https://<account-id>.r2.cloudflarestorage.com) or R2_ACCOUNT_ID.
_account_id = os.getenv("R2_ACCOUNT_ID")
R2_ENDPOINT = (os.getenv("R2_ENDPOINT") or (f"https://{_account_id}.r2.cloudflarestorage.com" if _account_id else "")).rstrip("/")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET_NAME") or os.getenv("R2_BUCKET")
R2_PREFIX = os.getenv("R2_PREFIX", "rgpv-alerts/")
USE_R2 = all([R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET])

_r2 = None


class StorageError(Exception):
    """Stored state exists but could not be read or written."""


def _r2_client():
    global _r2
    if _r2 is None:
        import boto3
        from botocore.config import Config

        _r2 = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name="auto",
            config=Config(connect_timeout=10, read_timeout=30, retries={"max_attempts": 3}),
        )
    return _r2


def storage_location():
    return f"R2 bucket {R2_BUCKET}/{R2_PREFIX}" if USE_R2 else DATA_DIR


def _bundled(name, default):
    """Copy shipped with the code, used to seed empty storage so old items aren't re-sent."""
    path = os.path.join(BASE_DIR, name)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def load_json(name, default):
    """Load a stored document; missing -> bundled copy or default.

    Raises StorageError when the document exists but can't be read, so callers skip
    the check instead of treating everything as new.
    """
    if USE_R2:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            body = _r2_client().get_object(Bucket=R2_BUCKET, Key=R2_PREFIX + name)["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return _bundled(name, default)
            raise StorageError(f"R2 read failed for {name}: {e}") from e
        except BotoCoreError as e:
            raise StorageError(f"R2 read failed for {name}: {e}") from e
    else:
        path = os.path.join(DATA_DIR, name)
        if not os.path.exists(path):
            return _bundled(name, default)
        with open(path, "rb") as f:
            body = f.read()

    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise StorageError(f"{name} is not valid JSON: {e}") from e


def save_json(name, data):
    """Save a document to R2 or DATA_DIR. Raises StorageError on failure."""
    body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    if USE_R2:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            _r2_client().put_object(
                Bucket=R2_BUCKET, Key=R2_PREFIX + name, Body=body, ContentType="application/json"
            )
        except (BotoCoreError, ClientError) as e:
            raise StorageError(f"R2 write failed for {name}: {e}") from e
        return

    # Write via a temp file so a crash mid-write can't corrupt the target
    path = os.path.join(DATA_DIR, name)
    try:
        with open(f"{path}.tmp", "wb") as f:
            f.write(body)
        os.replace(f"{path}.tmp", path)
    except OSError as e:
        raise StorageError(f"Write failed for {path}: {e}") from e


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

    try:
        save_json(TIMETABLES, data)
    except StorageError as e:
        logger.warning(f"Could not save timetables cache: {e}")
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
