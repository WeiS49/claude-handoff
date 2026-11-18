#!/usr/bin/env bash
# This project's own lint and test commands. Owned by the project: edit freely.
set -euo pipefail
# --locked: a missing or stale uv.lock fails here instead of being re-resolved silently.
uv sync --locked --quiet
# Pinned on purpose: ruff's default rules change between releases, and an unpinned run can
# turn CI red with no change in this repo. Bump the version deliberately, in its own change.
uvx ruff@0.17.5 check .
uv run pytest -q
