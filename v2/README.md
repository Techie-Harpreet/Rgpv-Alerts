# RGPV Time Table Alerts v2

Posts new RGPV exam timetables and notices to a WhatsApp channel (via WAHA) or a Telegram group (timetables only). Scrapes the RGPV site with `requests` + `BeautifulSoup` (no Selenium/browser).

## Files
| File | Purpose |
|---|---|
| `scraper.py` | Scrapes timetables for all programs from `/Uni/frm_ViewTT.aspx` |
| `notices.py` | Lists notices from `/Uni/ImpNoticeArchive.aspx`; fetches PDF links only for new ones |
| `helper.py` | Runs the scraper, updates `rgpv_timetables.json`, builds direct PDF links |
| `whatsapp_sender.py` | Checks every `CHECK_INTERVAL` seconds and sends new timetables and notices to your WhatsApp channels via WAHA |
| `telegram_bot.py` | Same, but posts to a Telegram group |
| `sent_timetables.json` / `sent_notices.json` | IDs already posted (kept in `DATA_DIR`) |

## Setup
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # set WAHA_* and WHATSAPP_CHAT_ID (and/or BOT_TOKEN, GROUP_ID)
```

## Run
```bash
python scraper.py --program B.Tech   # scraper only (writes rgpv_timetables_test.json)
python notices.py --days 60          # list recent notices
python whatsapp_sender.py --once     # one check, then exit
python whatsapp_sender.py            # run forever
python telegram_bot.py               # Telegram bot
```

Run only one of `whatsapp_sender.py` / `telegram_bot.py`: they share `sent_timetables.json`.

## WhatsApp
Targets are found like this (unless `WAHA_SESSION` / `WHATSAPP_CHAT_ID` are set):
`GET /api/sessions` (WORKING only) → `GET /api/{session}/channels?role=ADMIN` → `POST /api/sendText` to each channel.
Timetables: one message per program. Notices: only the last `NOTICES_LOOKBACK_DAYS` days, oldest first, 10 per message.
Items are marked sent only when every channel accepted the message.
A `422` from WAHA usually means the session is not `WORKING` (re-scan the QR or restart the session).

## Telegram commands
- `/start`, `/status` — check the bot is running
- `/check` — scrape and post new timetables now (admin)
- `/reset` — clear the sent list; everything is re-posted on the next check (admin)
