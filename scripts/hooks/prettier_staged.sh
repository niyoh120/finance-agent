#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
files=()

for f in "$@"; do
  files+=("$repo_root/$f")
done

cd "$repo_root/services/stock-api"
npx prettier --write --ignore-unknown -- "${files[@]}"
