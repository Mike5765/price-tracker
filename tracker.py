import requests
import sqlite3
import schedule
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, PRODUCTS, CHECK_INTERVAL

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def init_db():
    conn = sqlite3.connect("prices.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT,
            price REAL,
            checked_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_last_price(product_name):
    conn = sqlite3.connect("prices.db")
    row = conn.execute(
        "SELECT price FROM price_history WHERE product_name = ? ORDER BY checked_at DESC LIMIT 1",
        (product_name,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def save_price(product_name, price):
    conn = sqlite3.connect("prices.db")
    conn.execute(
        "INSERT INTO price_history (product_name, price, checked_at) VALUES (?, ?, ?)",
        (product_name, price, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def scrape_price(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, "lxml")

        # Try the main price span Amazon uses
        price_whole = soup.select_one("span.a-price-whole")
        price_fraction = soup.select_one("span.a-price-fraction")

        if price_whole:
            whole = price_whole.get_text(strip=True).replace(",", "").replace(".", "")
            fraction = price_fraction.get_text(strip=True) if price_fraction else "00"
            return float(f"{whole}.{fraction}")

        # Fallback: search for any price-like text
        price_tag = soup.select_one("#priceblock_ourprice, #priceblock_dealprice, .a-offscreen")
        if price_tag:
            text = price_tag.get_text(strip=True)
            match = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
            if match:
                return float(match.group())

    except Exception as e:
        print(f"[ERROR] Failed to scrape {url}: {e}")

    return None


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}")


def check_prices():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking prices...")
    for product in PRODUCTS:
        name = product["name"]
        url = product["url"]
        price = scrape_price(url)

        if price is None:
            print(f"  Could not retrieve price for {name}")
            continue

        last_price = get_last_price(name)
        save_price(name, price)

        print(f"  {name}: ${price:.2f} (was: {'N/A' if last_price is None else f'${last_price:.2f}'})")

        if last_price is None:
            send_telegram(
                f"*Price Tracker Started*\n\n"
                f"*{name}*\n"
                f"Current price: *${price:.2f}*\n"
                f"I'll notify you whenever the price changes."
            )
        elif price < last_price:
            diff = last_price - price
            send_telegram(
                f"*Price Drop!*\n\n"
                f"*{name}*\n"
                f"Was: ${last_price:.2f}\n"
                f"Now: *${price:.2f}*\n"
                f"You save: *${diff:.2f}*\n\n"
                f"[View on Amazon]({url})"
            )
        elif price > last_price:
            diff = price - last_price
            send_telegram(
                f"*Price Increase*\n\n"
                f"*{name}*\n"
                f"Was: ${last_price:.2f}\n"
                f"Now: *${price:.2f}* (+${diff:.2f})\n\n"
                f"[View on Amazon]({url})"
            )


if __name__ == "__main__":
    init_db()
    check_prices()  # Run once immediately on start
    schedule.every(CHECK_INTERVAL).minutes.do(check_prices)
    print(f"Scheduler running — checking every {CHECK_INTERVAL} minutes. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(30)
