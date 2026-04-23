from __future__ import annotations

import sys
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QSortFilterProxyModel, QAbstractTableModel,
    QModelIndex, QTimer,
)
from PyQt6.QtGui import QFont, QColor, QAction, QIcon
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTableView, QLabel, QPushButton, QLineEdit, QComboBox,
    QDockWidget, QStatusBar, QDialog, QDialogButtonBox, QTabWidget,
    QFormLayout, QSpinBox, QDoubleSpinBox, QTextEdit, QSplitter,
    QGroupBox, QMessageBox, QHeaderView, QFrame, QScrollArea,
    QProgressBar, QAbstractItemView, QMenu,
)

from . import database as db
from .psa_scraper import PSAScraper
from .ebay_scraper import EbayScraper
from .psa_catalog import PSACatalogScraper

SPORTS = ["", "Baseball", "Basketball", "Football", "Hockey", "Soccer",
          "Pokemon", "Magic: The Gathering", "Yu-Gi-Oh!", "Other TCG", "Other"]

COLUMNS = [
    ("id",              "ID",           40),
    ("card_name",       "Card Name",    220),
    ("year",            "Year",         55),
    ("sport",           "Sport/Category", 120),
    ("card_set",        "Set",          160),
    ("card_number",     "#",            55),
    ("variation",       "Variation",    110),
    ("player",          "Player/Char",  130),
    ("psa_pop_10",      "PSA 10",       65),
    ("psa_total_pop",   "Total Pop",    75),
    ("gem_rate",        "Gem Rate %",   80),
    ("ebay_avg_price",  "Avg $",        70),
    ("ebay_low_price",  "Low $",        70),
    ("ebay_high_price", "High $",       70),
    ("ebay_sold_count", "# Sold",       60),
    ("last_updated",    "Updated",      110),
]


# ---------------------------------------------------------------------------
# Table model
# ---------------------------------------------------------------------------

class CardTableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._data: list[dict] = []
        self._headers = [c[1] for c in COLUMNS]
        self._fields = [c[0] for c in COLUMNS]

    def refresh(self, filters: dict = None):
        self.beginResetModel()
        self._data = db.search_cards(filters)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self._fields)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._data):
            return None
        row = self._data[index.row()]
        field = self._fields[index.column()]
        val = row.get(field)

        if role == Qt.ItemDataRole.DisplayRole:
            if val is None:
                return ""
            if field == "gem_rate":
                return f"{val:.1f}%"
            if field in ("ebay_avg_price", "ebay_low_price", "ebay_high_price"):
                return f"${val:,.2f}" if val else ""
            if field == "last_updated" and val:
                return val[:10]
            return str(val)

        if role == Qt.ItemDataRole.BackgroundRole:
            if field == "gem_rate" and val is not None:
                if val >= 80:
                    return QColor("#c8f7c5")
                if val >= 50:
                    return QColor("#fef9c3")
                if val > 0:
                    return QColor("#fde8e8")

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if field in ("year", "psa_pop_10", "psa_total_pop", "gem_rate",
                         "ebay_avg_price", "ebay_low_price", "ebay_high_price",
                         "ebay_sold_count", "card_number", "id"):
                return Qt.AlignmentFlag.AlignCenter
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._headers[section]
        return None

    def get_card_id(self, row: int) -> Optional[int]:
        if 0 <= row < len(self._data):
            return self._data[row].get("id")
        return None

    def get_row_data(self, row: int) -> Optional[dict]:
        if 0 <= row < len(self._data):
            return self._data[row]
        return None


# ---------------------------------------------------------------------------
# Worker threads
# ---------------------------------------------------------------------------

class ScrapeWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(int)   # card_id
    error = pyqtSignal(int, str)

    def __init__(self, card_id: int):
        super().__init__()
        self.card_id = card_id

    def run(self):
        card = db.get_card(self.card_id)
        if not card:
            self.error.emit(self.card_id, "Card not found in database")
            return

        psa = PSAScraper()
        ebay = EbayScraper()

        # --- PSA ---
        psa_data = {}
        pop_url = card.get("psa_url", "")
        if pop_url:
            self.progress.emit(f"Fetching PSA population for: {card['card_name']}")
            psa_data = psa.get_population(pop_url)
        else:
            self.progress.emit(f"No PSA URL for {card['card_name']} — skipping PSA")

        # --- eBay ---
        query = card.get("ebay_search_query") or _build_ebay_query(card)
        self.progress.emit(f"Searching eBay sold listings: {query}")
        listings = ebay.search_sold(query)
        summary = ebay.summarize(listings)

        # Save to DB
        update = {**psa_data, **summary}
        db.update_card(self.card_id, update)
        if listings:
            db.save_ebay_listings(self.card_id, listings)

        self.done.emit(self.card_id)


def _build_ebay_query(card: dict) -> str:
    parts = []
    if card.get("card_name"):
        parts.append(card["card_name"])
    if card.get("year"):
        parts.append(str(card["year"]))
    if card.get("variation"):
        parts.append(card["variation"])
    parts.append("PSA 10")
    return " ".join(parts)[:100]


class BulkScrapeWorker(QThread):
    progress = pyqtSignal(str, int, int)   # message, current, total
    card_done = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, card_ids: list[int]):
        super().__init__()
        self.card_ids = card_ids
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        psa = PSAScraper()
        ebay = EbayScraper()
        total = len(self.card_ids)

        for i, cid in enumerate(self.card_ids):
            if self._abort:
                break
            card = db.get_card(cid)
            if not card:
                continue
            self.progress.emit(f"Processing {card['card_name']}", i + 1, total)

            psa_data = {}
            if card.get("psa_url"):
                psa_data = psa.get_population(card["psa_url"])

            query = card.get("ebay_search_query") or _build_ebay_query(card)
            listings = ebay.search_sold(query)
            summary = ebay.summarize(listings)

            db.update_card(cid, {**psa_data, **summary})
            if listings:
                db.save_ebay_listings(cid, listings)

            self.card_done.emit(cid)

        self.finished.emit()


# ---------------------------------------------------------------------------
# Catalog import worker
# ---------------------------------------------------------------------------

class CatalogImportWorker(QThread):
    progress = pyqtSignal(str, int, int)   # message, imported, total_sets
    card_imported = pyqtSignal(str, bool)  # card_name, was_new
    finished = pyqtSignal(int, int)        # total_imported, total_new

    def __init__(self, sets: list[dict], fetch_ebay: bool = False):
        super().__init__()
        self.sets = sets
        self.fetch_ebay = fetch_ebay
        self._abort = False
        self._scraper = PSACatalogScraper()

    def abort(self):
        self._abort = True
        self._scraper.abort()

    def run(self):
        ebay = EbayScraper() if self.fetch_ebay else None
        total_imported = 0
        total_new = 0

        for card, set_idx, total_sets in self._scraper.stream_cards(self.sets):
            if self._abort:
                break

            card_id, was_new = db.upsert_card(card)
            total_imported += 1
            if was_new:
                total_new += 1

            if self.fetch_ebay and ebay and was_new:
                query = _build_ebay_query(card)
                listings = ebay.search_sold(query)
                if listings:
                    summary = ebay.summarize(listings)
                    db.update_card(card_id, summary)
                    db.save_ebay_listings(card_id, listings)

            self.progress.emit(
                f"Set {set_idx}/{total_sets} — {card.get('card_name', '')}",
                total_imported,
                total_sets,
            )
            self.card_imported.emit(card.get("card_name", ""), was_new)

        self.finished.emit(total_imported, total_new)


# ---------------------------------------------------------------------------
# Background workers for catalog browsing
# ---------------------------------------------------------------------------

class _YearLoaderWorker(QThread):
    done = pyqtSignal(list)   # list of year dicts
    error = pyqtSignal(str)
    def __init__(self, cat):
        super().__init__()
        self.cat = cat
    def run(self):
        try:
            years = PSACatalogScraper().get_years(self.cat)
            self.done.emit(years)
        except Exception as e:
            self.error.emit(str(e))

class _SetLoaderWorker(QThread):
    done = pyqtSignal(list)   # list of set dicts
    error = pyqtSignal(str)
    def __init__(self, year):
        super().__init__()
        self.year = year
    def run(self):
        try:
            sets = PSACatalogScraper().get_sets(self.year)
            self.done.emit(sets)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Browse PSA Catalog dialog  (3-panel: Category → Year → Sets)
# ---------------------------------------------------------------------------

class BrowseCatalogDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Browse & Import PSA Catalog")
        self.setMinimumSize(860, 560)
        self._categories: list[dict] = PSACatalogScraper().get_categories()
        self._years: list[dict] = []
        self._sets: list[dict] = []
        self._worker: Optional[CatalogImportWorker] = None
        self._year_loader: Optional[_YearLoaderWorker] = None
        self._set_loader: Optional[_SetLoaderWorker] = None
        self._build_ui()
        self._populate_categories()

    def _build_ui(self):
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QCheckBox
        self._LW = QListWidgetItem

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Select a category → select a year → check sets → click Import Selected Sets"
        ))

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Panel 1: Categories
        p1 = QWidget(); v1 = QVBoxLayout(p1); v1.setContentsMargins(0,0,0,0)
        v1.addWidget(QLabel("<b>Category</b>"))
        self._cat_list = QListWidget()
        self._cat_list.currentRowChanged.connect(self._on_cat_selected)
        v1.addWidget(self._cat_list)
        splitter.addWidget(p1)

        # Panel 2: Years
        p2 = QWidget(); v2 = QVBoxLayout(p2); v2.setContentsMargins(0,0,0,0)
        v2.addWidget(QLabel("<b>Year</b>"))
        self._year_list = QListWidget()
        self._year_list.currentRowChanged.connect(self._on_year_selected)
        v2.addWidget(self._year_list)
        splitter.addWidget(p2)

        # Panel 3: Sets with checkboxes
        p3 = QWidget(); v3 = QVBoxLayout(p3); v3.setContentsMargins(0,0,0,0)
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("<b>Sets</b>"))
        self._chk_all_btn = QPushButton("✓ All")
        self._chk_all_btn.setMaximumWidth(55)
        self._chk_all_btn.clicked.connect(self._check_all)
        self._unchk_btn = QPushButton("✗ None")
        self._unchk_btn.setMaximumWidth(60)
        self._unchk_btn.clicked.connect(self._uncheck_all)
        hdr.addWidget(self._chk_all_btn)
        hdr.addWidget(self._unchk_btn)
        v3.addLayout(hdr)
        self._set_list = QListWidget()
        v3.addWidget(self._set_list)
        splitter.addWidget(p3)

        splitter.setSizes([160, 140, 400])
        layout.addWidget(splitter, 1)

        # Status bar
        self._status = QLabel("Select a category to begin.")
        layout.addWidget(self._status)

        # eBay toggle
        self._ebay_check = QCheckBox(
            "Also fetch eBay sold prices for new cards (much slower)"
        )
        layout.addWidget(self._ebay_check)

        # Progress
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        # Buttons
        btn_row = QHBoxLayout()
        self._import_btn = QPushButton("⬇  Import Selected Sets")
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._start_import)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setVisible(False)
        self._stop_btn.clicked.connect(self._stop_import)
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._import_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

    def _populate_categories(self):
        self._cat_list.clear()
        for cat in self._categories:
            self._cat_list.addItem(cat["name"])
        self._status.setText(f"{len(self._categories)} categories. Click one to load years.")

    # --- Category selected → load years in background ---
    def _on_cat_selected(self, row: int):
        if row < 0 or row >= len(self._categories):
            return
        cat = self._categories[row]
        self._year_list.clear()
        self._set_list.clear()
        self._years = []
        self._sets = []
        self._import_btn.setEnabled(False)
        self._status.setText(f"Loading years for {cat['name']}…")

        if self._year_loader and self._year_loader.isRunning():
            self._year_loader.terminate()

        self._year_loader = _YearLoaderWorker(cat)
        self._year_loader.done.connect(self._on_years_loaded)
        self._year_loader.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        self._year_loader.finished.connect(self._year_loader.deleteLater)
        self._year_loader.start()

    def _on_years_loaded(self, years: list):
        self._years = years
        self._year_list.clear()
        for y in years:
            self._year_list.addItem(y["label"])
        self._status.setText(f"{len(years)} years found. Click a year to see sets.")

    # --- Year selected → load sets in background ---
    def _on_year_selected(self, row: int):
        if row < 0 or row >= len(self._years):
            return
        year = self._years[row]
        self._set_list.clear()
        self._sets = []
        self._import_btn.setEnabled(False)
        self._status.setText(f"Loading sets for {year['label']}…")

        if self._set_loader and self._set_loader.isRunning():
            self._set_loader.terminate()

        self._set_loader = _SetLoaderWorker(year)
        self._set_loader.done.connect(self._on_sets_loaded)
        self._set_loader.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        self._set_loader.finished.connect(self._set_loader.deleteLater)
        self._set_loader.start()

    def _on_sets_loaded(self, sets: list):
        self._sets = sets
        self._set_list.clear()
        for s in sets:
            item = self._LW(s["name"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._set_list.addItem(item)
        n = len(sets)
        self._status.setText(
            f"{n} set{'s' if n != 1 else ''} found. Check any you want, then click Import."
        )
        self._import_btn.setEnabled(n > 0)

    def _check_all(self):
        for i in range(self._set_list.count()):
            self._set_list.item(i).setCheckState(Qt.CheckState.Checked)

    def _uncheck_all(self):
        for i in range(self._set_list.count()):
            self._set_list.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _get_checked_sets(self) -> list[dict]:
        return [
            self._sets[i]
            for i in range(self._set_list.count())
            if i < len(self._sets)
            and self._set_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _start_import(self):
        sets = self._get_checked_sets()
        if not sets:
            QMessageBox.information(self, "Nothing checked",
                                    "Tick at least one set checkbox first.")
            return

        self._worker = CatalogImportWorker(sets, self._ebay_check.isChecked())
        self._worker.progress.connect(self._on_import_progress)
        self._worker.finished.connect(self._on_import_finished)
        self._worker.finished.connect(self._worker.deleteLater)

        self._progress_bar.setRange(0, len(sets))
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._import_btn.setEnabled(False)
        self._stop_btn.setVisible(True)
        self._worker.start()

    def _on_import_progress(self, msg: str, imported: int, total_sets: int):
        self._progress_bar.setRange(0, max(total_sets, 1))
        self._progress_bar.setValue(imported)
        self._status.setText(msg)

    def _on_import_finished(self, total: int, new: int):
        self._progress_bar.setVisible(False)
        self._stop_btn.setVisible(False)
        self._import_btn.setEnabled(True)
        self._status.setText(
            f"Done — {total} cards processed, {new} new cards added to database."
        )

    def _stop_import(self):
        if self._worker:
            self._worker.abort()
        self._stop_btn.setVisible(False)

    def closeEvent(self, event):
        for w in (self._worker, self._year_loader, self._set_loader):
            if w and w.isRunning():
                if hasattr(w, "abort"):
                    w.abort()
                w.wait(2000)
        event.accept()


# ---------------------------------------------------------------------------
# Add / Edit card dialog
# ---------------------------------------------------------------------------

class CardDialog(QDialog):
    def __init__(self, parent, card: dict = None):
        super().__init__(parent)
        self._card = card or {}
        self._psa_url = card.get("psa_url", "") if card else ""
        self._psa_results: list[dict] = []
        self.setWindowTitle("Edit Card" if card else "Add Card")
        self.setMinimumWidth(620)
        self._build_ui()
        if card:
            self._populate(card)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # --- Tab 1: PSA Search ---
        search_tab = QWidget()
        sl = QVBoxLayout(search_tab)

        search_row = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("e.g. Charizard 1999 Base Set")
        self._search_btn = QPushButton("Search PSA Pop Report")
        self._search_btn.clicked.connect(self._do_psa_search)
        search_row.addWidget(QLabel("Search:"))
        search_row.addWidget(self._search_input, 1)
        search_row.addWidget(self._search_btn)
        sl.addLayout(search_row)

        self._psa_status = QLabel("Enter a search term and click Search.")
        sl.addWidget(self._psa_status)

        # Results list (displayed as a table-like widget)
        self._results_frame = QFrame()
        self._results_frame.setFrameShape(QFrame.Shape.StyledPanel)
        results_scroll = QScrollArea()
        results_scroll.setWidget(self._results_frame)
        results_scroll.setWidgetResizable(True)
        results_scroll.setMinimumHeight(180)
        self._results_layout = QVBoxLayout(self._results_frame)
        self._results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        sl.addWidget(results_scroll, 1)

        # PSA URL direct entry
        url_row = QHBoxLayout()
        self._psa_url_input = QLineEdit()
        self._psa_url_input.setPlaceholderText("Or paste PSA pop report URL directly")
        if self._psa_url:
            self._psa_url_input.setText(self._psa_url)
        url_row.addWidget(QLabel("PSA URL:"))
        url_row.addWidget(self._psa_url_input, 1)
        sl.addLayout(url_row)

        tabs.addTab(search_tab, "PSA Search")

        # --- Tab 2: Card Details ---
        details_tab = QWidget()
        fl = QFormLayout(details_tab)
        fl.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._name = QLineEdit()
        self._year = QSpinBox()
        self._year.setRange(1900, 2099)
        self._year.setValue(2024)
        self._year.setSpecialValueText(" ")
        self._sport = QComboBox()
        self._sport.addItems(SPORTS)
        self._card_set = QLineEdit()
        self._card_number = QLineEdit()
        self._variation = QLineEdit()
        self._player = QLineEdit()
        self._ebay_query = QLineEdit()
        self._ebay_query.setPlaceholderText("Auto-generated if left blank")
        self._notes = QTextEdit()
        self._notes.setMaximumHeight(70)

        fl.addRow("Card Name *", self._name)
        fl.addRow("Year", self._year)
        fl.addRow("Sport / Category", self._sport)
        fl.addRow("Set / Series", self._card_set)
        fl.addRow("Card Number", self._card_number)
        fl.addRow("Variation / Parallel", self._variation)
        fl.addRow("Player / Character", self._player)
        fl.addRow("eBay Search Query", self._ebay_query)
        fl.addRow("Notes", self._notes)

        tabs.addTab(details_tab, "Card Details")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, card: dict):
        self._name.setText(card.get("card_name", ""))
        if card.get("year"):
            self._year.setValue(int(card["year"]))
        idx = self._sport.findText(card.get("sport", ""))
        if idx >= 0:
            self._sport.setCurrentIndex(idx)
        self._card_set.setText(card.get("card_set", "") or "")
        self._card_number.setText(card.get("card_number", "") or "")
        self._variation.setText(card.get("variation", "") or "")
        self._player.setText(card.get("player", "") or "")
        self._ebay_query.setText(card.get("ebay_search_query", "") or "")
        self._notes.setPlainText(card.get("notes", "") or "")

    def _do_psa_search(self):
        query = self._search_input.text().strip()
        if not query:
            return
        self._psa_status.setText("Searching PSA…")
        self._search_btn.setEnabled(False)
        QTimer.singleShot(50, lambda: self._run_psa_search(query))

    def _run_psa_search(self, query: str):
        scraper = PSAScraper()
        results = scraper.search(query)
        self._psa_results = results

        # Clear previous results
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not results:
            self._psa_status.setText("No results found. Try a different search, or paste a URL directly.")
        else:
            self._psa_status.setText(f"Found {len(results)} result(s). Click one to select it.")
            for r in results:
                btn = QPushButton(f"{r.get('year', '')}  {r['name'][:80]}")
                btn.setStyleSheet("text-align: left; padding: 4px 8px;")
                btn.clicked.connect(lambda checked, res=r: self._select_psa_result(res))
                self._results_layout.addWidget(btn)

        self._search_btn.setEnabled(True)

    def _select_psa_result(self, result: dict):
        url = result.get("pop_url", "")
        self._psa_url_input.setText(url)
        self._psa_status.setText(f"Selected: {result['name'][:80]}")
        # Pre-fill details tab if fields are empty
        if result.get("name") and not self._name.text():
            self._name.setText(result["name"])
        if result.get("year") and self._year.value() == self._year.minimum():
            self._year.setValue(result["year"])
        if result.get("set") and not self._card_set.text():
            self._card_set.setText(result["set"])

    def _validate_and_accept(self):
        if not self._name.text().strip():
            QMessageBox.warning(self, "Required", "Card Name is required.")
            return
        self.accept()

    def get_data(self) -> dict:
        year_val = self._year.value()
        return {
            "card_name": self._name.text().strip(),
            "year": year_val if year_val != self._year.minimum() else None,
            "sport": self._sport.currentText() or None,
            "card_set": self._card_set.text().strip() or None,
            "card_number": self._card_number.text().strip() or None,
            "variation": self._variation.text().strip() or None,
            "player": self._player.text().strip() or None,
            "psa_url": self._psa_url_input.text().strip() or None,
            "ebay_search_query": self._ebay_query.text().strip() or None,
            "notes": self._notes.toPlainText().strip() or None,
        }


# ---------------------------------------------------------------------------
# eBay listings detail panel
# ---------------------------------------------------------------------------

class EbayPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._card_id: Optional[int] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._title_label = QLabel("Select a card to view eBay sold listings")
        self._title_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        layout.addWidget(self._title_label)

        self._table = QTableView()
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        self._model = _EbayListingModel()
        self._table.setModel(self._model)
        self._table.setColumnWidth(0, 350)
        self._table.setColumnWidth(1, 70)
        self._table.setColumnWidth(2, 90)
        self._table.setColumnWidth(3, 90)

    def load_card(self, card_id: int, card_name: str):
        self._card_id = card_id
        listings = db.get_ebay_listings(card_id)
        self._model.set_data(listings)
        self._title_label.setText(
            f"eBay Sold Listings — {card_name}  ({len(listings)} records)"
        )


class _EbayListingModel(QAbstractTableModel):
    _COLS = [("title", "Title", 350), ("price", "Price", 70),
             ("sold_date", "Sold Date", 90), ("condition", "Condition", 90)]

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []

    def set_data(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, _=QModelIndex()):
        return len(self._rows)

    def columnCount(self, _=QModelIndex()):
        return len(self._COLS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        field = self._COLS[index.column()][0]
        val = row.get(field)
        if role == Qt.ItemDataRole.DisplayRole:
            if field == "price" and val is not None:
                return f"${val:,.2f}"
            return str(val) if val is not None else ""
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._COLS[section][1]
        return None


# ---------------------------------------------------------------------------
# Filter panel
# ---------------------------------------------------------------------------

class FilterPanel(QWidget):
    filter_changed = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Full-text search
        layout.addWidget(QLabel("Search (any field):"))
        self._text = QLineEdit()
        self._text.setPlaceholderText("Name, player, set, notes…")
        self._text.textChanged.connect(self._emit)
        layout.addWidget(self._text)

        # Sport
        layout.addWidget(QLabel("Sport / Category:"))
        self._sport = QComboBox()
        self._sport.addItem("All")
        self._sport.addItems(SPORTS[1:])
        self._sport.currentIndexChanged.connect(self._emit)
        layout.addWidget(self._sport)

        # Year range
        yr_grp = QGroupBox("Year Range")
        yr_layout = QHBoxLayout(yr_grp)
        self._year_from = QSpinBox()
        self._year_from.setRange(1900, 2099)
        self._year_from.setSpecialValueText("Any")
        self._year_from.setValue(1900)
        self._year_to = QSpinBox()
        self._year_to.setRange(1900, 2099)
        self._year_to.setSpecialValueText("Any")
        self._year_to.setValue(2099)
        yr_layout.addWidget(self._year_from)
        yr_layout.addWidget(QLabel("–"))
        yr_layout.addWidget(self._year_to)
        self._year_from.valueChanged.connect(self._emit)
        self._year_to.valueChanged.connect(self._emit)
        layout.addWidget(yr_grp)

        # Gem Rate range
        gem_grp = QGroupBox("Gem Rate % Range")
        gem_layout = QHBoxLayout(gem_grp)
        self._gem_min = QDoubleSpinBox()
        self._gem_min.setRange(0, 100)
        self._gem_min.setDecimals(1)
        self._gem_min.setSpecialValueText("Any")
        self._gem_max = QDoubleSpinBox()
        self._gem_max.setRange(0, 100)
        self._gem_max.setDecimals(1)
        self._gem_max.setValue(100)
        self._gem_max.setSpecialValueText("Any")
        gem_layout.addWidget(self._gem_min)
        gem_layout.addWidget(QLabel("–"))
        gem_layout.addWidget(self._gem_max)
        self._gem_min.valueChanged.connect(self._emit)
        self._gem_max.valueChanged.connect(self._emit)
        layout.addWidget(gem_grp)

        # Price range
        price_grp = QGroupBox("Avg eBay Price ($)")
        price_layout = QHBoxLayout(price_grp)
        self._price_min = QDoubleSpinBox()
        self._price_min.setRange(0, 999999)
        self._price_min.setDecimals(2)
        self._price_min.setSpecialValueText("Any")
        self._price_max = QDoubleSpinBox()
        self._price_max.setRange(0, 999999)
        self._price_max.setDecimals(2)
        self._price_max.setValue(999999)
        self._price_max.setSpecialValueText("Any")
        price_layout.addWidget(self._price_min)
        price_layout.addWidget(QLabel("–"))
        price_layout.addWidget(self._price_max)
        self._price_min.valueChanged.connect(self._emit)
        self._price_max.valueChanged.connect(self._emit)
        layout.addWidget(price_grp)

        # PSA 10 pop min
        pop_grp = QGroupBox("Min PSA 10 Pop")
        pop_layout = QHBoxLayout(pop_grp)
        self._pop10_min = QSpinBox()
        self._pop10_min.setRange(0, 999999)
        self._pop10_min.setSpecialValueText("Any")
        pop_layout.addWidget(self._pop10_min)
        self._pop10_min.valueChanged.connect(self._emit)
        layout.addWidget(pop_grp)

        # Reset button
        reset_btn = QPushButton("Reset Filters")
        reset_btn.clicked.connect(self._reset)
        layout.addWidget(reset_btn)
        layout.addStretch()

    def _emit(self):
        self.filter_changed.emit(self._build_filters())

    def _build_filters(self) -> dict:
        f: dict = {}
        text = self._text.text().strip()
        if text:
            f["text"] = text

        sport = self._sport.currentText()
        if sport and sport != "All":
            f["sport"] = sport

        yr_from = self._year_from.value()
        yr_to = self._year_to.value()
        if yr_from > 1900:
            f["year_from"] = yr_from
        if yr_to < 2099:
            f["year_to"] = yr_to

        gem_min = self._gem_min.value()
        gem_max = self._gem_max.value()
        if gem_min > 0:
            f["gem_rate_min"] = gem_min
        if gem_max < 100:
            f["gem_rate_max"] = gem_max

        price_min = self._price_min.value()
        price_max = self._price_max.value()
        if price_min > 0:
            f["price_min"] = price_min
        if price_max < 999999:
            f["price_max"] = price_max

        pop10 = self._pop10_min.value()
        if pop10 > 0:
            f["pop_10_min"] = pop10

        return f

    def _reset(self):
        self._text.clear()
        self._sport.setCurrentIndex(0)
        self._year_from.setValue(1900)
        self._year_to.setValue(2099)
        self._gem_min.setValue(0)
        self._gem_max.setValue(100)
        self._price_min.setValue(0)
        self._price_max.setValue(999999)
        self._pop10_min.setValue(0)
        self._emit()


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        db.init_db()
        self.setWindowTitle("PSA Card Tracker")
        self.resize(1400, 800)
        self._workers: list[QThread] = []
        self._active_scrapes: int = 0
        self._catalog_worker: Optional[CatalogImportWorker] = None
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self._refresh_all)
        self._build_ui()
        self._refresh_table()

    def _build_ui(self):
        # --- Toolbar ---
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        act_add = QAction("➕  Add Card", self)
        act_add.setShortcut("Ctrl+N")
        act_add.triggered.connect(self._add_card)

        act_browse = QAction("🌐  Browse PSA Catalog", self)
        act_browse.setShortcut("Ctrl+B")
        act_browse.triggered.connect(self._browse_catalog)

        act_refresh_sel = QAction("🔄  Refresh Selected", self)
        act_refresh_sel.setShortcut("F5")
        act_refresh_sel.triggered.connect(self._refresh_selected)

        act_refresh_all = QAction("🔄  Refresh All", self)
        act_refresh_all.setShortcut("Ctrl+Shift+R")
        act_refresh_all.triggered.connect(self._refresh_all)

        act_export = QAction("📊  Export CSV", self)
        act_export.triggered.connect(self._export_csv)

        act_auto = QAction("⏰  Auto-Refresh", self)
        act_auto.triggered.connect(self._configure_auto_refresh)

        for act in (act_add, act_browse, act_refresh_sel, act_refresh_all, act_export, act_auto):
            tb.addAction(act)

        # Progress bar in toolbar
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(200)
        self._progress.setMaximumHeight(18)
        self._progress.setVisible(False)
        tb.addWidget(self._progress)
        self._progress_label = QLabel("")
        tb.addWidget(self._progress_label)

        # --- Central splitter ---
        splitter_v = QSplitter(Qt.Orientation.Vertical)
        self.setCentralWidget(splitter_v)

        splitter_h = QSplitter(Qt.Orientation.Horizontal)
        splitter_v.addWidget(splitter_h)

        # --- Filter dock ---
        self._filter_panel = FilterPanel()
        self._filter_panel.filter_changed.connect(self._on_filter_changed)
        filter_dock = QDockWidget("Filters", self)
        filter_dock.setWidget(self._filter_panel)
        filter_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        filter_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, filter_dock)

        # --- Card table ---
        self._model = CardTableModel()
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.doubleClicked.connect(self._edit_card)
        self._table.selectionModel().currentRowChanged.connect(self._on_row_selected)

        hdr = self._table.horizontalHeader()
        hdr.setStretchLastSection(True)
        for i, (_, _, width) in enumerate(COLUMNS):
            self._table.setColumnWidth(i, width)

        splitter_h.addWidget(self._table)

        # --- eBay panel at bottom ---
        self._ebay_panel = EbayPanel()
        splitter_v.addWidget(self._ebay_panel)
        splitter_v.setSizes([550, 200])

        # --- Status bar ---
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._count_label = QLabel()
        self._status.addWidget(self._count_label)

    # -----------------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------------

    def _refresh_table(self, filters: dict = None):
        self._model.refresh(filters)
        self._count_label.setText(f"  {self._model.rowCount()} card(s) in database")

    def _on_filter_changed(self, filters: dict):
        self._refresh_table(filters)

    def _on_row_selected(self, current: QModelIndex, _previous: QModelIndex):
        row = current.row()
        card_id = self._model.get_card_id(row)
        card = self._model.get_row_data(row)
        if card_id and card:
            self._ebay_panel.load_card(card_id, card.get("card_name", ""))

    def _add_card(self):
        dlg = CardDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            card_id = db.add_card(data)
            self._refresh_table()
            self._status.showMessage(f"Added: {data['card_name']}", 3000)
            # Auto-scrape the new card
            self._scrape_card(card_id)

    def _edit_card(self, index: QModelIndex):
        card_id = self._model.get_card_id(index.row())
        card = db.get_card(card_id)
        if not card:
            return
        dlg = CardDialog(self, card)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            db.update_card(card_id, data)
            self._refresh_table()
            self._status.showMessage(f"Saved: {data['card_name']}", 3000)

    def _delete_card(self, card_id: int):
        card = db.get_card(card_id)
        if not card:
            return
        reply = QMessageBox.question(
            self, "Delete Card",
            f"Delete '{card['card_name']}'?\nThis also removes all saved eBay listings.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            db.delete_card(card_id)
            self._refresh_table()
            self._status.showMessage("Card deleted.", 3000)

    def _context_menu(self, pos):
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        card_id = self._model.get_card_id(index.row())
        card = self._model.get_row_data(index.row())
        if not card_id:
            return

        menu = QMenu(self)
        menu.addAction("✏️  Edit Card", lambda: self._edit_card(index))
        menu.addAction("🔄  Refresh This Card", lambda: self._scrape_card(card_id))
        menu.addSeparator()

        psa_url = card.get("psa_url")
        if psa_url:
            import webbrowser
            menu.addAction("🔗  Open PSA Pop Report", lambda: webbrowser.open(psa_url))

        ebay_q = card.get("ebay_search_query") or _build_ebay_query(card)
        import urllib.parse
        ebay_url = f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote(ebay_q)}&LH_Complete=1&LH_Sold=1"
        import webbrowser
        menu.addAction("🛒  View on eBay", lambda: webbrowser.open(ebay_url))

        menu.addSeparator()
        menu.addAction("🗑️  Delete Card", lambda: self._delete_card(card_id))
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _refresh_selected(self):
        rows = set(idx.row() for idx in self._table.selectedIndexes())
        ids = [self._model.get_card_id(r) for r in rows if self._model.get_card_id(r)]
        if not ids:
            self._status.showMessage("No cards selected.", 2000)
            return
        for cid in ids:
            self._scrape_card(cid)

    def _refresh_all(self):
        all_cards = db.search_cards()
        ids = [c["id"] for c in all_cards]
        if not ids:
            self._status.showMessage("No cards in database.", 2000)
            return
        self._start_bulk_scrape(ids)

    def _scrape_card(self, card_id: int):
        worker = ScrapeWorker(card_id)
        worker.progress.connect(lambda msg: self._status.showMessage(msg))
        worker.done.connect(self._on_scrape_done)
        worker.error.connect(lambda cid, err: self._status.showMessage(f"Error: {err}", 4000))
        worker.finished.connect(worker.deleteLater)
        self._workers.append(worker)
        self._active_scrapes += 1
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        worker.start()

    def _on_scrape_done(self, card_id: int):
        self._active_scrapes = max(0, self._active_scrapes - 1)
        self._refresh_table()
        if self._active_scrapes == 0:
            self._progress.setVisible(False)
            self._progress_label.setText("")
            self._status.showMessage("Refresh complete.", 3000)

    def _start_bulk_scrape(self, ids: list[int]):
        self._progress.setVisible(True)
        self._progress.setRange(0, len(ids))
        self._progress.setValue(0)
        worker = BulkScrapeWorker(ids)
        worker.progress.connect(self._on_bulk_progress)
        worker.card_done.connect(self._on_bulk_card_done)
        worker.finished.connect(self._on_bulk_finished)
        worker.finished.connect(worker.deleteLater)
        self._workers.append(worker)
        worker.start()

    def _on_bulk_progress(self, msg: str, current: int, total: int):
        self._progress.setRange(0, total)
        self._progress.setValue(current)
        self._progress_label.setText(f"  {msg}")

    def _on_bulk_card_done(self, card_id: int):
        self._refresh_table()

    def _on_bulk_finished(self):
        self._progress.setVisible(False)
        self._progress_label.setText("")
        self._status.showMessage("All cards refreshed.", 3000)

    def _browse_catalog(self):
        dlg = BrowseCatalogDialog(self)
        dlg.exec()
        # Refresh table after catalog import may have added cards
        self._refresh_table()

    def _configure_auto_refresh(self):
        from PyQt6.QtWidgets import QInputDialog
        intervals = ["Off", "Every 1 hour", "Every 6 hours", "Every 12 hours", "Every 24 hours"]
        interval_ms = {"Off": 0, "Every 1 hour": 3_600_000, "Every 6 hours": 21_600_000,
                       "Every 12 hours": 43_200_000, "Every 24 hours": 86_400_000}
        current = "Off" if not self._auto_refresh_timer.isActive() else "Active"
        choice, ok = QInputDialog.getItem(
            self, "Auto-Refresh", "Automatically re-fetch gem rates and eBay prices:", intervals, 0, False
        )
        if not ok:
            return
        ms = interval_ms.get(choice, 0)
        if ms == 0:
            self._auto_refresh_timer.stop()
            self._status.showMessage("Auto-refresh disabled.", 3000)
        else:
            self._auto_refresh_timer.start(ms)
            self._status.showMessage(f"Auto-refresh set: {choice}", 3000)

    def _on_catalog_progress(self, msg: str, imported: int, total_sets: int):
        self._progress.setRange(0, total_sets)
        self._progress.setValue(imported)
        self._progress_label.setText(f"  {msg}")

    def _on_catalog_finished(self, total: int, new: int):
        self._progress.setVisible(False)
        self._progress_label.setText("")
        self._refresh_table()
        self._status.showMessage(f"Catalog import done — {total} cards processed, {new} new.", 5000)

    def _export_csv(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "cards.csv", "CSV Files (*.csv)")
        if not path:
            return
        import csv
        cards = db.search_cards()
        if not cards:
            self._status.showMessage("No cards to export.", 2000)
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cards[0].keys())
            writer.writeheader()
            writer.writerows(cards)
        self._status.showMessage(f"Exported {len(cards)} cards to {path}", 4000)

    def closeEvent(self, event):
        for w in self._workers:
            if hasattr(w, "abort"):
                w.abort()
            if w.isRunning():
                w.wait(2000)
        # Shut down the shared headless browser
        from . import browser as _browser
        _browser.quit()
        event.accept()
