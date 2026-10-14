"""
RGPV timetable scraper using requests + BeautifulSoup (no browser needed).

Standalone usage:
    python scraper.py
    python scraper.py --program B.Tech --program MBA
    python scraper.py --out my.json
"""

import argparse
import json
import logging
import re
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.rgpv.ac.in"
TT_PAGE = f"{BASE_URL}/Uni/frm_ViewTT.aspx"
PROGRAM_FIELD = "ctl00$ContentPlaceHolder1$drpProgram"
REQUEST_DELAY = 0.5  # seconds between requests, to go easy on the RGPV server

logger = logging.getLogger("rgpv_scraper")


def hidden_fields(soup):
    """ASP.NET hidden form fields (__VIEWSTATE, __EVENTVALIDATION, ...)."""
    return {
        inp["name"]: inp.get("value", "")
        for inp in soup.select("input[type=hidden]")
        if inp.get("name")
    }


def normalize_semester(text):
    """'4 th Semester' -> '4th Semester', matching the IDs in sent_timetables.json."""
    return re.sub(r"(\d+)\s+(st|nd|rd|th)\b", r"\1\2", " ".join(text.split()))


def to_absolute_url(relative):
    """Make a relative site URL absolute, with spaces encoded as %20."""
    path = relative.replace("../", "/", 1) if relative.startswith("../") else relative
    if not path.startswith("http"):
        path = BASE_URL + ("" if path.startswith("/") else "/") + path
    return path.replace(" ", "%20")


class RGPVScraper:
    def __init__(self, timeout=30):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
        self.timeout = timeout

    def _get(self):
        r = self.session.get(TT_PAGE, timeout=self.timeout)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")

    def _postback(self, soup, event_target, program_id):
        data = hidden_fields(soup)
        data["__EVENTTARGET"] = event_target
        data["__EVENTARGUMENT"] = ""
        data[PROGRAM_FIELD] = program_id
        time.sleep(REQUEST_DELAY)
        r = self.session.post(TT_PAGE, data=data, timeout=self.timeout)
        r.raise_for_status()
        return r.text

    def get_programs(self):
        """Return ([(program_id, program_name), ...], page soup)."""
        soup = self._get()
        select = soup.find("select", {"name": PROGRAM_FIELD})
        if select is None:
            raise RuntimeError("Program dropdown not found; the RGPV page layout may have changed")
        return [
            (opt["value"], opt.get_text(strip=True))
            for opt in select.find_all("option")
            if opt.get("value") and opt["value"] not in ("0", "-1", "")
        ], soup

    def get_program_timetables(self, start_soup, program_id):
        """Return [{title, semester, url}, ...] for one program."""
        program_html = self._postback(start_soup, PROGRAM_FIELD, program_id)
        program_soup = BeautifulSoup(program_html, "html.parser")

        grid = program_soup.select_one("#ContentPlaceHolder1_gvViewAct")
        if grid is None:
            return []

        results = []
        for link in grid.select("a[id^=ContentPlaceHolder1_gvViewAct_Lbtn_]"):
            index = link["id"].rsplit("_", 1)[-1]
            heading = grid.select_one(f"#ContentPlaceHolder1_gvViewAct_lblHeading_{index}")
            title = " ".join(link.get_text().split())
            semester = normalize_semester(heading.get_text()) if heading else ""

            # href="javascript:__doPostBack('ctl00$...$ctl02$Lbtn','')"
            m = re.search(r"__doPostBack\('([^']+)'", link.get("href", ""))
            if not m:
                logger.warning(f"No postback target for: {title}")
                continue

            click_html = self._postback(program_soup, m.group(1), program_id)
            url_match = re.search(r'window\.open\("([^"]+)"', click_html)
            if not url_match:
                logger.warning(f"No PDF URL for: {title}")
                continue

            results.append({
                "title": title,
                "semester": semester,
                "url": to_absolute_url(url_match.group(1)),
            })
        return results

    def scrape(self, only_programs=None):
        """Scrape all (or only the given) programs in the rgpv_timetables.json format."""
        programs, start_soup = self.get_programs()
        logger.info(f"Found {len(programs)} programs")

        wanted = {p.lower() for p in only_programs} if only_programs else None
        data = []
        for program_id, program_name in programs:
            if wanted and program_name.lower() not in wanted:
                continue
            try:
                timetables = self.get_program_timetables(start_soup, program_id)
            except requests.RequestException as e:
                logger.error(f"Failed to fetch {program_name}: {e}")
                timetables = []
            logger.info(f"{program_name}: {len(timetables)} timetables")
            data.append({
                "programName": program_name,
                "programId": int(program_id) if program_id.isdigit() else program_id,
                "programDataList": timetables,
            })
        return data


def main():
    parser = argparse.ArgumentParser(description="RGPV timetable scraper (no Selenium)")
    parser.add_argument("--program", action="append", help="Only scrape this program (repeatable)")
    parser.add_argument("--out", default="rgpv_timetables_test.json", help="Output JSON file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    start = time.time()
    data = RGPVScraper().scrape(args.program)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    total = sum(len(p["programDataList"]) for p in data)
    logger.info(f"Done: {total} timetables, {len(data)} programs, {time.time() - start:.1f}s -> {args.out}")


if __name__ == "__main__":
    main()
