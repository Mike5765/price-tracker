import requests
import sqlite3
import schedule
import time
import re
import anthropic
from bs4 import BeautifulSoup
from datetime import datetime
import urllib.parse
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, ANTHROPIC_API_KEY, SCRAPERAPI_KEY, PRODUCTS, CHECK_INTERVAL

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
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


def get_price_history(product_name, limit=10):
    conn = sqlite3.connect("prices.db")
    rows = conn.execute(
        "SELECT price, checked_at FROM price_history WHERE product_name = ? ORDER BY checked_at DESC LIMIT ?",
        (product_name, limit)
    ).fetchall()
    conn.close()
    return rows


def save_price(product_name, price):
    conn = sqlite3.connect("prices.db")
    conn.execute(
        "INSERT INTO price_history (product_name, price, checked_at) VALUES (?, ?, ?)",
        (product_name, price, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def _extract_asin(url):
    match = re.search(r"/dp/([A-Z0-9]{10})", url)
    return match.group(1) if match else None


def _scrape_amazon(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "lxml")

        price_whole = soup.select_one("span.a-price-whole")
        price_fraction = soup.select_one("span.a-price-fraction")

        if price_whole:
            whole = price_whole.get_text(strip=True).replace(",", "").replace(".", "")
            fraction = price_fraction.get_text(strip=True) if price_fraction else "00"
            return float(f"{whole}.{fraction}")

        price_tag = soup.select_one("#priceblock_ourprice, #priceblock_dealprice, .a-offscreen")
        if price_tag:
            text = price_tag.get_text(strip=True)
            match = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
            if match:
                return float(match.group())

    except Exception as e:
        print(f"[ERROR] Amazon scrape failed: {e}")

    return None


def _scrape_camelcamelcamel(asin):
    url = f"https://camelcamelcamel.com/product/{asin}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "lxml")

        # Current price shown in the product price table
        for row in soup.select("table.product_prices tr, #product_prices tr"):
            cells = row.select("td, th")
            if len(cells) >= 2:
                price_text = cells[-1].get_text(strip=True)
                match = re.search(r"\$([\d,]+\.\d{2})", price_text)
                if match:
                    val = float(match.group(1).replace(",", ""))
                    if 5 < val < 10000:
                        return val

        # Fallback: find any price-like link pointing to Amazon
        for a in soup.select("a[href*='amazon.com']"):
            text = a.get_text(strip=True)
            match = re.search(r"\$([\d,]+\.\d{2})", text)
            if match:
                val = float(match.group(1).replace(",", ""))
                if 5 < val < 10000:
                    return val

        # Last resort: scan all text for dollar amounts near "Amazon"
        for tag in soup.select("[class*='price'], [id*='price']"):
            text = tag.get_text(strip=True)
            match = re.search(r"\$([\d,]+\.\d{2})", text)
            if match:
                val = float(match.group(1).replace(",", ""))
                if 5 < val < 10000:
                    return val

    except Exception as e:
        print(f"[ERROR] CamelCamelCamel scrape failed: {e}")

    return None


def _proxied_url(url):
    if SCRAPERAPI_KEY:
        encoded = urllib.parse.quote(url)
        return f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={encoded}"
    return url


def scrape_price(url, **_):
    # When SCRAPERAPI_KEY is set, route through ScraperAPI residential proxies
    # (bypasses Amazon's datacenter IP blocks on GitHub Actions)
    fetch_url = _proxied_url(url)
    source = "ScraperAPI→Amazon" if SCRAPERAPI_KEY else "Amazon"

    price = _scrape_amazon(fetch_url)
    if price:
        print(f"  [source: {source}]")
        return price

    # Fallback: CamelCamelCamel (no proxy needed)
    asin = _extract_asin(url)
    if asin:
        print(f"  Primary unavailable, trying CamelCamelCamel (ASIN: {asin})...")
        price = _scrape_camelcamelcamel(asin)
        if price:
            print(f"  [source: CamelCamelCamel]")
            return price

    return None


def get_ai_analysis(product_name, current_price, history, retail_price=None, tracking_start_price=None):
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        history_text = "\n".join(
            [f"  ${price:.2f} on {checked_at[:10]}" for price, checked_at in history]
        )

        context = ""
        if retail_price:
            context += f"MSRP / retail price: ${retail_price:.2f}\n"
        if tracking_start_price:
            context += f"Price when we started tracking: ${tracking_start_price:.2f}\n"

        message = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"You are a price tracking assistant. Analyze this price data and give a short buy recommendation.\n\n"
                        f"Product: {product_name}\n"
                        f"{context}"
                        f"Current price: ${current_price:.2f}\n"
                        f"Recent price history (newest first):\n{history_text}\n\n"
                        f"In 2-3 sentences: Is this a good time to buy? Is the price trending up or down? "
                        f"Reference the retail price and starting price if relevant. Keep it concise and practical."
                    )
                }
            ]
        )
        return message.content[0].text
    except Exception as e:
        print(f"[ERROR] AI analysis failed: {e}")
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
        retail_price = product.get("retail_price")
        tracking_start_price = product.get("tracking_start_price")
        price = scrape_price(url)

        if price is None:
            print(f"  Could not retrieve price for {name}")
            continue

        last_price = get_last_price(name)
        save_price(name, price)
        history = get_price_history(name)

        print(f"  {name}: ${price:.2f} (was: {'N/A' if last_price is None else f'${last_price:.2f}'})")

        ai_note = get_ai_analysis(name, price, history, retail_price, tracking_start_price)

        retail_line = f"Retail (MSRP): ${retail_price:.2f}\n" if retail_price else ""
        start_line = f"When we started tracking: ${tracking_start_price:.2f}\n" if tracking_start_price else ""

        if last_price is None or price == last_price:
            msg = (
                f"*Price Check (Test)*\n\n"
                f"*{name}*\n"
                f"{retail_line}"
                f"{start_line}"
                f"Current price: *${price:.2f}*\n"
                f"Price is unchanged — tracker is working."
            )
            if ai_note:
                msg += f"\n\n*AI Analysis:*\n{ai_note}"
            send_telegram(msg)

        elif price < last_price:
            diff = last_price - price
            msg = (
                f"*Price Drop!*\n\n"
                f"*{name}*\n"
                f"{retail_line}"
                f"{start_line}"
                f"Was: ${last_price:.2f}\n"
                f"Now: *${price:.2f}*\n"
                f"You save: *${diff:.2f}*\n\n"
                f"[View on Amazon]({url})"
            )
            if ai_note:
                msg += f"\n\n*AI Analysis:*\n{ai_note}"
            send_telegram(msg)

        elif price > last_price:
            diff = price - last_price
            msg = (
                f"*Price Increase*\n\n"
                f"*{name}*\n"
                f"{retail_line}"
                f"{start_line}"
                f"Was: ${last_price:.2f}\n"
                f"Now: *${price:.2f}* (+${diff:.2f})\n\n"
                f"[View on Amazon]({url})"
            )
            if ai_note:
                msg += f"\n\n*AI Analysis:*\n{ai_note}"
            send_telegram(msg)


if __name__ == "__main__":
    init_db()
    check_prices()
    schedule.every(CHECK_INTERVAL).minutes.do(check_prices)
    print(f"Scheduler running — checking every {CHECK_INTERVAL} minutes. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(30)
