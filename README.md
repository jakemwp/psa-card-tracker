# PSA Card Tracker

A native Windows desktop app that automatically pulls **PSA gem rates** and **eBay sold listing prices** for trading cards, storing everything in a local searchable database.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python) ![Platform](https://img.shields.io/badge/Platform-Windows-blue?logo=windows) ![License](https://img.shields.io/badge/License-MIT-green)

---

## Features

### PSA Population Data
- Fetches live population data from the PSA pop report for any card
- Tracks all grade tiers: PSA 1 through PSA 10 + Authentic
- Calculates **gem rate** (PSA 10 population ÷ total population × 100%)
- Color-coded gem rate column: 🟢 ≥80% · 🟡 ≥50% · 🔴 >0%

### eBay Sold Listings
- Scrapes eBay completed/sold listings for each card automatically
- Records individual sale prices, dates, and conditions
- Calculates **average, low, and high** sold prices across recent sales
- Full sold listing history stored per card and viewable in the bottom panel

### Searchable Database
- Local SQLite database — no account or internet connection needed to browse your data
- **Filter by any combination of:**
  - Free-text search (name, player, set, notes)
  - Sport / category (Baseball, Basketball, Football, Hockey, Soccer, Pokémon, MTG, Yu-Gi-Oh!, etc.)
  - Year range
  - Gem rate % range
  - Average eBay price range
  - Minimum PSA 10 population
- All table columns are **sortable** with a single click
- **Export to CSV** for use in Excel or Google Sheets

### Card Management
- Add cards by searching the PSA pop report directly inside the app
- Or paste a PSA pop report URL manually
- Edit any card field at any time (double-click a row)
- Right-click context menu: edit, refresh, open PSA page, view on eBay, delete
- Bulk refresh all cards in one click

---

## Installation

### Requirements
- Windows 10 or 11
- [Python 3.10+](https://www.python.org/downloads/) — check **"Add Python to PATH"** during install

### Steps

1. **Clone or download this repository**
   ```
   git clone https://github.com/aaronbfeoffice/psa-card-tracker.git
   cd psa-card-tracker
   ```
   Or download and extract the ZIP from the GitHub releases page.

2. **Run the installer** (one time only)
   ```
   install.bat
   ```
   This installs PyQt6, requests, BeautifulSoup4, and lxml.

3. **Launch the app**
   ```
   run.bat
   ```
   Or double-click `run.bat` from File Explorer.

---

## How to Use

### Adding a Card

1. Click **➕ Add Card** in the toolbar (or press `Ctrl+N`)
2. In the **PSA Search** tab, type a card name and click **Search PSA Pop Report**
3. Click a result to select it — the PSA URL and card details auto-fill
4. Switch to the **Card Details** tab to review/edit the name, year, sport, set, card number, variation, player/character, and custom eBay search query
5. Click **OK** — the app immediately scrapes PSA population data and eBay sold listings in the background

### Refreshing Data

| Action | How |
|---|---|
| Refresh one card | Select it → click **🔄 Refresh Selected** (or press `F5`) |
| Refresh multiple | Select several rows → **🔄 Refresh Selected** |
| Refresh everything | Click **🔄 Refresh All** |
| Refresh via right-click | Right-click any row → **Refresh This Card** |

### Searching & Filtering

Use the **left filter panel** to narrow the table in real time:

- **Search box** — matches against card name, player/character, set name, and notes simultaneously
- **Sport / Category** — dropdown to filter by sport or card game
- **Year Range** — from/to year sliders
- **Gem Rate % Range** — e.g. set minimum to 70% to find hard-to-gem cards
- **Avg eBay Price ($)** — filter by price range
- **Min PSA 10 Pop** — filter to cards with a minimum PSA 10 population

Click **Reset Filters** to clear all filters at once.

### Viewing eBay Listings

Click any card row — the bottom panel loads all saved eBay sold listings for that card, showing title, price, sold date, and condition.

To open the live eBay search in your browser: right-click the card → **🛒 View on eBay**.

### Editing a Card

Double-click any row to open the edit dialog. All fields are editable including the PSA URL and custom eBay search query.

### Exporting Data

Click **📊 Export CSV** in the toolbar to save the full database (with current filters applied) as a `.csv` file.

---

## Database Fields

Every card stores the following fields, all of which are searchable/filterable:

| Field | Description |
|---|---|
| Card Name | Full card name |
| Year | Year of issue |
| Sport / Category | Sport or card game |
| Set / Series | Set or series name |
| Card Number | Card number within the set |
| Variation / Parallel | e.g. Holo, 1st Edition, Reverse Holo |
| Player / Character | Athlete name or character |
| PSA 1–10 Population | Individual count per grade |
| PSA Auth Population | Authentic (ungraded) count |
| Total Population | Sum of all grades |
| Gem Rate % | PSA 10 ÷ Total × 100 |
| eBay Avg Price | Average sold price |
| eBay Low Price | Lowest sold price |
| eBay High Price | Highest sold price |
| eBay Sold Count | Number of sales sampled |
| PSA URL | Link to the PSA pop report page |
| eBay Search Query | Custom eBay search term (auto-generated or manual) |
| Notes | Free-text notes |
| Date Added | When the card was added |
| Last Updated | When data was last refreshed |

---

## File Structure

```
psa-card-tracker/
├── main.py              # App entry point
├── run.bat              # Launch the app (Windows)
├── install.bat          # Install dependencies (run once)
├── requirements.txt     # Python dependencies
├── cards.db             # SQLite database (auto-created on first run)
└── app/
    ├── database.py      # SQLite schema, queries, and CRUD operations
    ├── psa_scraper.py   # PSA pop report scraper
    ├── ebay_scraper.py  # eBay sold listings scraper
    └── main_window.py   # Full PyQt6 user interface
```

---

## Notes

- **PSA scraping:** PSA's pop report pages are fetched directly. If PSA changes their page structure, the scraper may need updating — you can always paste the PSA URL directly into the Add Card dialog as a fallback.
- **eBay scraping:** Uses eBay's publicly accessible completed listings search. No API key required. Requests are throttled to avoid rate limiting.
- **Data is local:** All data is stored in `cards.db` in the app folder. Nothing is sent to any external service.

---

## License

MIT
