#!/usr/bin/env bash
# ==============================================================================
# INDRA Frontend Build & Chunk Graph Verification Script
# Runs Next.js lint and clean production build to verify client-only chunk graphs
# and detect broken SSR imports before code reaches the development server.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

echo -e "${BOLD}${CYAN}▶ INDRA Frontend Verification: Chunk Graph & Architecture Linter${RESET}"
echo -e "  Frontend Directory: ${FRONTEND_DIR}"

cd "$FRONTEND_DIR"

# 1. Check if git diff touches client-only or config (if git is present)
SHOULD_BUILD=true
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  DIFF_FILES=$(git diff --name-only HEAD 2>/dev/null || true)
  UNTRACKED_FILES=$(git status --porcelain 2>/dev/null || true)
  ALL_CHANGES="${DIFF_FILES}\n${UNTRACKED_FILES}"
  
  if echo -e "$ALL_CHANGES" | grep -qE "client-only|next\.config|\.eslintrc|package\.json"; then
    echo -e "  ${YELLOW}Detected changes in client-only components, configs, or dependencies.${RESET}"
    SHOULD_BUILD=true
  fi
fi

# 2. Run ESLint to enforce no-restricted-imports
echo -e "${CYAN}→ Running ESLint architecture checks...${RESET}"
if npm run lint; then
  echo -e "${GREEN}✓ ESLint rules passed (no restricted imports outside src/components/client-only/)${RESET}"
else
  echo -e "${RED}✘ ESLint checks failed! Browser-only libraries imported outside src/components/client-only/.${RESET}"
  exit 1
fi

# 3. Clean prior build caches
echo -e "${CYAN}→ Purging build cache (.next & node_modules/.cache)...${RESET}"
npm run clean

# 4. Run Next.js production build
echo -e "${CYAN}→ Running next build to verify chunk manifest and CSS integrity...${RESET}"
if npm run build; then
  echo -e "\n${GREEN}${BOLD}✓ Frontend build verified successfully! Chunk graph is intact.${RESET}\n"
  exit 0
else
  echo -e "\n${RED}${BOLD}✘ Frontend build failed! Broken chunk graph or SSR module error detected.${RESET}\n"
  exit 1
fi
