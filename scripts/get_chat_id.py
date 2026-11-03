"""Print the Telegram chat ID of whoever last messaged the bot.

Usage:
    read -rs TELEGRAM_BOT_TOKEN && export TELEGRAM_BOT_TOKEN
    python3 scripts/get_chat_id.py

The token is read from the environment only. It is never printed, and errors
are reported without the request URL (which contains the token).
"""

import json
import os
import sys
import urllib.request


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set.", file=sys.stderr)
        return 1

    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.load(resp)
    except Exception as exc:  # urllib errors include the URL; report the type only
        print(f"Request to Telegram failed ({type(exc).__name__}).", file=sys.stderr)
        return 1

    if not data.get("ok"):
        print("Telegram rejected the request. Check the token.", file=sys.stderr)
        return 1

    chat_ids = []
    for update in data.get("result", []):
        msg = update.get("message") or update.get("edited_message") or {}
        chat_id = msg.get("chat", {}).get("id")
        if chat_id is not None and chat_id not in chat_ids:
            chat_ids.append(chat_id)

    if not chat_ids:
        print("No messages found. Send any message to your bot, then run this again.", file=sys.stderr)
        return 1

    print(chat_ids[-1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
