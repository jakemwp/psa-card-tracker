import sys
import os

# High-DPI support
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

# ---------------------------------------------------------------------------
# Dependency check — show a clear message if install.bat was not run
# ---------------------------------------------------------------------------
REQUIRED = {
    "PyQt6":         "PyQt6",
    "requests":      "requests",
    "bs4":           "beautifulsoup4",
    "lxml":          "lxml",
    "curl_cffi":     "curl-cffi",
}

missing = []
for module, package in REQUIRED.items():
    try:
        __import__(module)
    except ImportError:
        missing.append(package)

if missing:
    print("=" * 55)
    print("  ERROR: Missing required packages:")
    for p in missing:
        print(f"    - {p}")
    print()
    print("  Please run install.bat and try again.")
    print("=" * 55)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "PSA Card Tracker — Missing Dependencies",
            "The following packages are not installed:\n\n"
            + "\n".join(f"  • {p}" for p in missing)
            + "\n\nPlease run install.bat and try again."
        )
    except Exception:
        input("\nPress Enter to exit...")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Normal startup
# ---------------------------------------------------------------------------
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor

from app.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("PSA Card Tracker")
    app.setOrganizationName("CardTracker")

    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#1a73e8"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
