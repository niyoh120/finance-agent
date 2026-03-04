#!/usr/bin/env python3
from __future__ import annotations

import re
import sys

SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def main() -> int:
    paths = [p for p in sys.argv[1:] if p]
    if not paths:
        return 0

    invalid: list[str] = []

    for path in paths:
        for segment in path.split("/"):
            if " " in segment or not SEGMENT_RE.match(segment):
                invalid.append(path)
                break

    if invalid:
        print("ERROR: 文件名/目录名不符合规则（禁止空格，仅允许字母、数字、._-）:")
        for p in invalid:
            print(f"  - {p}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
