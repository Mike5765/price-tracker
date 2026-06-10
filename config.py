import os

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
BESTBUY_API_KEY = os.environ.get("BESTBUY_API_KEY", "")

PRODUCTS = [
    {
        "name": "PlayStation DualSense Edge Wireless Controller",
        "url": "https://www.amazon.com/PlayStation-DualSense-Wireless-Controller-Gaming-Console/dp/B0DSQQ1P8D/",
        "bestbuy_search": "PlayStation DualSense Edge Wireless Controller",
    }
]

CHECK_INTERVAL = 60
