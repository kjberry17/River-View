"""Compatibility launcher for the Replit fishing dashboard."""

import os
import sys
from pathlib import Path

dashboard_dir = Path(__file__).parent / "artifacts" / "fishing-dashboard"
os.chdir(dashboard_dir)
sys.path.insert(0, str(dashboard_dir))

from app import app  # noqa: E402


def main():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
