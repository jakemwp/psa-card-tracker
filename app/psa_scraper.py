"""
PSA Population Report scraper — single card lookup / search.
Uses curl_cffi (Chrome TLS fingerprint) to bypass Cloudflare.
"""

import re
import time
from typing import Optional
from urllib.parse import quote

from curl_cffi import requests as cf_requests
from bs4 import BeautifulSoup

PSA_BASE = "https://www.psacard.com"
DELAY = 1.5

_SESSION = cf_requests.Session(impersonate="chrome124")
_SESSION.headers.update({"Referer": PSA_BASE, "Accept-Language": "en-US,en;q=0.9"})


class PSAScraper:
    def _get(self, url: str) -> Optional[BeautifulSoup]:
        try:
            time.sleep(DELAY)
            r = _SESSION.get(url, timeout=15)
            r.raise_for_status()
            return BeautifulSoup(r.text, "lxml")
        except Exception as e:
            print(f"[PSAScraper] GET error {url}: {e}")
            return None

    def search(self, query: str) -> list[dict]:
        """Search PSA pop report. Returns list of {name, year, set, pop_url}."""
        soup = self._get(f"{PSA_BASE}/pop/search?q={quote(query)}")
        if not soup:
            return []

        results = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            parts = [p for p in href.split("/") if p and p != "pop"]
            if len(parts) < 3:
                continue
            if any(x in href for x in ("/search", "/cert", "?", "#")):
                continue
            full_url = href if href.startswith("http") else PSA_BASE + href
            if full_url in seen:
                continue
            seen.add(full_url)
            text = a.get_text(" ", strip=True)[:120]
            if not text or len(text) < 3:
                continue
            year_match = re.search(r"\b(19|20)\d{2}\b", href + " " + text)
            year = int(year_match.group()) if year_match else None
            results.append({
                "name": text,
                "year": year,
                "set": parts[-2].replace("-", " ").title() if len(parts) >= 2 else "",
                "card_number": "",
                "pop_url": full_url,
            })
        return results[:50]

    def get_population(self, pop_url: str) -> dict:
        """
        Fetch population data from a PSA pop report URL.
        Tries the GetSetItems API first (fast JSON), falls back to HTML parsing.
        """
        empty = {f"psa_pop_{g}": 0 for g in [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]}
        empty.update({"psa_pop_auth": 0, "psa_total_pop": 0, "gem_rate": 0.0})

        # Extract headingID and categoryID from the URL
        # URL pattern: /pop/{slug}/{year}/{set-slug}/{heading_id}
        parts = [p for p in pop_url.rstrip("/").split("/") if p and p != "pop"]
        heading_id = None
        cat_id = None

        if parts and parts[-1].isdigit():
            heading_id = parts[-1]

        # Try to find cat_id from the category page (requires extra fetch) or skip
        if heading_id:
            try:
                time.sleep(DELAY)
                resp = _SESSION.post(
                    f"{PSA_BASE}/Pop/GetSetItems",
                    data={
                        "draw": 1, "start": 0, "length": 500,
                        "search": "", "headingID": heading_id,
                        "categoryID": "", "isPSADNA": "false",
                    },
                    headers={"X-Requested-With": "XMLHttpRequest",
                             "Content-Type": "application/x-www-form-urlencoded",
                             "Referer": pop_url},
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    rows = data.get("data", [])
                    # First row is usually TOTAL POPULATION summary
                    total_row = next((r for r in rows if
                                      "TOTAL" in (r.get("SubjectName") or "").upper()), None)
                    if total_row:
                        pop_10   = int(total_row.get("Grade10", 0) or 0)
                        pop_auth = int(total_row.get("GradeN0",  0) or 0)
                        total    = int(total_row.get("GradeTotal", 0) or 0)
                        return {
                            "psa_pop_10":    pop_10,
                            "psa_pop_9":     int(total_row.get("Grade9", 0) or 0),
                            "psa_pop_8":     int(total_row.get("Grade8", 0) or 0),
                            "psa_pop_7":     int(total_row.get("Grade7", 0) or 0),
                            "psa_pop_6":     int(total_row.get("Grade6", 0) or 0),
                            "psa_pop_5":     int(total_row.get("Grade5", 0) or 0),
                            "psa_pop_4":     int(total_row.get("Grade4", 0) or 0),
                            "psa_pop_3":     int(total_row.get("Grade3", 0) or 0),
                            "psa_pop_2":     int(total_row.get("Grade2", 0) or 0),
                            "psa_pop_1":     int(total_row.get("Grade1", 0) or 0),
                            "psa_pop_auth":  pop_auth,
                            "psa_total_pop": total,
                            "gem_rate":      round(pop_10 / total * 100, 2) if total else 0.0,
                        }
            except Exception as e:
                print(f"[PSAScraper] API fallback error: {e}")

        # Fallback: HTML table parsing
        soup = self._get(pop_url)
        if not soup:
            return empty

        grade_map: dict = {}
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if len(cells) < 2:
                    continue
                label = cells[0].upper().replace("PSA", "").strip()
                count = int(re.sub(r"[^\d]", "", cells[-1]) or 0)
                if "10" in label:       grade_map[10] = count
                elif "9" in label:      grade_map[9]  = count
                elif "8" in label:      grade_map[8]  = count
                elif "7" in label:      grade_map[7]  = count
                elif "6" in label:      grade_map[6]  = count
                elif "5" in label:      grade_map[5]  = count
                elif "4" in label:      grade_map[4]  = count
                elif "3" in label:      grade_map[3]  = count
                elif "2" in label:      grade_map[2]  = count
                elif "1" in label:      grade_map[1]  = count
                elif "AUTH" in label:   grade_map["auth"] = count

        result = {f"psa_pop_{g}": grade_map.get(g, 0) for g in [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]}
        result["psa_pop_auth"]  = grade_map.get("auth", 0)
        total = sum(v for k, v in grade_map.items() if isinstance(k, int))
        result["psa_total_pop"] = total
        pop_10 = grade_map.get(10, 0)
        result["gem_rate"] = round(pop_10 / total * 100, 2) if total else 0.0
        return result
