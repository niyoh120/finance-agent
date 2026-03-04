#!/usr/bin/env python3
from __future__ import annotations

import py_compile
import sys


def main() -> int:
    files = [f for f in sys.argv[1:] if f.endswith(".py")]
    if not files:
        return 0

    failed = False
    for file_path in files:
        try:
            py_compile.compile(file_path, doraise=True)
        except py_compile.PyCompileError as exc:
            failed = True
            print(exc.msg)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
