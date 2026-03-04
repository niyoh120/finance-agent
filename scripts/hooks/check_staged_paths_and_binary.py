#!/usr/bin/env python3
from __future__ import annotations

import sys

FORBIDDEN_SEGMENTS = {"node_modules", "dist", ".venv"}


def _looks_binary(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(4096)
    except OSError:
        return False
    return b"\x00" in chunk


def main() -> int:
    files = [p for p in sys.argv[1:] if p]
    if not files:
        return 0

    bad_paths: list[str] = []
    binary_files: list[str] = []
    for path in files:
        segments = set(path.split("/"))
        if FORBIDDEN_SEGMENTS & segments:
            bad_paths.append(path)
        if _looks_binary(path):
            binary_files.append(path)

    if bad_paths:
        print("ERROR: 检测到禁止提交的路径（node_modules/dist/.venv）:")
        for p in bad_paths:
            print(f"  - {p}")
        return 1

    if binary_files:
        print("ERROR: 检测到二进制文件提交:")
        for p in sorted(set(binary_files)):
            print(f"  - {p}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
