#!/usr/bin/env bash
# CI guard: a pull request that closes an issue labelled "correction" must change a check,
# either a rule in checks/rules.tsv or a test file. Otherwise the mistake can come back.
# Managed by the dev-repo-init skill.
set -euo pipefail
: "${PR_NUMBER:?PR_NUMBER is not set}"
repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is not set}"
# Only issues of this repo count: the workflow token cannot read another repo's labels.
issues=$(gh pr view "$PR_NUMBER" -R "$repo" --json closingIssuesReferences \
  --jq ".closingIssuesReferences[] | select((.repository.owner.login + \"/\" + .repository.name) == \"$repo\") | .number")
is_correction=no
for n in $issues; do
  labels=$(gh issue view "$n" -R "$repo" --json labels --jq '.labels[].name')
  case $'\n'"$labels"$'\n' in *$'\n'correction$'\n'*) is_correction=yes ;; esac
done
if [ "$is_correction" = no ]; then
  echo "guard: this pull request closes no correction issue; nothing to enforce"
  exit 0
fi
files=$(gh pr diff "$PR_NUMBER" -R "$repo" --name-only)
# A check is a changed rules file, or a changed test file that is source code (not a README).
test_path='(^|/)(tests?|__tests__|spec)/|(_test|\.test|\.spec)\.[A-Za-z0-9]+$|(^|/)test_[^/]+$'
code_ext='\.(py|js|mjs|cjs|ts|tsx|jsx|go|rs|rb|java|kt|swift|c|cc|cpp|cs|php|sh|ex|exs)$'
tests=$(grep -E "$test_path" <<<"$files" || true)
if grep -qx 'checks/rules\.tsv' <<<"$files" || grep -qE "$code_ext" <<<"$tests"; then
  echo "guard: the correction leaves a check behind"
  exit 0
fi
echo "GUARD FAILED: this pull request closes a correction issue but changes no check." >&2
echo "Add a rule to checks/rules.tsv, or a test that fails on the old code and passes on the new." >&2
exit 1
