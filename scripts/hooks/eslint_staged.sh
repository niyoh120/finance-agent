#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
files=()

for f in "$@"; do
  files+=("$repo_root/$f")
done

cd "$repo_root/services/stock-api"
npx eslint --cache --max-warnings=0 --config eslint.config.mjs -- "${files[@]}"
