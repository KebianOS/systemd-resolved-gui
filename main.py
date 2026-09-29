#!/usr/bin/env python3
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault(
    "SYSTEMD_RESOLVED_GUI_LOCALE_DIR",
    str(PROJECT_ROOT / "build/locale"),
)

from systemd_resolved_gui.app import main


if __name__ == "__main__":
    main()
