#!/usr/bin/env bash
# Pull the latest commit of the GitHub branch and redeploy the game when it changed.
#
#   deploy/update.sh            update only if origin/<branch> moved (what cron runs)
#   deploy/update.sh --force    rebuild and restart even if nothing changed
#
# Untracked server files (.env with the tutor token, backend/data/review/...) are never touched.
# If the new build does not answer /api/health within ~60 s, it rolls back to the previous commit.
#
# Env: SYNTAX_STACK_BRANCH (default main), SYNTAX_STACK_PORT (default 8000).

# Everything runs inside main() so bash has read the whole file before `git reset` can replace it.
main() {
  set -euo pipefail
  cd "$(dirname "$(readlink -f "$0")")/.."

  local branch="${SYNTAX_STACK_BRANCH:-main}"
  local port="${SYNTAX_STACK_PORT:-8000}"
  local force="${1:-}"

  exec 9>"/tmp/syntax-stack-update.lock"
  if ! flock -n 9; then echo "$(stamp) another update is already running"; return 0; fi

  git fetch --quiet origin "$branch"
  local old new
  old="$(git rev-parse HEAD)"
  new="$(git rev-parse "origin/$branch")"
  if [[ "$old" == "$new" && "$force" != "--force" ]]; then return 0; fi

  echo "$(stamp) updating ${old:0:12} -> ${new:0:12}"
  git reset --hard --quiet "$new"

  if deploy "$new" && healthy "$port"; then
    # (healthy tries every address the app may be bound to; see health_hosts)
    echo "$(stamp) deployed ${new:0:12}"
    docker image prune -f >/dev/null 2>&1 || true
    return 0
  fi

  echo "$(stamp) new build is not healthy, rolling back to ${old:0:12}"
  git reset --hard --quiet "$old"
  deploy "$old" && healthy "$port" && echo "$(stamp) rolled back to ${old:0:12}"
  return 1
}

stamp() { date '+%F %T'; }

deploy() {
  # The commit id becomes the asset version stamped on every CSS/JS URL (see app/main.py).
  SYNTAX_STACK_BUILD="${1:0:12}" docker compose up -d --build --remove-orphans
}

# Where to look for /api/health: SYNTAX_STACK_HEALTH_HOST if set, the SYNTAX_STACK_BIND address the
# app listens on (environment or .env, as compose.yaml reads it), and loopback.
health_hosts() {
  local bind="${SYNTAX_STACK_BIND:-}"
  if [[ -z "$bind" && -f .env ]]; then
    bind="$(grep -E '^[[:space:]]*SYNTAX_STACK_BIND=' .env | tail -n 1 | cut -d= -f2- | tr -d "\"' \r")"
  fi
  [[ "$bind" == "0.0.0.0" ]] && bind=""
  printf '%s\n' ${SYNTAX_STACK_HEALTH_HOST:-} $bind 127.0.0.1 | awk 'NF && !seen[$0]++'
}

healthy() {
  local i host hosts
  hosts="$(health_hosts)"
  for i in $(seq 1 30); do
    for host in $hosts; do
      if curl -fsS -m 3 "http://$host:$1/api/health" >/dev/null 2>&1; then return 0; fi
    done
    sleep 2
  done
  echo "$(stamp) no answer from /api/health on: $(echo $hosts) (port $1)"
  return 1
}

main "$@"
exit $?
