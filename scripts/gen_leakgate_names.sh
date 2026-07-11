#!/usr/bin/env bash
# Seed/refresh the gitignored "known repo names" denylist (scripts/.leakgate-names.local) that
# scripts/leak_gate.py reads. OPT-IN CONVENIENCE ONLY — this is a one-shot generator you run by
# hand and then REVIEW/PRUNE; it is NOT part of the leak-gate's runtime (the gate stays fast,
# offline, and deterministic by reading only the static local file).
#
# Candidates come from your PRIVATE remotes and local clones — sources an automated tool must not
# invent. Review the output: drop over-broad names (a private repo literally named "api"/"utils"
# would reject every fixture mentioning it) and ADD non-repo sensitive tokens the gate should also
# block (employer/client names, internal codenames, product names) that no remote list contains.
#
#   scripts/gen_leakgate_names.sh            # merge candidates into the local file (never clobbers)
#
# Requires (all optional; each is skipped if absent): gh (GitHub), glab (GitLab). Local .git remotes
# are always scanned. Nothing is committed — the target file is gitignored.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
out="$here/.leakgate-names.local"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

emit() { printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]' | grep -E '.' >>"$tmp" || true; }

# 1) GitHub private repo names (needs `gh auth login`)
if command -v gh >/dev/null 2>&1; then
  gh repo list --visibility private --limit 1000 --json name --jq '.[].name' 2>/dev/null \
    | while IFS= read -r n; do emit "$n"; done || true
fi

# 2) GitLab private/internal project paths (needs `glab auth login`)
if command -v glab >/dev/null 2>&1; then
  glab repo list --per-page 1000 2>/dev/null \
    | awk '{print $1}' | sed 's#.*/##' | while IFS= read -r n; do [ -n "$n" ] && emit "$n"; done || true
fi

# 3) Local clones: repo dir names + remote-URL repo slugs under $HOME (bounded depth)
while IFS= read -r gitdir; do
  repo="$(dirname "$gitdir")"
  emit "$(basename "$repo")"
  git -C "$repo" remote -v 2>/dev/null \
    | awk '{print $2}' | sed -E 's#\.git$##; s#.*[/:]##' | while IFS= read -r n; do [ -n "$n" ] && emit "$n"; done || true
done < <(find "$HOME" -maxdepth 4 -type d -name .git 2>/dev/null)

# Merge with any existing hand-curated entries; keep the header; de-dupe; never clobber.
{
  if [ -f "$out" ]; then grep -E '^#|^\s*$' "$out" || true; else
    printf '# Owner-supplied "known repo names" denylist for scripts/leak_gate.py.\n'
    printf '# GITIGNORED — never commit. One name per line; #-comments and blanks ignored.\n'
  fi
  { [ -f "$out" ] && grep -vE '^#|^\s*$' "$out" || true; cat "$tmp"; } | sort -u | grep -E '.'
} >"$out.new"
mv "$out.new" "$out"

n="$(grep -cvE '^#|^\s*$' "$out" || true)"
echo "Wrote $n name(s) to $out (gitignored). REVIEW & PRUNE before relying on it:"
echo "  - drop over-broad/common names that would false-positive on fixtures"
echo "  - add non-repo sensitive tokens (employers, codenames, people) the gate should block"
