import os

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")

PRODUCTS = [
    {
        "name": "PlayStation DualSense Edge Wireless Controller",
        "url": "https://www.amazon.com/PlayStation-DualSense-Wireless-Controller-Gaming-Console/dp/B0DSQQ1P8D/",
        "retail_price": 200.00,
        "tracking_start_price": 169.00,
    }
]

CHECK_INTERVAL = 60
