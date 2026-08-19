from __future__ import annotations

import sys

from diagnostics import main


if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1].startswith("-"):
        sys.argv.insert(1, "pir")
    raise SystemExit(main())
