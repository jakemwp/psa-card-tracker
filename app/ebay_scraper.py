"""
eBay sold-listing scraper.

Uses eBay's public search with LH_Complete=1&LH_Sold=1 to get completed sales.
No API key required. Respects eBay's robots.txt by not hitting at high frequency.
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from typing import Optional
from datetime import datetime

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

EBAY_SEARCH = "https://www.ebay.com/sch/i.html"
REQUEST_DELAY = 2.0


class EbayScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _get(self, url: str, params: dict = None, timeout: int = 15) -> Optional[BeautifulSoup]:
        try:
            time.sleep(REQUEST_DELAY)
            resp = self.session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except Exception:
            return None

    def _parse_price(self, text: str) -> Optional[float]:
        text = text.replace(",", "")
        match = re.search(r"\$?([\d]+\.[\d]{2})", text)
        if match:
            return float(match.group(1))
        match = re.search(r"\$?([\d]+)", text)
        if match:
            return float(match.group(1))
        return None

    def _parse_date(self, text: str) -> str:
        """Convert eBay date strings like 'Jun 12, 2024' to ISO format."""
        text = text.strip()
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return text

    def search_sold(self, query: str, max_results: int = 60) -> list[dict]:
        """
        Search eBay completed/sold listings.
        Returns list of dicts: title, price, sold_date, listing_url, condition
        """
        params = {
            "_nkw": query,
            "LH_Complete": "1",
            "LH_Sold": "1",
            "_sop": "12",       # Sort: newly listed
            "_ipg": "60",       # Items per page
            "LH_ItemCondition": "",
        }

        soup = self._get(EBAY_SEARCH, params=params)
        if soup is None:
            return []

        listings = []

        # eBay item list — selector may vary slightly by eBay layout version
        items = soup.select("li.s-item")
        for item in items:
            # Skip the ghost "placeholder" first item eBay injects
            title_el = item.select_one(".s-item__title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if "Shop on eBay" in title or not title:
                continue

            # Price
            price_el = item.select_one(".s-item__price")
            price_text = price_el.get_text(strip=True) if price_el else ""
            # Handle price ranges like "$10.00 to $20.00" — take the lower
            if "to" in price_text:
                price_text = price_text.split("to")[0]
            price = self._parse_price(price_text)
            if price is None:
                continue

            # Sold date
            date_el = (
                item.select_one(".s-item__caption--signal")
                or item.select_one(".POSITIVE")
                or item.select_one(".s-item__endedDate")
                or item.select_one("[class*='endedDate']")
            )
            raw_date = date_el.get_text(strip=True) if date_el else ""
            # Strip "Sold " prefix
            raw_date = re.sub(r"^(Sold|Ended)\s*", "", raw_date, flags=re.I).strip()
            sold_date = self._parse_date(raw_date) if raw_date else ""

            # URL
            link_el = item.select_one("a.s-item__link")
            url = link_el.get("href", "").split("?")[0] if link_el else ""

            # Condition
            cond_el = item.select_one(".SECONDARY_INFO")
            condition = cond_el.get_text(strip=True) if cond_el else ""

            listings.append({
                "title": title[:300],
                "price": price,
                "sold_date": sold_date,
                "listing_url": url,
                "condition": condition[:100],
            })

            if len(listings) >= max_results:
                break

        return listings

    def summarize(self, listings: list[dict]) -> dict:
        """Compute avg/low/high from a list of sold listings."""
        prices = [l["price"] for l in listings if l.get("price") and l["price"] > 0]
        if not prices:
            return {"ebay_avg_price": 0.0, "ebay_low_price": 0.0, "ebay_high_price": 0.0, "ebay_sold_count": 0}
        return {
            "ebay_avg_price": round(sum(prices) / len(prices), 2),
            "ebay_low_price": round(min(prices), 2),
            "ebay_high_price": round(max(prices), 2),
            "ebay_sold_count": len(prices),
        }
