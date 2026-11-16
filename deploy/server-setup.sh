#!/usr/bin/env bash
# One-time setup: turn the server's copy of the game into a git checkout of the GitHub repo
# and install a cron job that runs deploy/update.sh every 5 minutes.
#
# Run it on the server as the user that owns the stack directory and can use docker:
#   ssh <user>@<server> 'bash -s' < deploy/server-setup.sh
#
# It backs the directory up first (to ~/syntax-stack-backup-<date>.tgz) and keeps untracked
# server files such as .env (tutor token) in place. Safe to re-run.
set -euo pipefail

REPO="${SYNTAX_STACK_REPO:-https://github.com/dohongminh-ui/Syntax-Stack.git}"
BRANCH="${SYNTAX_STACK_BRANCH:-main}"
DIR="${SYNTAX_STACK_DIR:-/opt/stacks/syntax-stack}"
LOG="$HOME/syntax-stack-update.log"

for cmd in git docker curl flock crontab; do
  command -v "$cmd" >/dev/null || { echo "Missing '$cmd' on the server; install it first." >&2; exit 1; }
done
[[ -d "$DIR" ]] || { echo "No $DIR on the server." >&2; exit 1; }

backup="$HOME/syntax-stack-backup-$(date +%Y%m%d-%H%M%S).tgz"
tar -czf "$backup" -C "$(dirname "$DIR")" "$(basename "$DIR")"
echo "Backup: $backup"

cd "$DIR"
if [[ ! -d .git ]]; then
  git init -q -b "$BRANCH"
  git remote add origin "$REPO"
fi
git remote set-url origin "$REPO"
git fetch -q origin "$BRANCH"
# -f: the files already here came from release bundles; GitHub is the source of truth now.
git checkout -q -f -B "$BRANCH" "origin/$BRANCH"
echo "Checkout: $(git log -1 --format='%h %s')"

# Always invoked through bash: git stores the script without the executable bit, and every
# `git reset --hard` in update.sh would strip a chmod +x again.
bash deploy/update.sh --force

line="*/5 * * * * bash $DIR/deploy/update.sh >> $LOG 2>&1"
( crontab -l 2>/dev/null | grep -vF "$DIR/deploy/update.sh" || true; echo "$line" ) | crontab -
echo "Cron: $line"
echo "Setup finished. Push to $BRANCH and the server picks it up within 5 minutes (log: $LOG)."
