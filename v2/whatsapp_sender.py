"""
Scrape RGPV every CHECK_INTERVAL seconds and send new timetables and notices to
WhatsApp channels through the WAHA API (https://waha.devlike.pro).

Timetables go one message per program; notices are batched. Items are marked sent
only when WAHA answers 2xx, so failed deliveries are retried on the next check.

Usage:
    python whatsapp_sender.py          # run forever
    python whatsapp_sender.py --once   # single check, then exit
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

import requests

from helper import (
    DATA_DIR, SENT_NOTICES, SENT_TIMETABLES, TIMETABLES, StorageError, convert_aspx_to_pdf_url,
    load_json, save_json, storage_location,
)
from notices import NOTICE_PAGE, NoticeScraper, notice_id
from scraper import RGPVScraper


WAHA_URL = os.getenv("WAHA_URL", "").rstrip("/")
WAHA_API_KEY = os.getenv("WAHA_API_KEY")
WAHA_SESSION = os.getenv("WAHA_SESSION")  # optional; default: every WORKING session
WHATSAPP_CHAT_ID = os.getenv("WHATSAPP_CHAT_ID")  # optional; default: every channel you are ADMIN of
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "7200"))  # seconds
NOTICES_LOOKBACK_DAYS = int(os.getenv("NOTICES_LOOKBACK_DAYS") or 60)  # ignore notices older than this
NOTICES_PER_MESSAGE = 10
SEND_DELAY = 5  # seconds between messages

logger = logging.getLogger("whatsapp_sender")


def load_sent_ids(name):
    """Sent list, or None if it can't be read (the check is skipped rather than re-sending everything)."""
    try:
        return load_json(name, [])
    except StorageError as e:
        logger.error(f"Skipping check, cannot read {name}: {e}")
        return None


def mark_sent(name, sent_ids):
    """Persist the sent list; False if that failed (stop sending to avoid duplicates)."""
    try:
        save_json(name, sent_ids)
        return True
    except StorageError as e:
        logger.error(f"Stopping, cannot save {name}: {e}")
        return False


def find_new_timetables(data, sent_ids):
    """Return {program_name: [(timetable, unique_id), ...]} for timetables not yet sent."""
    sent = set(sent_ids)
    new = {}
    for program in data:
        program_name = program.get("programName", "N/A")
        for timetable in program.get("programDataList", []):
            unique_id = (
                f"{program_name}_{timetable.get('semester', '')}_"
                f"{timetable.get('title', '')}_{timetable.get('url', '')}"
            )
            if unique_id not in sent:
                new.setdefault(program_name, []).append((timetable, unique_id))
    return new


def whatsapp_message(program_name, timetables):
    """WhatsApp text: *bold*, plain links."""
    lines = [f"📢 *New Time Table Update – {program_name}*", ""]
    for index, t in enumerate(timetables, 1):
        lines.append(f"{index}. 📖 *{t['title']}*")
        if t["semester"]:
            lines.append(f"   📆 {t['semester']}")
        lines += [f"   🔗 {t['url']}", ""]
    return "\n".join(lines).strip()


def notices_message(notices):
    lines = ["📰 *New RGPV Notice*" if len(notices) == 1 else "📰 *New RGPV Notices*", ""]
    for index, n in enumerate(notices, 1):
        prefix = f"{index}. " if len(notices) > 1 else ""
        lines += [f"{prefix}📖 *{n['title']}*", f"   📅 {n['date']}", f"   🔗 {n['url']}", ""]
    return "\n".join(lines).strip()


def waha(method, path, **kwargs):
    headers = {"X-Api-Key": WAHA_API_KEY} if WAHA_API_KEY else {}
    r = requests.request(method, f"{WAHA_URL}{path}", headers=headers, timeout=30, **kwargs)
    if not r.ok:
        # 422 usually means the session is not WORKING (re-scan the QR / restart the session)
        raise requests.HTTPError(f"{r.status_code} {method} {path}: {r.text[:300]}", response=r)
    return r.json() if r.content else None


def get_targets():
    """[(session, chat_id), ...]: WORKING sessions -> channels where we are ADMIN."""
    if WAHA_SESSION:
        sessions = [WAHA_SESSION]
    else:
        sessions = [s["name"] for s in waha("GET", "/api/sessions") if s.get("status") == "WORKING"]
    if not sessions:
        return []
    if WHATSAPP_CHAT_ID:
        return [(sessions[0], WHATSAPP_CHAT_ID)]

    targets = {}  # chat_id -> session, so a channel shared by two sessions gets one message
    for session in sessions:
        for channel in waha("GET", f"/api/{session}/channels", params={"role": "ADMIN"}):
            targets.setdefault(channel["id"], session)
    return [(session, chat_id) for chat_id, session in targets.items()]


def send_whatsapp(session, chat_id, text):
    try:
        waha("POST", "/api/sendText", json={"session": session, "chatId": chat_id, "text": text})
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to send to {chat_id}: {e}")
        return False


def resolve_targets():
    """get_targets() with logging; returns [] when nothing can be sent."""
    try:
        targets = get_targets()
    except requests.RequestException as e:
        logger.error(f"Could not get WAHA sessions/channels: {e}")
        return []
    if not targets:
        logger.error("No WORKING WAHA session or ADMIN channel found; nothing sent")
        return []
    logger.info(f"Sending to: {', '.join(chat_id for _, chat_id in targets)}")
    return targets


def send_to_all(targets, text):
    return all([send_whatsapp(session, chat_id, text) for session, chat_id in targets])


def check_timetables():
    logger.info("Scraping RGPV timetables...")
    try:
        data = RGPVScraper().scrape()
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        return
    if not data:
        logger.warning("Scraper returned no programs")
        return
    try:
        save_json(TIMETABLES, data)
    except StorageError as e:
        logger.warning(f"Could not save timetables cache: {e}")

    sent_ids = load_sent_ids(SENT_TIMETABLES)
    if sent_ids is None:
        return
    new = find_new_timetables(data, sent_ids)
    if not new:
        logger.info("No new timetables found.")
        return
    logger.info(f"New timetables found: {sum(len(v) for v in new.values())}")

    targets = resolve_targets()
    if not targets:
        return

    for program_name, items in new.items():
        timetables = [
            {
                "title": t.get("title", ""),
                "semester": t.get("semester", ""),
                "url": convert_aspx_to_pdf_url(t.get("url", "")),
            }
            for t, _ in items
        ]
        if send_to_all(targets, whatsapp_message(program_name, timetables)):
            sent_ids.extend(uid for _, uid in items)
            if not mark_sent(SENT_TIMETABLES, sent_ids):
                return
            logger.info(f"Sent {len(items)} timetables for {program_name}")
        else:
            logger.error(f"Not marking {program_name} timetables as sent; will retry next check")
        time.sleep(SEND_DELAY)


def check_notices():
    since = datetime.now().date() - timedelta(days=NOTICES_LOOKBACK_DAYS)
    logger.info(f"Scraping RGPV notices since {since}...")
    scraper = NoticeScraper()
    try:
        notices = scraper.list_notices(since)
    except Exception as e:
        logger.error(f"Notice scraping failed: {e}")
        return

    sent_ids = load_sent_ids(SENT_NOTICES)
    if sent_ids is None:
        return
    sent = set(sent_ids)
    new, seen = [], set()
    for n in reversed(notices):  # oldest first, so the channel reads in order
        uid = notice_id(n)
        if uid not in sent and uid not in seen:
            seen.add(uid)
            new.append(n)
    if not new:
        logger.info("No new notices found.")
        return
    logger.info(f"New notices found: {len(new)}")

    targets = resolve_targets()
    if not targets:
        return

    for start in range(0, len(new), NOTICES_PER_MESSAGE):
        batch = new[start:start + NOTICES_PER_MESSAGE]
        for n in batch:
            try:
                url = scraper.get_pdf_url(n)
            except requests.RequestException as e:
                logger.warning(f"Could not get PDF link for {n['title']!r}: {e}")
                url = None
            n["url"] = convert_aspx_to_pdf_url(url) if url else NOTICE_PAGE

        if send_to_all(targets, notices_message(batch)):
            sent_ids.extend(notice_id(n) for n in batch)
            if not mark_sent(SENT_NOTICES, sent_ids):
                return
            logger.info(f"Sent {len(batch)} notices")
        else:
            logger.error(f"Not marking {len(batch)} notices as sent; will retry next check")
        time.sleep(SEND_DELAY)


def run_check():
    check_timetables()
    check_notices()


def main():
    parser = argparse.ArgumentParser(description="Send new RGPV timetables and notices to WhatsApp via WAHA")
    parser.add_argument("--once", action="store_true", help="Run a single check and exit")
    args = parser.parse_args()

    logging.Formatter.converter = time.localtime
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            RotatingFileHandler(os.path.join(DATA_DIR, "whatsapp_sender.log"), maxBytes=5_000_000, backupCount=3, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    if not WAHA_URL:
        sys.exit("Set WAHA_URL in .env (see .env.example)")

    logger.info(f"State is kept in {storage_location()}")
    if args.once:
        run_check()
        return

    logger.info(f"Starting; checking every {CHECK_INTERVAL}s")
    while True:
        run_check()
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
