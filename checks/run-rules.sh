#!/usr/bin/env bash
# Generic engine: fails when a file of the repo (tracked or new, not ignored) matches a rule in checks/rules.tsv.
# Rule line: <extended regex> TAB <path prefix> TAB <message that says how to fix it>
# Managed by the dev-repo-init skill. Add rules to checks/rules.tsv, not here.
set -euo pipefail
cd "$(dirname "$0")/.."
failed=0
while IFS=$'\t' read -r pattern prefix message; do
  case "$pattern" in ''|'#'*) continue ;; esac
  if [ -z "${prefix:-}" ] || [ -z "${message:-}" ]; then
    echo "checks/rules.tsv: a rule needs three tab-separated fields: $pattern" >&2
    exit 2
  fi
  # A rule that cannot run must fail the check, never pass it.
  rc=0; grep -qE -- "$pattern" /dev/null 2>/dev/null || rc=$?
  if [ "$rc" -gt 1 ]; then
    echo "checks/rules.tsv: invalid regular expression: $pattern" >&2
    exit 2
  fi
  list="$(mktemp)"
  # Tracked files plus new ones not yet added, so the check also sees work in progress.
  if ! git ls-files -z --cached --others --exclude-standard -- "$prefix" ':!checks/rules.tsv' > "$list"; then
    rm -f "$list"; echo "checks/rules.tsv: could not list files under: $prefix" >&2; exit 2
  fi
  if [ ! -s "$list" ]; then
    rm -f "$list"; echo "checks/rules.tsv: the path prefix matches no file: $prefix" >&2; exit 2
  fi
  hits=$(xargs -0 grep -nIE -- "$pattern" /dev/null < "$list" 2>/dev/null || true)
  rm -f "$list"
  if [ -n "$hits" ]; then
    failed=1
    printf 'RULE BROKEN: %s\n' "$message"
    printf '%s\n' "$hits" | sed 's/^/  /'
  fi
done < checks/rules.tsv
if [ "$failed" -ne 0 ]; then
  echo "Fix the code. Do not edit checks/ to make this pass." >&2
  exit 1
fi
echo "rules: ok"
