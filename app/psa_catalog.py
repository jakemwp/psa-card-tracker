"""
PSA Pop Report catalog crawler.

Navigates PSA's category hierarchy:
  /pop/  →  categories  →  years/sets  →  individual card pages

Yields card dicts with full population data for bulk import.
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from typing import Generator, Optional

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
DELAY = 1.5  # seconds between requests

# Map PSA category URL slugs to friendly sport names
SPORT_SLUG_MAP = {
    "baseball-cards": "Baseball",
    "basketball-cards": "Basketball",
    "football-cards": "Football",
    "hockey-cards": "Hockey",
    "soccer-cards": "Soccer",
    "golf-cards": "Golf",
    "boxing-cards": "Boxing",
    "wrestling-cards": "Wrestling",
    "non-sports-cards": "Non-Sports",
    "tcg-cards": "TCG",
    "pokemon-cards": "Pokemon",
    "magic-cards": "Magic: The Gathering",
    "yugioh-cards": "Yu-Gi-Oh!",
    "entertainment-cards": "Entertainment",
    "auto-cards": "Autographs",
}


class PSACatalogScraper:
    def __init__(self, delay: float = DELAY):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._abort = False

    def abort(self):
        self._abort = True

    def _get(self, url: str) -> Optional[BeautifulSoup]:
        if self._abort:
            return None
        try:
            time.sleep(self.delay)
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Top-level category list
    # ------------------------------------------------------------------

    def get_categories(self) -> list[dict]:
        """
        Fetch the top-level categories from the PSA pop report home page.
        Returns list of {name, url, slug}
        """
        soup = self._get(f"{PSA_BASE}/pop/")
        if not soup:
            return []

        categories = []
        seen = set()

        for a in soup.select("a[href]"):
            href = a.get("href", "")
            # Match /pop/{slug}/ or /pop/{slug}
            m = re.match(r"^/pop/([a-z0-9-]+)/?$", href)
            if not m:
                continue
            slug = m.group(1)
            if slug in seen or slug in ("search", "cert", "verifycert"):
                continue
            seen.add(slug)
            name = SPORT_SLUG_MAP.get(slug, a.get_text(strip=True)[:60] or slug.replace("-", " ").title())
            categories.append({
                "name": name,
                "slug": slug,
                "url": PSA_BASE + href if href.startswith("/") else href,
            })

        # If PSA didn't expose them as links, return known categories
        if not categories:
            categories = [
                {"name": v, "slug": k, "url": f"{PSA_BASE}/pop/{k}/"}
                for k, v in SPORT_SLUG_MAP.items()
            ]

        return categories

    # ------------------------------------------------------------------
    # Sets within a category
    # ------------------------------------------------------------------

    def get_sets(self, category_url: str, category_name: str = "") -> list[dict]:
        """
        Return all sets (leaf pages) reachable from a category URL.
        PSA organises as: category → year → set
        Returns list of {name, url, year, sport}
        """
        sets = []
        soup = self._get(category_url)
        if not soup:
            return sets

        # Collect all /pop/... links that look like set pages (≥4 path segments)
        for a in soup.select("a[href*='/pop/']"):
            href = a.get("href", "")
            parts = [p for p in href.split("/") if p and p != "pop"]
            if len(parts) < 3:
                continue
            full_url = href if href.startswith("http") else PSA_BASE + href

            year_match = re.search(r"\b(19|20)\d{2}\b", href)
            year = int(year_match.group()) if year_match else None

            name = a.get_text(" ", strip=True)[:120]
            if not name:
                name = parts[-1].replace("-", " ").title()

            sets.append({
                "name": name,
                "url": full_url,
                "year": year,
                "sport": category_name,
            })

        # Deduplicate
        seen = set()
        unique = []
        for s in sets:
            if s["url"] not in seen:
                seen.add(s["url"])
                unique.append(s)
        return unique

    # ------------------------------------------------------------------
    # Cards within a set page
    # ------------------------------------------------------------------

    def get_cards_from_set(self, set_info: dict) -> list[dict]:
        """
        Parse a PSA set pop report page and return all card records.
        Each record has full population + gem rate.
        """
        soup = self._get(set_info["url"])
        if not soup:
            return []

        cards = []
        page_title = ""
        h1 = soup.find("h1")
        if h1:
            page_title = h1.get_text(" ", strip=True)

        # PSA pop report tables: each row is a card with grade columns
        # Common structure:
        #   <table> <tr> <td>Card Name/Number</td> <td>Auth</td> <td>1</td> ... <td>10</td> <td>Total</td> </tr>
        tables = soup.find_all("table")
        for table in tables:
            headers_row = table.find("tr")
            if not headers_row:
                continue
            header_cells = [th.get_text(strip=True).upper() for th in headers_row.find_all(["th", "td"])]

            # Identify grade column positions
            grade_cols = {}
            for i, h in enumerate(header_cells):
                clean = h.replace("PSA", "").replace("GEM", "").strip()
                if clean == "10":
                    grade_cols[10] = i
                elif clean == "9" or "MINT" in h:
                    grade_cols[9] = i
                elif clean == "8":
                    grade_cols[8] = i
                elif clean == "7":
                    grade_cols[7] = i
                elif clean == "6":
                    grade_cols[6] = i
                elif clean == "5":
                    grade_cols[5] = i
                elif clean == "4":
                    grade_cols[4] = i
                elif clean == "3":
                    grade_cols[3] = i
                elif clean == "2":
                    grade_cols[2] = i
                elif clean == "1" or clean == "PR":
                    grade_cols[1] = i
                elif "AUTH" in h:
                    grade_cols["auth"] = i

            if not grade_cols:
                continue

            for row in table.find_all("tr")[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                cell_texts = [c.get_text(strip=True) for c in cells]
                if not any(cell_texts):
                    continue

                # First cell is usually card name/number
                raw_name = cell_texts[0] if cell_texts else ""
                if not raw_name or raw_name.upper() in ("CARD", "NAME", "DESCRIPTION"):
                    continue

                # Parse card number from name like "001 Bulbasaur" or "#001"
                card_num = ""
                num_match = re.match(r"^#?(\d+[A-Za-z]?)\s+(.*)", raw_name)
                if num_match:
                    card_num = num_match.group(1)
                    card_name = num_match.group(2).strip()
                else:
                    card_name = raw_name

                # Build card name from set page title if it adds context
                full_name = card_name
                if set_info.get("year") and str(set_info["year"]) not in full_name:
                    full_name = f"{set_info['year']} {card_name}" if card_name else page_title

                # Extract grade counts
                def safe_int(txt: str) -> int:
                    clean = re.sub(r"[^\d]", "", txt)
                    return int(clean) if clean else 0

                pops = {}
                for grade, col in grade_cols.items():
                    if col < len(cell_texts):
                        pops[grade] = safe_int(cell_texts[col])

                # Total — last cell or last numeric cell
                total_col = len(cell_texts) - 1
                total = safe_int(cell_texts[total_col]) if cell_texts[total_col] else sum(pops.values())
                if total == 0:
                    total = sum(v for k, v in pops.items() if isinstance(k, int))

                pop_10 = pops.get(10, 0)
                gem_rate = round(pop_10 / total * 100, 2) if total > 0 else 0.0

                card = {
                    "card_name": full_name[:200],
                    "year": set_info.get("year"),
                    "sport": set_info.get("sport", ""),
                    "card_set": set_info.get("name", "")[:200],
                    "card_number": card_num[:20],
                    "variation": "",
                    "player": card_name[:200],
                    "psa_pop_10": pop_10,
                    "psa_pop_9": pops.get(9, 0),
                    "psa_pop_8": pops.get(8, 0),
                    "psa_pop_7": pops.get(7, 0),
                    "psa_pop_6": pops.get(6, 0),
                    "psa_pop_5": pops.get(5, 0),
                    "psa_pop_4": pops.get(4, 0),
                    "psa_pop_3": pops.get(3, 0),
                    "psa_pop_2": pops.get(2, 0),
                    "psa_pop_1": pops.get(1, 0),
                    "psa_pop_auth": pops.get("auth", 0),
                    "psa_total_pop": total,
                    "gem_rate": gem_rate,
                    "psa_url": set_info["url"],
                }
                cards.append(card)

        return cards

    # ------------------------------------------------------------------
    # High-level generator: stream all cards from a list of set URLs
    # ------------------------------------------------------------------

    def stream_cards(
        self, sets: list[dict]
    ) -> Generator[tuple[dict, int, int], None, None]:
        """
        Yields (card_dict, current_set_index, total_sets) for each card found.
        """
        total = len(sets)
        for i, set_info in enumerate(sets):
            if self._abort:
                return
            cards = self.get_cards_from_set(set_info)
            for card in cards:
                if self._abort:
                    return
                yield card, i + 1, total
