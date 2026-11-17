#!/usr/bin/env bash
# MealConnect — verify the local development environment.
# Usage (from the project root):  ./scripts/check-env.sh
set -u
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"

pass=0; fail=0
ok()  { printf "  \033[32m✔\033[0m %-22s %s\n" "$1" "$2"; pass=$((pass+1)); }
bad() { printf "  \033[31m✘\033[0m %-22s %s\n" "$1" "$2"; fail=$((fail+1)); }
check() { # name, command producing version text
  local out; if out=$(eval "$2" 2>/dev/null) && [ -n "$out" ]; then ok "$1" "$out"; else bad "$1" "not found / not running"; fi
}

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Tools"
check "Homebrew"        "brew --version | head -1"
check "Git"             "git --version"
check "Python 3.13"     "python3 --version"
check "Node (LTS 24)"   "node -v | grep -E '^v24\.'"
check "npm"             "npm -v"
check "VS Code CLI"     "code --version | head -1"
check "psql"            "psql --version"
check "Docker CLI"      "docker --version"
check "Docker Compose"  "docker compose version"

echo "Services"
check "PostgreSQL"      "pg_isready -h localhost"
check "Redis"           "redis-cli ping | grep PONG"
check "Docker engine"   "docker info --format '{{.ServerVersion}}'"

echo "Project"
check "Git repository"  "git -C '$ROOT' rev-parse --is-inside-work-tree"
check "backend/.venv"   "'$ROOT/backend/.venv/bin/python' --version"
check "backend/.env"    "test -f '$ROOT/backend/.env' && echo present"
check ".env ignored"    "git -C '$ROOT' check-ignore backend/.env"
if [ -f "$ROOT/backend/.env" ]; then
  DB_URL=$(grep '^DATABASE_URL=' "$ROOT/backend/.env" | cut -d= -f2- | sed 's/+psycopg//')
  check "DB login (app role)" "psql '$DB_URL' -tAc 'select current_user'"
fi

echo
echo "Passed: $pass   Failed: $fail"
[ "$fail" -eq 0 ]
