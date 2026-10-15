"""
RGPV notice scraper for /Uni/ImpNoticeArchive.aspx.

The archive lists every notice since 2010 on one ~3 MB page, newest first, and each
title is an ASP.NET postback that returns the whole page again. So notices are
listed from the page itself and the PDF link is fetched only for the ones we need.

Standalone usage:
    python notices.py              # notices from the last 60 days
    python notices.py --days 90
"""

import argparse
import logging
import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from scraper import BASE_URL, REQUEST_DELAY, hidden_fields, to_absolute_url

NOTICE_PAGE = f"{BASE_URL}/Uni/ImpNoticeArchive.aspx"
ID_PREFIX = "ContentPlaceHolder1_UcImpNoticeArchive1_GVView_"

logger = logging.getLogger("notices")


def notice_id(notice):
    return f"{notice['date']}_{notice['title']}"


class NoticeScraper:
    def __init__(self, timeout=60):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
        self.timeout = timeout
        self.soup = None

    def list_notices(self, since):
        """Return [{date, title, target}, ...] dated on/after `since` (a date), newest first."""
        r = self.session.get(NOTICE_PAGE, timeout=self.timeout)
        r.raise_for_status()
        self.soup = BeautifulSoup(r.text, "html.parser")

        notices = []
        for date_el in self.soup.select(f"[id^={ID_PREFIX}Date_]"):
            index = date_el["id"].rsplit("_", 1)[-1]
            link = self.soup.select_one(f"#{ID_PREFIX}LbnTitle_{index}")
            date = date_el.get_text(strip=True)
            try:
                notice_date = datetime.strptime(date, "%d/%m/%Y").date()
            except ValueError:
                logger.warning(f"Unparseable notice date {date!r}")
                continue
            if notice_date < since:
                break  # page is sorted newest first
            m = re.search(r"__doPostBack\('([^']+)'", link.get("href", "")) if link else None
            notices.append({
                "date": date,
                "title": " ".join(link.get_text().split()) if link else "",
                "target": m.group(1) if m else None,
            })
        return notices

    def get_pdf_url(self, notice):
        """Click the notice title and return the absolute download URL, or None."""
        if not notice.get("target") or self.soup is None:
            return None
        data = hidden_fields(self.soup)
        data["__EVENTTARGET"] = notice["target"]
        data["__EVENTARGUMENT"] = ""
        time.sleep(REQUEST_DELAY)
        r = self.session.post(NOTICE_PAGE, data=data, timeout=self.timeout)
        r.raise_for_status()
        m = re.search(r'window\.open\("([^"]+)"', r.text)
        return to_absolute_url(m.group(1)) if m else None


def main():
    parser = argparse.ArgumentParser(description="List RGPV notices")
    parser.add_argument("--days", type=int, default=60, help="Only notices from the last N days")
    parser.add_argument("--links", type=int, default=3, help="Fetch PDF links for the newest N notices")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    scraper = NoticeScraper()
    since = datetime.now().date() - timedelta(days=args.days)
    notices = scraper.list_notices(since)
    logger.info(f"{len(notices)} notices since {since}")
    for n in notices[:args.links]:
        print(n["date"], "|", n["title"], "|", scraper.get_pdf_url(n))


if __name__ == "__main__":
    main()
