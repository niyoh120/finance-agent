#!/usr/bin/env bash
set -euo pipefail

if git diff --cached --name-only --diff-filter=ACMRTUXB | grep -Eq '^services/stock-api/(src/.*\.(ts|tsx)|tsconfig\.json|package\.json|eslint\.config\.(js|mjs|cjs))$'; then
  npm --prefix services/stock-api run -s typecheck
fi
