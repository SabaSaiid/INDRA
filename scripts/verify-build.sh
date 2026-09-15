#!/usr/bin/env bash
# ==============================================================================
# INDRA Platform Build & Chunk Verification Entry Point
# Delegates to frontend/scripts/verify-build.sh
# ==============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT_DIR/frontend/scripts/verify-build.sh" "$@"
