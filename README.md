# RGPV Timetable Alert Bot

## 📌 Overview
RGPV Timetable Alert Bot is a **Telegram bot** that automatically checks for new **timetables** on the RGPV website and sends alerts to a Telegram group. It uses **SeleniumBase** for web scraping and **Python Telegram Bot API** for sending messages.

## 🚀 Features
- ✅ **Automated Timetable Detection**: Scrapes timetables from `https://api.rgpvnotes.in/timetable`.
- 🔔 **Telegram Notifications**: Sends alerts to a configured Telegram group.
- 🔄 **Automatic Checking**: Runs every 55 minutes to check for updates.
- 🐂 **Persistent Storage**: Keeps track of already sent timetables to avoid duplicates.
- 🛠 **Manual Commands**: Supports commands like `/check`, `/reset`, `/status`, and `/start`.

---

## 🫠 Installation & Setup
### 1⃣ Clone the Repository
```bash
git clone https://github.com/Techie-Harpreet/Rgpv-Alerts.git
cd Rgpv-Alerts-main
```

### 2⃣ Create a Virtual Environment (Optional but Recommended)
```bash
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
```

### 3⃣ Install Dependencies
```bash
pip install -r requirements.txt
```

### 4⃣ Set Up Environment Variables
Create a `.env` file in the root directory and add the following:
```ini
BOT_TOKEN="your-telegram-bot-token"
GROUP_ID="your-telegram-group-id"
```

### 5⃣ Run the Bot
```bash
python bot.py
```

#### ▶️ Run in Headless Mode
If you want to run the bot in **headless mode**, use the following command:
```bash
python bot.py --headless
```

---

## 🐜 Available Commands
| Command       | Description |
|--------------|-------------|
| `/start`     | Start the bot |
| `/status`    | Check if the bot is running |
| `/check`     | Manually check for new timetables |
| `/reset`     | Clear sent timetable records |

---

## 🫠 Tech Stack
- **Python** 🐍
- **SeleniumBase** 🚀 (for web automation)
- **Python Telegram Bot API** 🤖
- **dotenv** 📁 (for environment variables)
- **asyncio** ⏳ (for async operations)

---

## 🖼 Screenshots

![Timetable Alert]([https://raw.githubusercontent.com/Techie-Harpreet/Rgpv-Alerts/refs/heads/main/Images/Screenshot%202025-03-14%20145848.png?token=GHSAT0AAAAAAC7V2MOFI72UYPJRGDBLZWPYZ6T66CQ](https://raw.githubusercontent.com/Techie-Harpreet/Rgpv-Alerts/refs/heads/main/Images/Screenshot%202025-03-14%20145848.png))

---

## 📞 Live Bot
Join the Telegram channel for live alerts:
[![Telegram](https://img.shields.io/badge/Telegram-Join%20Channel-blue)](https://t.me/rgpv_alerts)

**Channel Link:** [https://t.me/rgpv_alerts](https://t.me/rgpvupdates)

---

## 📬 Contributing
1. Fork the repository 🍴
2. Create a new branch: `git checkout -b feature-name`
3. Make changes and commit: `git commit -m "Added a new feature"`
4. Push changes: `git push origin feature-name`
5. Open a **Pull Request** 🚀

---

## 🐝 License
This project is licensed under the **MIT License**.

---

## ✨ Author
Developed by **[Harpreet]**

---

## 📲 Contact
For any issues or suggestions, feel free to reach out:
📧 Email: contact@harpreetsinghbansal.com


