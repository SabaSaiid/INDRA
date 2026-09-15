#!/usr/bin/env bash
# ==============================================================================
# INDRA Frontend Pre-Flight Diagnostic Doctor
# Intelligent National Disaster & Weather Platform
# ==============================================================================

set -eo pipefail

# ANSI Colors
if [[ -t 1 ]]; then
  BOLD=$'\033[1m'
  GREEN=$'\033[0;32m'
  CYAN=$'\033[0;36m'
  YELLOW=$'\033[0;33m'
  RED=$'\033[0;31m'
  RESET=$'\033[0m'
else
  BOLD=""
  GREEN=""
  CYAN=""
  YELLOW=""
  RED=""
  RESET=""
fi

FRONTEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FRONTEND_DIR"

DEV_PORT="${PORT:-3000}"
ERRORS=0
WARNINGS=0

echo "${CYAN}${BOLD}🩺 [INDRA Doctor] Auditing Frontend Environment...${RESET}"

# 1. Check Node.js Version
NODE_VER=$(node -v 2>/dev/null || true)
if [[ -z "$NODE_VER" ]]; then
  echo "  ${RED}✘ Node.js not found in PATH${RESET}"
  ERRORS=$((ERRORS + 1))
else
  NODE_MAJOR=$(echo "$NODE_VER" | tr -d 'v' | cut -d '.' -f1)
  if [[ "$NODE_MAJOR" -ge 18 ]]; then
    echo "  ${GREEN}✓ Node.js Runtime:${RESET}       $NODE_VER (>= 18 required for Next.js 14)"
  else
    echo "  ${RED}✘ Node.js Runtime:${RESET}       $NODE_VER (Upgrade to Node 18+ required)"
    ERRORS=$((ERRORS + 1))
  fi
fi

# 2. Check Port 3000 Status
PORT_PIDS=$(lsof -ti :"$DEV_PORT" -sTCP:LISTEN 2>/dev/null || true)
if [[ -n "$PORT_PIDS" ]]; then
  echo "  ${GREEN}✓ Port $DEV_PORT Active:${RESET}        PID(s) $PORT_PIDS listening (auto-cleared by 'predev' before new starts)"
else
  echo "  ${GREEN}✓ Port $DEV_PORT Status:${RESET}        Port $DEV_PORT is completely free"
fi

# 3. Check Dependencies & Node Modules
if [[ ! -d "node_modules" ]]; then
  echo "  ${RED}✘ Missing node_modules:${RESET}   Run 'npm install'"
  ERRORS=$((ERRORS + 1))
else
  if [[ -f "node_modules/next/package.json" ]]; then
    INSTALLED_NEXT_VER=$(node -p "require('./node_modules/next/package.json').version" 2>/dev/null || echo "unknown")
    echo "  ${GREEN}✓ Next.js Framework:${RESET}     v$INSTALLED_NEXT_VER"
  else
    echo "  ${RED}✘ Missing Next.js package in node_modules${RESET}"
    ERRORS=$((ERRORS + 1))
  fi

  if [[ -f "node_modules/maplibre-gl/package.json" ]]; then
    INSTALLED_MAP_VER=$(node -p "require('./node_modules/maplibre-gl/package.json').version" 2>/dev/null || echo "unknown")
    echo "  ${GREEN}✓ MapLibre GL Engine:${RESET}    v$INSTALLED_MAP_VER (3D Globe)"
  else
    echo "  ${RED}✘ Missing maplibre-gl in node_modules${RESET}"
    ERRORS=$((ERRORS + 1))
  fi
fi

# 4. Check Stale .next Build Cache
AUTO_CLEANED=false
if [[ -d ".next" ]]; then
  # Compare modification time of .next with package.json and config files
  CONFIG_FILES=("package.json" "package-lock.json" "next.config.mjs" "tailwind.config.ts")
  STALE=false
  for cfg in "${CONFIG_FILES[@]}"; do
    if [[ -f "$cfg" && "$cfg" -nt ".next" ]]; then
      STALE=true
      STALE_REASON="$cfg was updated after .next was built"
      break
    fi
  done

  # Also check if packfile cache has missing files
  if [[ -d ".next/cache/webpack" ]]; then
    CORRUPTED=$(find .next/cache/webpack -name "*.pack.gz" -size 0 2>/dev/null || true)
    if [[ -n "$CORRUPTED" ]]; then
      STALE=true
      STALE_REASON="corrupted zero-byte webpack pack files detected"
    fi
  fi

  if [[ "$STALE" == true ]]; then
    echo "  ${YELLOW}⚠ Stale / Corrupted Cache:${RESET} $STALE_REASON"
    echo "    ${CYAN}Automatically purging .next and node_modules/.cache...${RESET}"
    rm -rf .next node_modules/.cache tsconfig.tsbuildinfo
    AUTO_CLEANED=true
    echo "  ${GREEN}✓ Build Cache:${RESET}           Purged successfully to prevent chunk mismatch"
  else
    echo "  ${GREEN}✓ Build Cache:${RESET}           .next is fresh and consistent"
  fi
else
  echo "  ${GREEN}✓ Build Cache:${RESET}           Clean (no existing .next directory)"
fi

# 5. Cloud Sync Safety Check
PROJECT_PATH=$(pwd)
if [[ "$PROJECT_PATH" =~ (Mobile\ Documents|OneDrive|Dropbox|Google\ Drive) ]]; then
  echo "  ${YELLOW}⚠ Cloud Sync Warning:${RESET}   Project is located in a synced directory ($PROJECT_PATH)."
  echo "    Ensure .next is excluded via .nosync to prevent sync clients from locking webpack chunks mid-compile."
  WARNINGS=$((WARNINGS + 1))
else
  echo "  ${GREEN}✓ Storage Location:${RESET}      Not inside an active desktop cloud sync folder"
fi

echo ""
if [[ "$ERRORS" -eq 0 ]]; then
  echo "${GREEN}${BOLD}🎉 [INDRA Doctor] Frontend verification PASSED cleanly.${RESET}"
  exit 0
else
  echo "${RED}${BOLD}✘ [INDRA Doctor] Frontend verification FAILED with $ERRORS error(s).${RESET}"
  exit 1
fi
