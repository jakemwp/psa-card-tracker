"""
PSA Population Report scraper.

Strategy:
  1. If the user provides a direct pop-report URL, fetch it and parse the grade table.
  2. If a search term is provided, search PSA's pop-report search and return candidate cards.

PSA renders their pop-report pages server-side (not pure-JS), so plain requests works.
The page structure occasionally changes — graceful fallback to 0 values if parsing fails.
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from typing import Optional

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.psacard.com/",
}

PSA_BASE = "https://www.psacard.com"
REQUEST_DELAY = 1.5  # seconds between requests — be polite


class PSAScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _get(self, url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
        try:
            time.sleep(REQUEST_DELAY)
            resp = self.session.get(url, timeout=timeout)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except Exception as e:
            return None

    def search(self, query: str) -> list[dict]:
        """
        Search PSA pop report. Returns list of dicts with keys:
            name, year, set, card_number, pop_url
        """
        url = f"{PSA_BASE}/pop/search?q={requests.utils.quote(query)}"
        soup = self._get(url)
        if soup is None:
            return []

        results = []

        # PSA returns search results in various list/table layouts.
        # Try several common selectors.
        for a in soup.select("a[href*='/pop/']"):
            href = a.get("href", "")
            # Filter out nav links — real results have 4+ path segments
            parts = [p for p in href.split("/") if p]
            if len(parts) < 4:
                continue
            text = a.get_text(" ", strip=True)
            if not text or len(text) < 3:
                continue

            # Try to extract year from URL or text
            year_match = re.search(r"\b(19|20)\d{2}\b", href + " " + text)
            year = int(year_match.group()) if year_match else None

            full_url = href if href.startswith("http") else PSA_BASE + href
            results.append({
                "name": text[:120],
                "year": year,
                "set": parts[-2].replace("-", " ").title() if len(parts) >= 2 else "",
                "card_number": "",
                "pop_url": full_url,
            })

        # Deduplicate by URL
        seen = set()
        unique = []
        for r in results:
            if r["pop_url"] not in seen:
                seen.add(r["pop_url"])
                unique.append(r)

        return unique[:50]

    def get_population(self, pop_url: str) -> dict:
        """
        Fetch population data from a PSA pop report URL.
        Returns a dict with grade counts and derived stats.
        """
        empty = {f"psa_pop_{g}": 0 for g in [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]}
        empty["psa_pop_auth"] = 0
        empty["psa_total_pop"] = 0
        empty["gem_rate"] = 0.0

        soup = self._get(pop_url)
        if soup is None:
            return empty

        # --- Parse grade distribution table ---
        # PSA uses a table with grade labels and counts.
        # Common selectors: table.pop-report-table, .pop-report, etc.
        grade_map = {}

        # Look for any table containing "PSA 10" or grade numbers
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if len(cells) < 2:
                    continue
                # Match patterns like "PSA 10", "10", "Authentic", "Auth"
                grade_text = cells[0].upper().replace("PSA", "").strip()
                count_text = re.sub(r"[^\d]", "", cells[-1]) or "0"
                count = int(count_text) if count_text else 0

                if grade_text in ("10", "GEM MT 10", "GEM-MT 10"):
                    grade_map[10] = count
                elif grade_text in ("9", "MINT 9", "MINT"):
                    grade_map[9] = count
                elif grade_text in ("8", "NM-MT 8", "NM-MT"):
                    grade_map[8] = count
                elif grade_text in ("7", "NM 7", "NM"):
                    grade_map[7] = count
                elif grade_text in ("6", "EX-MT 6", "EX-MT"):
                    grade_map[6] = count
                elif grade_text in ("5", "EX 5", "EX"):
                    grade_map[5] = count
                elif grade_text in ("4", "VG-EX 4", "VG-EX"):
                    grade_map[4] = count
                elif grade_text in ("3", "VG 3", "VG"):
                    grade_map[3] = count
                elif grade_text in ("2", "GOOD 2", "GOOD"):
                    grade_map[2] = count
                elif grade_text in ("1", "PR 1", "POOR", "FR 1"):
                    grade_map[1] = count
                elif "AUTH" in grade_text or "AUTHENTIC" in grade_text:
                    grade_map["auth"] = count

        # Fallback: look for labelled spans/divs with grade data
        if not grade_map:
            for elem in soup.find_all(string=re.compile(r"PSA\s+10")):
                parent = elem.parent
                if parent:
                    # Sibling or nearby element might have the count
                    siblings = list(parent.next_siblings)
                    for s in siblings[:3]:
                        txt = getattr(s, "get_text", lambda: str(s))(strip=True) if hasattr(s, "get_text") else str(s).strip()
                        count_txt = re.sub(r"[^\d]", "", txt)
                        if count_txt:
                            grade_map[10] = int(count_txt)
                            break

        result = {f"psa_pop_{g}": grade_map.get(g, 0) for g in [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]}
        result["psa_pop_auth"] = grade_map.get("auth", 0)
        total = sum(grade_map.values())
        result["psa_total_pop"] = total
        pop_10 = grade_map.get(10, 0)
        result["gem_rate"] = round((pop_10 / total * 100), 2) if total > 0 else 0.0

        return result

    def get_card_info_from_url(self, pop_url: str) -> dict:
        """
        Try to extract card metadata (name, year, set, number) from the pop report page.
        """
        info = {"card_name": "", "year": None, "card_set": "", "card_number": ""}
        soup = self._get(pop_url)
        if soup is None:
            return info

        # Page title or h1 often has card name
        h1 = soup.find("h1")
        if h1:
            info["card_name"] = h1.get_text(" ", strip=True)[:200]

        # Look for year in page content
        year_match = re.search(r"\b(19|20)\d{2}\b", info["card_name"])
        if year_match:
            info["year"] = int(year_match.group())

        # Card number often appears as "#NNN" or "Card # NNN"
        num_match = re.search(r"#\s*(\w+)", info["card_name"])
        if num_match:
            info["card_number"] = num_match.group(1)

        return info
