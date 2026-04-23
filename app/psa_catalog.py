"""
PSA Pop Report catalog scraper.

Uses curl_cffi (Chrome TLS fingerprint) to bypass Cloudflare.
Card data is loaded via PSA's internal DataTables API:
  POST https://www.psacard.com/Pop/GetSetItems

URL hierarchy:
  /pop/{category-slug}/{cat-id}           → list of year links
  /pop/{category-slug}/{year}/{year-id}   → list of set links
  /Pop/GetSetItems  POST                  → card rows for a set
"""

import re
import time
from typing import Generator

from curl_cffi import requests as cf_requests
from bs4 import BeautifulSoup

PSA_BASE = "https://www.psacard.com"
DELAY = 1.2   # seconds between requests

def _new_session() -> cf_requests.Session:
    s = cf_requests.Session(impersonate="chrome124")
    s.headers.update({"Referer": PSA_BASE, "Accept-Language": "en-US,en;q=0.9"})
    return s

# Hardcoded categories with their numeric category IDs (stable, rarely change)
KNOWN_CATEGORIES = [
    {"name": "Baseball Cards",                  "slug": "baseball-cards",               "cat_id": "20003"},
    {"name": "Basketball Cards",                "slug": "basketball-cards",             "cat_id": "20019"},
    {"name": "Football Cards",                  "slug": "football-cards",               "cat_id": "20014"},
    {"name": "Hockey Cards",                    "slug": "hockey-cards",                 "cat_id": "20020"},
    {"name": "Soccer Cards",                    "slug": "soccer-cards",                 "cat_id": "20004"},
    {"name": "Golf Cards",                      "slug": "golf-cards",                   "cat_id": "20023"},
    {"name": "Boxing / Wrestling / MMA Cards",  "slug": "boxing-wrestling-cards-mma",   "cat_id": "20021"},
    {"name": "Non-Sport Cards",                 "slug": "non-sport-cards",              "cat_id": "20032"},
    {"name": "TCG Cards",                       "slug": "tcg-cards",                    "cat_id": "156940"},
    {"name": "Multi-Sport Cards",               "slug": "multi-sport-cards",            "cat_id": "20006"},
    {"name": "Minor League Cards",              "slug": "minor-league-cards",           "cat_id": "20031"},
    {"name": "Entertainment Cards",             "slug": "entertainment-cards",          "cat_id": "20037"},
    {"name": "Misc Cards",                      "slug": "misc-cards",                   "cat_id": "20033"},
]

# Sport label inferred from category
_SPORT_LABELS = {
    "baseball-cards": "Baseball",
    "basketball-cards": "Basketball",
    "football-cards": "Football",
    "hockey-cards": "Hockey",
    "soccer-cards": "Soccer",
    "golf-cards": "Golf",
    "boxing-wrestling-cards-mma": "Boxing/Wrestling",
    "non-sport-cards": "Non-Sport",
    "tcg-cards": "TCG",
    "multi-sport-cards": "Multi-Sport",
    "minor-league-cards": "Minor League",
    "entertainment-cards": "Entertainment",
    "misc-cards": "Misc",
}


def _get(url: str) -> BeautifulSoup:
    time.sleep(DELAY)
    resp = cf_requests.get(url, impersonate="chrome124", timeout=20,
                           headers={"Referer": PSA_BASE, "Accept-Language": "en-US,en;q=0.9"})
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def _post_json(url: str, data: dict, referer: str = PSA_BASE) -> dict:
    time.sleep(DELAY)
    resp = cf_requests.post(
        url, data=data, impersonate="chrome124", timeout=20,
        headers={
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class PSACatalogScraper:
    def __init__(self, delay: float = DELAY):
        self._abort = False

    def abort(self):
        self._abort = True

    def get_categories(self) -> list[dict]:
        """Returns hardcoded category list instantly — no network call."""
        return list(KNOWN_CATEGORIES)

    def get_years(self, cat: dict) -> list[dict]:
        """
        Fetch the category page and return all year entries.
        Each entry: {label, year_url, year_id, cat_id, sport}
        """
        url = f"{PSA_BASE}/pop/{cat['slug']}/{cat['cat_id']}"
        soup = _get(url)
        sport = _SPORT_LABELS.get(cat["slug"], cat["name"])

        years = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Match /pop/{slug}/{year-label}/{year-id}
            m = re.match(r"^/pop/[^/]+/([^/]+)/(\d+)$", href)
            if not m:
                continue
            year_label = m.group(1)
            year_id = m.group(2)
            if year_id in seen:
                continue
            seen.add(year_id)
            label = a.get_text(strip=True) or year_label
            years.append({
                "label": label,
                "year_url": PSA_BASE + href,
                "year_id": year_id,
                "cat_id": cat["cat_id"],
                "sport": sport,
                "slug": cat["slug"],
            })

        # Sort newest first
        def _sort_key(y):
            m = re.search(r"\d{4}", y["label"])
            return int(m.group()) if m else 0

        years.sort(key=_sort_key, reverse=True)
        return years

    def get_sets(self, year: dict) -> list[dict]:
        """
        Fetch a year page and return all set entries.
        Each entry: {name, set_url, heading_id, cat_id, year_label, sport}
        """
        soup = _get(year["year_url"])
        sport = year.get("sport", "")
        slug = year.get("slug", "")

        sets = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Match /pop/{slug}/{year-label}/{set-slug}/{heading-id}
            m = re.match(r"^/pop/[^/]+/[^/]+/([^/]+)/(\d+)$", href)
            if not m:
                continue
            heading_id = m.group(2)
            if heading_id in seen:
                continue
            seen.add(heading_id)
            name = a.get_text(strip=True)[:150] or m.group(1).replace("-", " ").title()
            sets.append({
                "name": name,
                "set_url": PSA_BASE + href,
                "heading_id": heading_id,
                "cat_id": year["cat_id"],
                "year_label": year["label"],
                "sport": sport,
            })

        return sets

    def get_cards_from_set(self, set_info: dict) -> list[dict]:
        """
        Call PSA's GetSetItems API and return all card records with
        full grade populations and gem rate.
        """
        if self._abort:
            return []

        heading_id = set_info["heading_id"]
        cat_id = set_info["cat_id"]
        set_url = set_info.get("set_url", "")

        all_rows = []
        start = 0
        page_size = 500

        while not self._abort:
            try:
                data = _post_json(
                    f"{PSA_BASE}/Pop/GetSetItems",
                    {
                        "draw": 1,
                        "start": start,
                        "length": page_size,
                        "search": "",
                        "headingID": heading_id,
                        "categoryID": cat_id,
                        "isPSADNA": "false",
                    },
                    referer=set_url or PSA_BASE,
                )
            except Exception as e:
                print(f"[PSACatalog] GetSetItems error for {heading_id}: {e}")
                break

            rows = data.get("data", [])
            if not rows:
                break
            all_rows.extend(rows)

            total = data.get("recordsTotal", 0)
            start += page_size
            if start >= total:
                break

        # Parse each row into a card dict
        cards = []
        sport = set_info.get("sport", "")
        set_name = set_info.get("name", "")
        year_label = set_info.get("year_label", "")

        # Try to extract numeric year
        year_match = re.search(r"\b(1[89]\d{2}|20\d{2})\b", year_label)
        year = int(year_match.group()) if year_match else None

        for row in all_rows:
            subject = (row.get("SubjectName") or "").strip()
            if not subject or subject.upper() == "TOTAL POPULATION":
                continue

            card_num = (row.get("CardNumber") or "").strip()
            variety  = (row.get("Variety") or "").strip()

            # Build a descriptive card name
            parts = [year_label, set_name, subject]
            full_name = " ".join(p for p in parts if p).strip()

            pop_10   = int(row.get("Grade10", 0) or 0)
            pop_9    = int(row.get("Grade9",  0) or 0)
            pop_8    = int(row.get("Grade8",  0) or 0)
            pop_7    = int(row.get("Grade7",  0) or 0)
            pop_6    = int(row.get("Grade6",  0) or 0)
            pop_5    = int(row.get("Grade5",  0) or 0)
            pop_4    = int(row.get("Grade4",  0) or 0)
            pop_3    = int(row.get("Grade3",  0) or 0)
            pop_2    = int(row.get("Grade2",  0) or 0)
            pop_1    = int(row.get("Grade1",  0) or 0)
            pop_auth = int(row.get("GradeN0", 0) or 0)
            total    = int(row.get("GradeTotal", 0) or 0)

            if total == 0:
                total = pop_10 + pop_9 + pop_8 + pop_7 + pop_6 + pop_5 + pop_4 + pop_3 + pop_2 + pop_1

            gem_rate = round(pop_10 / total * 100, 2) if total > 0 else 0.0

            cards.append({
                "card_name":     full_name[:200],
                "year":          year,
                "sport":         sport,
                "card_set":      set_name[:200],
                "card_number":   card_num[:20],
                "variation":     variety[:100],
                "player":        subject[:200],
                "psa_pop_10":    pop_10,
                "psa_pop_9":     pop_9,
                "psa_pop_8":     pop_8,
                "psa_pop_7":     pop_7,
                "psa_pop_6":     pop_6,
                "psa_pop_5":     pop_5,
                "psa_pop_4":     pop_4,
                "psa_pop_3":     pop_3,
                "psa_pop_2":     pop_2,
                "psa_pop_1":     pop_1,
                "psa_pop_auth":  pop_auth,
                "psa_total_pop": total,
                "gem_rate":      gem_rate,
                "psa_url":       set_url,
            })

        return cards

    def stream_cards(
        self, sets: list[dict]
    ) -> Generator[tuple[dict, int, int], None, None]:
        """Yield (card_dict, set_index, total_sets) for every card in the given sets."""
        total = len(sets)
        for i, set_info in enumerate(sets):
            if self._abort:
                return
            for card in self.get_cards_from_set(set_info):
                if self._abort:
                    return
                yield card, i + 1, total
