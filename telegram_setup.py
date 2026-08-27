#!/usr/bin/env python3
"""Print your Telegram chat id (for the TELEGRAM_CHAT_ID secret).

Usage:
    python telegram_setup.py <BOT_TOKEN>

Steps: create the bot with @BotFather first, then send your bot a message
(e.g. "hi") in Telegram, then run this to get the numeric chat id.
"""
import sys

import requests


def main():
    token = sys.argv[1] if len(sys.argv) > 1 else input("Bot token: ").strip()
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
    data = r.json()
    if not data.get("ok"):
        print("Error:", data)
        return
    ids = set()
    for u in data.get("result", []):
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat", {})
        if chat.get("id"):
            ids.add(chat["id"])
    if not ids:
        print("No chats found. Send your bot a message in Telegram "
              "(e.g. 'hi'), then run this again.")
        return
    print("Chat id(s) found:")
    for i in sorted(ids):
        print(" ", i)
    print("\nUse the numeric id as the TELEGRAM_CHAT_ID secret in GitHub.")


if __name__ == "__main__":
    main()
