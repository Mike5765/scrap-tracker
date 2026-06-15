import requests
import sqlite3
import smtplib
import re
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from datetime import datetime
from config import EMAIL_SENDER, EMAIL_APP_PASSWORD, EMAIL_RECIPIENT, MATERIALS, REGION

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SCRAPMONSTER_URL = "https://www.scrapmonster.com/scrap-metal-prices/united-states"


def init_db():
    conn = sqlite3.connect("scrap_prices.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material TEXT,
            price REAL,
            checked_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_last_price(material):
    conn = sqlite3.connect("scrap_prices.db")
    row = conn.execute(
        "SELECT price FROM price_history WHERE material = ? ORDER BY checked_at DESC LIMIT 1",
        (material,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def save_price(material, price):
    conn = sqlite3.connect("scrap_prices.db")
    conn.execute(
        "INSERT INTO price_history (material, price, checked_at) VALUES (?, ?, ?)",
        (material, price, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def scrape_prices():
    try:
        response = requests.get(SCRAPMONSTER_URL, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "lxml")
        prices = {}

        region_col = None
        for row in soup.select("table tr"):
            headers = row.select("th")
            for i, cell in enumerate(headers):
                if REGION.lower() in cell.get_text(strip=True).lower():
                    region_col = i
                    break
            if region_col is not None:
                break

        for row in soup.select("table tr"):
            cells = row.select("td")
            if not cells:
                continue
            name = cells[0].get_text(strip=True)
            for material in MATERIALS:
                if material["scrapmonster_key"].lower() in name.lower():
                    target_cells = [cells[region_col]] if region_col and region_col < len(cells) else cells[1:]
                    for cell in target_cells:
                        text = cell.get_text(strip=True)
                        match = re.search(r"\$?([\d]+\.[\d]{2})", text)
                        if match:
                            val = float(match.group(1))
                            if 0.5 < val < 20:
                                prices[material["name"]] = val
                                break

        return prices

    except Exception as e:
        print(f"[ERROR] Scrape failed: {e}")
        return {}


def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECIPIENT

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
        print("  Email sent.")
    except Exception as e:
        print(f"[ERROR] Email send failed: {e}")


def check_prices():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Fetching scrap prices...")

    prices = scrape_prices()

    if not prices:
        print("  Could not retrieve any prices.")
        send_email(
            "Scrap Tracker — Price Unavailable",
            "Could not retrieve scrap prices today. Will try again tomorrow."
        )
        return

    lines = []
    for material in MATERIALS:
        name = material["name"]
        price = prices.get(name)

        if price is None:
            print(f"  {name}: not found")
            lines.append(f"{name}: N/A")
            continue

        last_price = get_last_price(name)
        save_price(name, price)

        if last_price is None:
            change = ""
        elif price > last_price:
            change = f" (up ${price - last_price:.2f} from yesterday)"
        elif price < last_price:
            change = f" (down ${last_price - price:.2f} from yesterday)"
        else:
            change = " (no change)"

        print(f"  {name}: ${price:.2f}/lb{change}")
        lines.append(f"{name}: ${price:.2f}/lb{change}")

    today = datetime.now().strftime("%B %d, %Y")
    body = (
        f"Daily Scrap Prices — {today}\n"
        f"Region: {REGION}\n"
        f"Source: ScrapMonster\n"
        f"\n"
        + "\n".join(lines)
    )

    send_email(f"Scrap Prices — {today}", body)
