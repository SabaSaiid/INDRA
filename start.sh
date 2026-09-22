#!/usr/bin/env bash
# ==============================================================================
# INDRA Platform Control Suite
# Intelligent National Disaster & Weather Platform
# Smart India Hackathon 2026 - Problem Statement: SIH26069 | Team: Sixth Sense
# "We are building an intelligence platform, not a weather app."
# ==============================================================================

set -o pipefail

# --- Color Scheme & Formatting (ANSI-C Quoted) ---
if [[ -t 1 ]]; then
    BOLD=$'\033[1m'
    DIM=$'\033[2m'
    GREEN=$'\033[0;32m'
    CYAN=$'\033[0;36m'
    BLUE=$'\033[0;34m'
    YELLOW=$'\033[0;33m'
    RED=$'\033[0;31m'
    MAGENTA=$'\033[0;35m'
    RESET=$'\033[0m'
else
    BOLD=""
    DIM=""
    GREEN=""
    CYAN=""
    BLUE=""
    YELLOW=""
    RED=""
    MAGENTA=""
    RESET=""
fi

# --- Project Paths ---
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
DATA_DIR="$ROOT_DIR/data"
SCRIPTS_DIR="$ROOT_DIR/scripts"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$ROOT_DIR/logs"
PID_FILE="$RUN_DIR/indra.pid"
FRONTEND_PID_FILE="$RUN_DIR/indra_frontend.pid"
LOG_FILE="$LOG_DIR/indra.log"
FRONTEND_LOG_FILE="$LOG_DIR/indra_frontend.log"
ENV_FILE="$ROOT_DIR/.env"
ENV_EXAMPLE="$ROOT_DIR/.env.example"
DOCKER_COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

mkdir -p "$RUN_DIR" "$LOG_DIR"

# --- Environment Configuration ---
if [[ ! -f "$ENV_FILE" && -f "$ENV_EXAMPLE" ]]; then
    echo "${YELLOW}ℹ .env file not found. Initializing from .env.example...${RESET}"
    cp "$ENV_EXAMPLE" "$ENV_FILE"
fi

# Load port and host defaults from .env if present
if [[ -f "$ENV_FILE" ]]; then
    ENV_PORT=$(grep -E '^(API_PORT|PORT)=' "$ENV_FILE" 2>/dev/null | cut -d '=' -f2 | tr -d ' "\r\n' | tail -n 1)
    ENV_FRONTEND_PORT=$(grep -E '^(FRONTEND_PORT)=' "$ENV_FILE" 2>/dev/null | cut -d '=' -f2 | tr -d ' "\r\n' | tail -n 1)
    ENV_HOST=$(grep -E '^(API_HOST|HOST)=' "$ENV_FILE" 2>/dev/null | cut -d '=' -f2 | tr -d ' "\r\n' | tail -n 1)
fi

DEFAULT_PORT="${ENV_PORT:-8000}"
DEFAULT_FRONTEND_PORT="${ENV_FRONTEND_PORT:-3000}"
DEFAULT_HOST="${ENV_HOST:-0.0.0.0}"
DEFAULT_WORKERS=1
DEFAULT_RELOAD=true
DEFAULT_BROWSER=true

# State variables
COMMAND=""
PORT="$DEFAULT_PORT"
FRONTEND_PORT="$DEFAULT_FRONTEND_PORT"
HOST="$DEFAULT_HOST"
WORKERS="$DEFAULT_WORKERS"
RELOAD="$DEFAULT_RELOAD"
NO_BROWSER=false
FORCE=false
WITH_INFRA=false
LOG_LINES=50
INFRA_ACTION=""

# --- Banner ---
print_banner() {
    cat << EOF
${CYAN}${BOLD}
================================================================================
   ___ _   _ ____  ____      _     
  |_ _| \ | |  _ \|  _ \    / \    
   | ||  \| | | | | |_) |  / _ \   
   | || |\  | |_| |  _ <  / ___ \  
  |___|_| \_|____/|_| \_\/_/   \_\ 
${RESET}${BLUE}${BOLD}  Intelligent National Disaster & Weather Platform${RESET}
${DIM}  Smart India Hackathon 2026 | Problem Statement: SIH26069 | Team Sixth Sense
  "We are building an intelligence platform, not a weather app."${RESET}
${CYAN}================================================================================${RESET}
EOF
}

# --- Help Display ---
show_help() {
    print_banner
    cat << EOF
${BOLD}USAGE:${RESET}
  ./start.sh [COMMAND] [OPTIONS]

${BOLD}COMMANDS:${RESET}
  ${GREEN}start${RESET}                  Launch full stack (Next.js Frontend & FastAPI Backend) (default)
  ${GREEN}frontend${RESET}               Launch Next.js frontend dashboard only (port 3000)
  ${GREEN}backend${RESET}                Launch FastAPI backend API server only (port 8000)
  ${GREEN}bg${RESET} | ${GREEN}daemon${RESET}             Launch full platform as background daemons
  ${GREEN}stop${RESET}                   Gracefully stop running backend and frontend processes
  ${GREEN}restart${RESET}                Restart running backend and frontend processes
  ${GREEN}status${RESET}                 Inspect backend, frontend, and Docker infrastructure status
  ${GREEN}setup${RESET}                  Create virtualenv and install backend + frontend dependencies
  ${GREEN}infra${RESET} [up|down|ps|logs] Manage PostGIS, Redis & Redpanda Docker services
  ${GREEN}doctor${RESET}                 Run comprehensive environment and dependency diagnostics
  ${GREEN}demo${RESET}                   Execute 10-Scene Patna flood verification simulation
  ${GREEN}test${RESET}                   Run automated health check and API verification probes
  ${GREEN}logs${RESET} [-n <lines>]       Stream live backend server logs (tail -f)
  ${GREEN}clean${RESET}                  Purge temporary cache files, .pyc, logs, and PID files
  ${GREEN}help${RESET}                   Display this help message

${BOLD}OPTIONS:${RESET}
  ${CYAN}-p, --port <port>${RESET}      Set server port (default: ${DEFAULT_PORT})
  ${CYAN}-H, --host <host>${RESET}      Set server host (default: ${DEFAULT_HOST})
  ${CYAN}-w, --workers <num>${RESET}    Number of worker processes (default: ${DEFAULT_WORKERS})
  ${CYAN}--reload / --no-reload${RESET} Toggle uvicorn hot-reload (default: enabled)
  ${CYAN}-n, --no-browser${RESET}       Do not auto-open API Swagger documentation in browser
  ${CYAN}-f, --force${RESET}            Force-kill any conflicting process holding target port
  ${CYAN}--with-infra${RESET}           Automatically launch Docker infrastructure if stopped
  ${CYAN}-h, --help${RESET}             Show this help menu

${BOLD}EXAMPLES:${RESET}
  ${DIM}# Launch backend with auto-reload and default port${RESET}
  ./start.sh

  ${DIM}# Setup virtualenv and install dependencies${RESET}
  ./start.sh setup

  ${DIM}# Run system diagnostics and Docker container checks${RESET}
  ./start.sh doctor

  ${DIM}# Run the 10-Scene SIH Patna Verification Narrative${RESET}
  ./start.sh demo

  ${DIM}# Start in background, verify status, and stream logs${RESET}
  ./start.sh bg
  ./start.sh status
  ./start.sh logs

  ${DIM}# Start PostGIS, Redis, and Redpanda Docker containers${RESET}
  ./start.sh infra up
EOF
}

# --- Python & Virtualenv Discovery ---
detect_python() {
    PYTHON_CMD=""
    VENV_ACTIVE=false

    # 1. Check backend/.venv
    if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
        PYTHON_CMD="$BACKEND_DIR/.venv/bin/python"
        VENV_ACTIVE=true
        VENV_PATH="$BACKEND_DIR/.venv"
    # 2. Check root .venv
    elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
        PYTHON_CMD="$ROOT_DIR/.venv/bin/python"
        VENV_ACTIVE=true
        VENV_PATH="$ROOT_DIR/.venv"
    # 3. Check currently activated virtualenv
    elif [[ -n "$VIRTUAL_ENV" && -x "$VIRTUAL_ENV/bin/python" ]]; then
        PYTHON_CMD="$VIRTUAL_ENV/bin/python"
        VENV_ACTIVE=true
        VENV_PATH="$VIRTUAL_ENV"
    # 4. Fallback to system python3
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD="$(command -v python3)"
        VENV_PATH="System ($PYTHON_CMD)"
    else
        echo "${RED}✘ Error: Python 3 was not found on your system.${RESET}"
        exit 1
    fi
}

# --- Pre-flight Uvicorn Check ---
ensure_uvicorn() {
    detect_python
    if ! "$PYTHON_CMD" -c "import uvicorn, fastapi" >/dev/null 2>&1; then
        echo "${YELLOW}⚠ Missing backend dependencies (fastapi/uvicorn) in: $PYTHON_CMD${RESET}"
        echo "${CYAN}Running environment setup into backend/.venv...${RESET}"
        cmd_setup
        detect_python
    fi
}

# --- Docker Compose Helper ---
get_docker_compose_cmd() {
    if docker compose version >/dev/null 2>&1; then
        echo "docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        echo "docker-compose"
    else
        echo ""
    fi
}

# --- Port Management ---
get_pid_on_port() {
    local target_port="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti :"$target_port" -sTCP:LISTEN 2>/dev/null | tr '\n' ' '
    fi
}

kill_process_gracefully() {
    local pid="$1"
    local name="${2:-Process}"

    if [[ -z "$pid" ]]; then
        return 0
    fi

    if kill -0 "$pid" 2>/dev/null; then
        echo "${YELLOW}Sending SIGTERM to $name (PID: $pid)...${RESET}"
        kill -TERM "$pid" 2>/dev/null

        local count=0
        while kill -0 "$pid" 2>/dev/null && [[ $count -lt 8 ]]; do
            sleep 0.5
            count=$((count + 1))
        done

        if kill -0 "$pid" 2>/dev/null; then
            echo "${RED}Escalating to SIGKILL for $name (PID: $pid)...${RESET}"
            kill -KILL "$pid" 2>/dev/null
            sleep 0.5
        fi
        echo "${GREEN}✓ $name (PID: $pid) stopped.${RESET}"
    fi
}

# --- Frontend Service Management ---
ensure_frontend_deps() {
    if ! command -v npm >/dev/null 2>&1; then
        echo "${YELLOW}⚠ npm is not installed or not in PATH.${RESET}"
        return 1
    fi
    if [[ -d "$FRONTEND_DIR" && ! -d "$FRONTEND_DIR/node_modules" ]]; then
        echo "${CYAN}Installing frontend dependencies in frontend/...${RESET}"
        (cd "$FRONTEND_DIR" && npm install)
    fi
    return 0
}

start_frontend_bg() {
    if [[ ! -d "$FRONTEND_DIR" ]]; then
        return 0
    fi

    local f_pids
    f_pids=$(get_pid_on_port "$FRONTEND_PORT")
    if [[ -n "$f_pids" ]]; then
        echo "  Frontend Dashboard:    ${GREEN}● ACTIVE${RESET} (Port $FRONTEND_PORT already running PID: $f_pids)"
        return 0
    fi

    ensure_frontend_deps || return 1

    echo "${BOLD}▶ Starting INDRA Next.js Frontend Dashboard (port $FRONTEND_PORT)...${RESET}"
    cd "$FRONTEND_DIR" || return 1
    nohup npm run dev -- -p "$FRONTEND_PORT" > "$FRONTEND_LOG_FILE" 2>&1 &
    local fpid=$!
    echo "$fpid" > "$FRONTEND_PID_FILE"
    cd "$ROOT_DIR" || return 1

    local count=0
    while ! curl -s -m 1 "http://127.0.0.1:$FRONTEND_PORT" >/dev/null 2>&1 && [[ $count -lt 25 ]]; do
        sleep 0.4
        count=$((count + 1))
    done

    if kill -0 "$fpid" 2>/dev/null; then
        echo "  Frontend Service:      ${GREEN}✓ STARTED${RESET} (PID: $fpid, http://localhost:$FRONTEND_PORT)"
    fi
}

stop_frontend() {
    local stopped=false
    if [[ -f "$FRONTEND_PID_FILE" ]]; then
        local fpid
        fpid=$(cat "$FRONTEND_PID_FILE" 2>/dev/null)
        if [[ -n "$fpid" ]]; then
            kill_process_gracefully "$fpid" "INDRA Frontend"
            stopped=true
        fi
        rm -f "$FRONTEND_PID_FILE"
    fi

    local f_pids
    f_pids=$(get_pid_on_port "$FRONTEND_PORT")
    if [[ -n "$f_pids" ]]; then
        for p in $f_pids; do
            kill_process_gracefully "$p" "Frontend Port $FRONTEND_PORT occupant"
            stopped=true
        done
    fi
}

# --- Browser Launcher ---
open_browser() {
    local url="${1:-http://localhost:$FRONTEND_PORT}"
    local target_port="${2:-$FRONTEND_PORT}"
    if [[ "$NO_BROWSER" == true || "$DEFAULT_BROWSER" == false || "$NO_BROWSER" == "1" ]]; then
        return 0
    fi

    (
        local count=0
        while ! curl -s -m 1 "http://127.0.0.1:$target_port" >/dev/null 2>&1 && [[ $count -lt 30 ]]; do
            sleep 0.4
            count=$((count + 1))
        done

        if command -v open >/dev/null 2>&1; then
            open "$url" >/dev/null 2>&1 || true
        elif command -v xdg-open >/dev/null 2>&1; then
            xdg-open "$url" >/dev/null 2>&1 || true
        elif command -v wslview >/dev/null 2>&1; then
            wslview "$url" >/dev/null 2>&1 || true
        fi
    ) &
}

# --- Start Docker Infra and wait for it ---
# `up -d` returns as soon as the containers exist, which on a fresh volume is
# seconds before Postgres has created indra_db (BUG-028). Compose v2's --wait
# blocks until every service with a healthcheck reports healthy, so whatever
# runs next (alembic, the API) finds a database that is really there.
# docker-compose v1 has no --wait; it keeps the old behaviour.
compose_up_and_wait() {
    local DOCKER_CMD="$1"
    if [[ "$DOCKER_CMD" == "docker compose" ]]; then
        $DOCKER_CMD -f "$DOCKER_COMPOSE_FILE" up -d --wait --wait-timeout 120
    else
        $DOCKER_CMD -f "$DOCKER_COMPOSE_FILE" up -d
    fi
}

# --- Check Docker Infra ---
check_docker_infra() {
    local DOCKER_CMD
    DOCKER_CMD=$(get_docker_compose_cmd)
    if [[ -z "$DOCKER_CMD" ]]; then
        return 1
    fi

    local running_containers
    running_containers=$($DOCKER_CMD -f "$DOCKER_COMPOSE_FILE" ps -q 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$running_containers" -ge 3 ]]; then
        return 0
    else
        return 2
    fi
}

ensure_docker_infra() {
    local DOCKER_CMD
    DOCKER_CMD=$(get_docker_compose_cmd)
    if [[ -z "$DOCKER_CMD" ]]; then
        echo "${YELLOW}⚠ Docker is not available. Skipping automatic infrastructure launch.${RESET}"
        return 0
    fi

    check_docker_infra
    local status=$?
    if [[ $status -eq 0 ]]; then
        echo "${GREEN}✓ Docker Infrastructure (PostGIS, Redis, Redpanda) is online.${RESET}"
    else
        if [[ "$WITH_INFRA" == true ]]; then
            echo "${CYAN}Spinning up Docker Infrastructure (PostGIS, Redis, Redpanda)...${RESET}"
            compose_up_and_wait "$DOCKER_CMD"
        else
            echo "${DIM}ℹ Docker containers not detected. Run './start.sh infra up' or pass '--with-infra' to start them.${RESET}"
        fi
    fi
}

# --- Subcommand: setup ---
cmd_setup() {
    print_banner
    echo "${BOLD}⚙ Setting up INDRA Backend & Frontend Environment...${RESET}"
    
    if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
        echo "${CYAN}Creating virtual environment at backend/.venv...${RESET}"
        python3 -m venv "$BACKEND_DIR/.venv"
    fi

    echo "${CYAN}Installing backend requirements from backend/requirements.txt...${RESET}"
    "$BACKEND_DIR/.venv/bin/pip" install -r "$BACKEND_DIR/requirements.txt"
    
    if command -v npm >/dev/null 2>&1 && [[ -d "$FRONTEND_DIR" ]]; then
        echo "${CYAN}Installing frontend dependencies in frontend/...${RESET}"
        (cd "$FRONTEND_DIR" && npm install)
    fi

    echo "${GREEN}✓ Environment setup complete!${RESET}"
    echo ""
}

# --- Subcommand: start (Full-Stack) ---
cmd_start() {
    ensure_uvicorn
    print_banner

    echo "${BOLD}▶ Starting INDRA Full-Stack Platform...${RESET}"
    echo "  Dashboard UI:   ${CYAN}http://localhost:$FRONTEND_PORT${RESET}"
    echo "  Backend API:    ${CYAN}http://$HOST:$PORT${RESET}"
    echo "  Python:         ${CYAN}$("$PYTHON_CMD" --version 2>&1)${RESET}"
    echo "  Environment:    ${CYAN}$VENV_PATH${RESET}"
    echo "  Auto-Reload:    ${CYAN}$RELOAD${RESET}"
    echo ""

    # Check port conflicts for backend
    local port_pids
    port_pids=$(get_pid_on_port "$PORT")
    if [[ -n "$port_pids" ]]; then
        if [[ "$FORCE" == true ]]; then
            echo "${YELLOW}⚠ Port $PORT is occupied by PID(s): $port_pids. Force terminating...${RESET}"
            for p in $port_pids; do
                kill_process_gracefully "$p" "Backend Port occupant"
            done
        else
            echo "${RED}✘ Port $PORT is currently occupied by process PID(s): $port_pids${RESET}"
            echo "  Use ${CYAN}./start.sh stop${RESET} or ${CYAN}./start.sh -f${RESET} to terminate conflicting processes."
            exit 1
        fi
    fi

    ensure_docker_infra

    # Start Next.js Frontend
    start_frontend_bg

    local APP_URL="http://localhost:$FRONTEND_PORT"
    local API_URL="http://localhost:$PORT"
    local DOCS_URL="http://localhost:$PORT/docs"
    echo ""
    echo "${GREEN}✓ Weather Intelligence Dashboard:${RESET} ${BOLD}$APP_URL${RESET}"
    echo "${GREEN}✓ FastAPI Backend API:${RESET}           ${BOLD}$API_URL${RESET}"
    echo "${GREEN}✓ Swagger Interactive API Docs:${RESET} ${BOLD}$DOCS_URL${RESET}"
    echo "${GREEN}✓ Health Endpoint:${RESET}              ${BOLD}http://localhost:$PORT/healthz${RESET}"
    echo "${GREEN}✓ Live WebSocket Stream:${RESET}        ${BOLD}ws://localhost:$PORT/ws/events${RESET}"
    echo ""
    echo "${DIM}Press Ctrl+C at any time to halt all INDRA services.${RESET}"
    echo "--------------------------------------------------------------------------------"

    open_browser "$APP_URL" "$FRONTEND_PORT"

    local RELOAD_FLAG=""
    if [[ "$RELOAD" == true ]]; then
        RELOAD_FLAG="--reload"
    fi

    cd "$BACKEND_DIR" || exit 1
    cleanup() {
        echo -e "\n${YELLOW}Halted by user. Shutting down INDRA...${RESET}"
        stop_frontend
        exit 0
    }
    trap cleanup INT TERM
    "$PYTHON_CMD" -m uvicorn app.main:app --host "$HOST" --port "$PORT" --workers "$WORKERS" $RELOAD_FLAG
}

# --- Subcommand: frontend ---
cmd_frontend() {
    print_banner
    echo "${BOLD}▶ Starting INDRA Next.js Frontend in Foreground...${RESET}"
    ensure_frontend_deps || exit 1
    cd "$FRONTEND_DIR" || exit 1
    open_browser "http://localhost:$FRONTEND_PORT" "$FRONTEND_PORT"
    npm run dev -- -p "$FRONTEND_PORT"
}

# --- Subcommand: backend ---
cmd_backend() {
    ensure_uvicorn
    print_banner

    echo "${BOLD}▶ Starting INDRA FastAPI Backend Server Only...${RESET}"
    echo "  Host:           ${CYAN}$HOST${RESET}"
    echo "  Port:           ${CYAN}$PORT${RESET}"
    echo "  Python:         ${CYAN}$("$PYTHON_CMD" --version 2>&1)${RESET}"
    echo "  Environment:    ${CYAN}$VENV_PATH${RESET}"
    echo "  Auto-Reload:    ${CYAN}$RELOAD${RESET}"
    echo ""

    local port_pids
    port_pids=$(get_pid_on_port "$PORT")
    if [[ -n "$port_pids" ]]; then
        if [[ "$FORCE" == true ]]; then
            echo "${YELLOW}⚠ Port $PORT is occupied by PID(s): $port_pids. Force terminating...${RESET}"
            for p in $port_pids; do
                kill_process_gracefully "$p" "Backend Port occupant"
            done
        else
            echo "${RED}✘ Port $PORT is currently occupied by process PID(s): $port_pids${RESET}"
            echo "  Use ${CYAN}./start.sh stop${RESET} or ${CYAN}./start.sh -f${RESET} to terminate conflicting processes."
            exit 1
        fi
    fi

    ensure_docker_infra

    local API_URL="http://localhost:$PORT"
    local DOCS_URL="http://localhost:$PORT/docs"
    echo "${GREEN}✓ FastAPI Backend API:${RESET}           ${BOLD}$API_URL${RESET}"
    echo "${GREEN}✓ Swagger Interactive API Docs:${RESET} ${BOLD}$DOCS_URL${RESET}"
    echo "${GREEN}✓ Health Endpoint:${RESET}              ${BOLD}http://localhost:$PORT/healthz${RESET}"
    echo "${GREEN}✓ Live WebSocket Stream:${RESET}        ${BOLD}ws://localhost:$PORT/ws/events${RESET}"
    echo ""
    echo "${DIM}Press Ctrl+C at any time to halt the backend.${RESET}"
    echo "--------------------------------------------------------------------------------"

    open_browser "$API_URL" "$PORT"

    local RELOAD_FLAG=""
    if [[ "$RELOAD" == true ]]; then
        RELOAD_FLAG="--reload"
    fi

    cd "$BACKEND_DIR" || exit 1
    trap 'echo -e "\n${YELLOW}Halted by user. Shutting down backend...${RESET}"; exit 0' INT TERM
    "$PYTHON_CMD" -m uvicorn app.main:app --host "$HOST" --port "$PORT" --workers "$WORKERS" $RELOAD_FLAG
}

# --- Subcommand: bg (daemon) ---
cmd_bg() {
    ensure_uvicorn
    print_banner

    echo "${BOLD}▶ Starting INDRA Full Stack in Background (Daemon Mode)...${RESET}"

    # Check if backend already running
    if [[ -f "$PID_FILE" ]]; then
        local existing_pid
        existing_pid=$(cat "$PID_FILE" 2>/dev/null)
        if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
            echo "${YELLOW}⚠ INDRA Backend is already running in background with PID: $existing_pid${RESET}"
        else
            rm -f "$PID_FILE"
        fi
    fi

    # Check port conflicts for backend
    local port_pids
    port_pids=$(get_pid_on_port "$PORT")
    if [[ -n "$port_pids" ]]; then
        if [[ "$FORCE" == true ]]; then
            echo "${YELLOW}⚠ Port $PORT occupied by PID(s): $port_pids. Force terminating...${RESET}"
            for p in $port_pids; do
                kill_process_gracefully "$p" "Backend Port occupant"
            done
        else
            echo "${RED}✘ Port $PORT is currently occupied by PID(s): $port_pids${RESET}"
            echo "  Use ${CYAN}./start.sh stop${RESET} or ${CYAN}./start.sh bg -f${RESET} to free the port."
            exit 1
        fi
    fi

    ensure_docker_infra

    # Start Frontend
    start_frontend_bg

    local RELOAD_FLAG=""
    if [[ "$RELOAD" == true ]]; then
        RELOAD_FLAG="--reload"
    fi

    cd "$BACKEND_DIR" || exit 1
    nohup "$PYTHON_CMD" -m uvicorn app.main:app --host "$HOST" --port "$PORT" --workers "$WORKERS" $RELOAD_FLAG > "$LOG_FILE" 2>&1 &
    local NEW_PID=$!
    echo "$NEW_PID" > "$PID_FILE"
    cd "$ROOT_DIR" || exit 1

    sleep 1.2
    if kill -0 "$NEW_PID" 2>/dev/null; then
        echo "${GREEN}✓ INDRA successfully launched in background!${RESET}"
        echo "  Backend PID:    ${CYAN}$NEW_PID${RESET}"
        echo "  Dashboard UI:   ${CYAN}http://localhost:$FRONTEND_PORT${RESET}"
        echo "  Backend API:    ${CYAN}http://localhost:$PORT${RESET}"
        echo "  API Docs:       ${CYAN}http://localhost:$PORT/docs${RESET}"
        echo "  Backend Logs:   ${CYAN}$LOG_FILE${RESET}"
        echo "  Frontend Logs:  ${CYAN}$FRONTEND_LOG_FILE${RESET}"
        echo ""
        echo "Commands to control background processes:"
        echo "  Status:         ${CYAN}./start.sh status${RESET}"
        echo "  Stream Logs:    ${CYAN}./start.sh logs${RESET}"
        echo "  Stop Platform:  ${CYAN}./start.sh stop${RESET}"
        open_browser "http://localhost:$FRONTEND_PORT" "$FRONTEND_PORT"
    else
        echo "${RED}✘ Failed to start INDRA backend in background. Check log output:${RESET}"
        tail -n 20 "$LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
}

# --- Subcommand: stop ---
cmd_stop() {
    echo "${BOLD}▶ Stopping INDRA Platform...${RESET}"
    local stopped=false

    # 1. Stop backend recorded PID
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE" 2>/dev/null)
        if [[ -n "$pid" ]]; then
            kill_process_gracefully "$pid" "INDRA Backend"
            stopped=true
        fi
        rm -f "$PID_FILE"
    fi

    # 2. Check and terminate any processes on backend port
    local port_pids
    port_pids=$(get_pid_on_port "$PORT")
    if [[ -n "$port_pids" ]]; then
        echo "${YELLOW}Cleaning up remaining process(es) on port $PORT: $port_pids${RESET}"
        for p in $port_pids; do
            kill_process_gracefully "$p" "Backend Port $PORT occupant"
            stopped=true
        done
    fi

    # 3. Stop frontend
    stop_frontend

    if [[ "$stopped" == true ]]; then
        echo "${GREEN}✓ INDRA stopped successfully.${RESET}"
    else
        echo "${DIM}ℹ All INDRA processes stopped.${RESET}"
    fi
}

# --- Subcommand: restart ---
cmd_restart() {
    echo "${BOLD}▶ Restarting INDRA Platform...${RESET}"
    cmd_stop
    echo ""
    cmd_bg
}

# --- Subcommand: status ---
cmd_status() {
    print_banner
    echo "${BOLD}▶ Checking INDRA Platform Operational Status...${RESET}"
    echo ""

    # Frontend Status
    local frontend_running=false
    local frontend_pid=""
    if [[ -f "$FRONTEND_PID_FILE" ]]; then
        frontend_pid=$(cat "$FRONTEND_PID_FILE" 2>/dev/null)
        if [[ -n "$frontend_pid" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
            frontend_running=true
        fi
    fi
    local fport_pids
    fport_pids=$(get_pid_on_port "$FRONTEND_PORT")

    if [[ "$frontend_running" == true ]]; then
        echo "  Frontend Dashboard:    ${GREEN}● RUNNING${RESET} (PID: $frontend_pid, http://localhost:$FRONTEND_PORT)"
    elif [[ -n "$fport_pids" ]]; then
        echo "  Frontend Dashboard:    ${GREEN}● ACTIVE${RESET} (Port $FRONTEND_PORT occupied by PID: $fport_pids)"
    else
        echo "  Frontend Dashboard:    ${DIM}○ STOPPED${RESET}"
    fi

    # Backend Status
    local backend_running=false
    local backend_pid=""
    if [[ -f "$PID_FILE" ]]; then
        backend_pid=$(cat "$PID_FILE" 2>/dev/null)
        if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
            backend_running=true
        fi
    fi

    local port_pids
    port_pids=$(get_pid_on_port "$PORT")

    if [[ "$backend_running" == true ]]; then
        echo "  Backend Service:       ${GREEN}● RUNNING${RESET} (PID: $backend_pid)"
    elif [[ -n "$port_pids" ]]; then
        echo "  Backend Service:       ${YELLOW}● ACTIVE${RESET} (Port $PORT occupied by PID: $port_pids)"
    else
        echo "  Backend Service:       ${DIM}○ STOPPED${RESET}"
    fi

    # Port 8000
    if [[ -n "$port_pids" ]]; then
        echo "  Backend Port $PORT:       ${GREEN}● OPEN${RESET} (Binding: $HOST:$PORT)"
    else
        echo "  Backend Port $PORT:       ${DIM}○ FREE${RESET}"
    fi

    # API Probe
    if command -v curl >/dev/null 2>&1; then
        local health_res
        health_res=$(curl -s -m 2 "http://localhost:$PORT/healthz" 2>/dev/null)
        if [[ -n "$health_res" ]]; then
            echo "  Health Check (/healthz): ${GREEN}✓ RESPONDING${RESET} $health_res"
        else
            echo "  Health Check (/healthz): ${DIM}○ UNREACHABLE${RESET}"
        fi
    fi

    echo ""
    echo "${BOLD}Docker Infrastructure:${RESET}"
    local DOCKER_CMD
    DOCKER_CMD=$(get_docker_compose_cmd)
    if [[ -n "$DOCKER_CMD" ]]; then
        $DOCKER_CMD -f "$DOCKER_COMPOSE_FILE" ps 2>/dev/null || echo "  ${YELLOW}Docker containers not initialized.${RESET}"
    else
        echo "  ${YELLOW}Docker Compose CLI not found.${RESET}"
    fi
    echo ""
}

# --- Subcommand: infra ---
cmd_infra() {
    local action="${1:-status}"
    local DOCKER_CMD
    DOCKER_CMD=$(get_docker_compose_cmd)

    if [[ -z "$DOCKER_CMD" ]]; then
        echo "${RED}✘ Docker or Docker Compose is not installed/running.${RESET}"
        exit 1
    fi

    case "$action" in
        up|start)
            echo "${BOLD}▶ Starting INDRA Docker Infrastructure (PostGIS, Redis, Redpanda)...${RESET}"
            if ! compose_up_and_wait "$DOCKER_CMD"; then
                echo "${RED}✘ Infrastructure did not become healthy. Check: $DOCKER_CMD ps${RESET}"
                exit 1
            fi
            echo "${GREEN}✓ Infrastructure containers started and healthy.${RESET}"
            ;;
        down|stop)
            echo "${BOLD}▶ Stopping INDRA Docker Infrastructure...${RESET}"
            $DOCKER_CMD -f "$DOCKER_COMPOSE_FILE" down
            echo "${GREEN}✓ Infrastructure containers stopped.${RESET}"
            ;;
        ps|status)
            echo "${BOLD}▶ INDRA Docker Container Status:${RESET}"
            $DOCKER_CMD -f "$DOCKER_COMPOSE_FILE" ps
            ;;
        logs)
            echo "${BOLD}▶ Streaming Docker Infrastructure Logs:${RESET}"
            $DOCKER_CMD -f "$DOCKER_COMPOSE_FILE" logs -f
            ;;
        *)
            echo "${RED}Unknown infra action: $action${RESET}"
            echo "Usage: ./start.sh infra [up|down|ps|logs]"
            exit 1
            ;;
    esac
}

# --- Subcommand: doctor ---
cmd_doctor() {
    print_banner
    echo "${BOLD}🩺 Running INDRA System Diagnostics & Audit...${RESET}"
    echo ""

    # 1. Python Check
    detect_python
    local py_ver
    py_ver=$("$PYTHON_CMD" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>/dev/null)
    local py_major
    py_major=$("$PYTHON_CMD" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
    local py_minor
    py_minor=$("$PYTHON_CMD" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)

    if [[ "$py_major" -ge 3 && "$py_minor" -ge 10 ]]; then
        echo "  ${GREEN}✓ Python Interpreter:${RESET}  Python $py_ver ($PYTHON_CMD)"
    else
        echo "  ${RED}✘ Python Interpreter:${RESET}  Python $py_ver (Recommended: 3.11+)"
    fi

    # 2. Virtual Environment Check
    if [[ "$VENV_ACTIVE" == true ]]; then
        echo "  ${GREEN}✓ Virtual Environment:${RESET} $VENV_PATH (Active)"
    else
        echo "  ${YELLOW}ℹ Virtual Environment:${RESET} Running without virtualenv. Recommended: './start.sh setup'"
    fi

    # 3. Core Dependencies Check
    echo -n "  Testing Core Modules: "
    local missing_deps=()
    for dep in fastapi uvicorn pydantic sqlalchemy; do
        if ! "$PYTHON_CMD" -c "import $dep" >/dev/null 2>&1; then
            missing_deps+=("$dep")
        fi
    done

    if [[ ${#missing_deps[@]} -eq 0 ]]; then
        echo "${GREEN}✓ Core API dependencies verified (fastapi, uvicorn, pydantic, sqlalchemy).${RESET}"
    else
        echo "${RED}✘ Missing modules:${RESET} ${missing_deps[*]}"
        echo "    Run: ${CYAN}./start.sh setup${RESET}"
    fi

    # 4. Environment Configuration (.env)
    if [[ -f "$ENV_FILE" ]]; then
        echo "  ${GREEN}✓ Environment File:${RESET}    .env exists and configured"
    else
        echo "  ${YELLOW}ℹ Environment File:${RESET}    .env missing (will auto-copy from .env.example)"
    fi

    # 5. Labelled Dataset Verification
    #
    # This used to report patna_flood_scenario.json as "127 reports verified".
    # Nothing in that file was verified or even ingested -- it was a hand-written
    # narrative served straight to the dashboard, and it was deleted on 20 Sep.
    # The labelled set below is real data this project measures against, and the
    # banner says plainly that it is synthetic.
    local labelled_dataset="$DATA_DIR/labelled/reports_v1.csv"
    if [[ -f "$labelled_dataset" ]]; then
        local drows
        drows=$(( $(wc -l < "$labelled_dataset" | tr -d ' ') - 1 ))
        echo "  ${GREEN}✓ Labelled Dataset:${RESET}    reports_v1.csv ($drows synthetic rows, train/test split)"
    else
        echo "  ${YELLOW}ℹ Labelled Dataset:${RESET}    Missing at $labelled_dataset"
    fi

    # 6. Docker & Infrastructure Check
    local DOCKER_CMD
    DOCKER_CMD=$(get_docker_compose_cmd)
    if [[ -n "$DOCKER_CMD" ]]; then
        echo "  ${GREEN}✓ Docker CLI:${RESET}          $DOCKER_CMD available"
        check_docker_infra
        local dstatus=$?
        if [[ $dstatus -eq 0 ]]; then
            echo "  ${GREEN}✓ Docker Containers:${RESET}   PostGIS (5433), Redis (6379), Redpanda (19092) are RUNNING"
        else
            echo "  ${YELLOW}ℹ Docker Containers:${RESET}   Containers currently stopped. Run './start.sh infra up'"
        fi
    else
        echo "  ${YELLOW}ℹ Docker CLI:${RESET}          Docker / Docker Compose not installed."
    fi

    # 7. Port Occupancy Check
    local port_pids
    port_pids=$(get_pid_on_port "$PORT")
    if [[ -n "$port_pids" ]]; then
        echo "  ${YELLOW}● Port $PORT:${RESET}             Occupied by PID(s): $port_pids"
    else
        echo "  ${GREEN}✓ Port $PORT:${RESET}             Available"
    fi

    # 8. Frontend Health & Hygiene Check
    if [[ -f "$FRONTEND_DIR/scripts/doctor.sh" ]]; then
        echo ""
        (cd "$FRONTEND_DIR" && bash "$FRONTEND_DIR/scripts/doctor.sh")
    fi

    echo ""
    echo "${BOLD}Diagnostics complete.${RESET}"
    echo ""
}

# --- Subcommand: demo ---
cmd_demo() {
    detect_python
    local demo_script="$SCRIPTS_DIR/run_patna_demo.py"
    if [[ ! -f "$demo_script" ]]; then
        echo "${RED}✘ Demo script not found at $demo_script${RESET}"
        exit 1
    fi

    "$PYTHON_CMD" "$demo_script"
}

# --- Subcommand: test ---
cmd_test() {
    print_banner
    echo "${BOLD}🧪 Running INDRA Automated Verification Checks...${RESET}"
    echo ""

    if ! command -v curl >/dev/null 2>&1; then
        echo "${RED}✘ curl is required to run automated HTTP tests.${RESET}"
        exit 1
    fi

    local BASE_URL="http://localhost:$PORT"
    local passed=0
    local failed=0

    # Test 1: GET /api/info (Platform Info)
    echo -n "  Testing GET /api/info (Platform Info) ... "
    local root_resp
    root_resp=$(curl -s -m 3 "$BASE_URL/api/info" 2>/dev/null)
    if echo "$root_resp" | grep -q '"platform": *"INDRA"'; then
        echo "${GREEN}✓ PASSED${RESET}"
        passed=$((passed + 1))
    else
        echo "${RED}✘ FAILED${RESET} (Backend may not be running on $BASE_URL)"
        failed=$((failed + 1))
    fi

    # Test 2: GET /healthz
    echo -n "  Testing GET /healthz (System Health) ... "
    local health_resp
    health_resp=$(curl -s -m 3 "$BASE_URL/healthz" 2>/dev/null)
    if echo "$health_resp" | grep -q '"status": *"healthy"'; then
        echo "${GREEN}✓ PASSED${RESET}"
        passed=$((passed + 1))
    else
        echo "${RED}✘ FAILED${RESET}"
        failed=$((failed + 1))
    fi

    # Test 3: GET /docs (Swagger Documentation)
    echo -n "  Testing GET /docs (Swagger UI) ... "
    local docs_code
    docs_code=$(curl -s -o /dev/null -w "%{http_code}" -m 3 "$BASE_URL/docs" 2>/dev/null)
    if [[ "$docs_code" == "200" ]]; then
        echo "${GREEN}✓ PASSED (HTTP 200)${RESET}"
        passed=$((passed + 1))
    else
        echo "${RED}✘ FAILED (HTTP $docs_code)${RESET}"
        failed=$((failed + 1))
    fi

    # Test 4: GET /api/dashboard/summary (National Dashboard KPIs)
    echo -n "  Testing GET /api/dashboard/summary (Dashboard KPIs) ... "
    local dash_code
    dash_code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 "$BASE_URL/api/dashboard/summary" 2>/dev/null)
    if [[ "$dash_code" == "200" ]]; then
        echo "${GREEN}✓ PASSED (HTTP 200)${RESET}"
        passed=$((passed + 1))
    else
        echo "${RED}✘ FAILED (HTTP $dash_code)${RESET}"
        failed=$((failed + 1))
    fi

    # Test 5: GET /api/events (Events List)
    echo -n "  Testing GET /api/events (Events List) ... "
    local events_code
    events_code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 "$BASE_URL/api/events" 2>/dev/null)
    if [[ "$events_code" == "200" ]]; then
        echo "${GREEN}✓ PASSED (HTTP 200)${RESET}"
        passed=$((passed + 1))
    else
        echo "${RED}✘ FAILED (HTTP $events_code)${RESET}"
        failed=$((failed + 1))
    fi

    # Test 6: GET /api/events/distribution (Donut Chart Data)
    echo -n "  Testing GET /api/events/distribution (Distribution) ... "
    local dist_code
    dist_code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 "$BASE_URL/api/events/distribution" 2>/dev/null)
    if [[ "$dist_code" == "200" ]]; then
        echo "${GREEN}✓ PASSED (HTTP 200)${RESET}"
        passed=$((passed + 1))
    else
        echo "${RED}✘ FAILED (HTTP $dist_code)${RESET}"
        failed=$((failed + 1))
    fi

    # Test 7: GET /api/reports/trend (Trend Chart Data)
    echo -n "  Testing GET /api/reports/trend?range=7d (Reports Trend) ... "
    local trend_code
    trend_code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 "$BASE_URL/api/reports/trend?range=7d" 2>/dev/null)
    if [[ "$trend_code" == "200" ]]; then
        echo "${GREEN}✓ PASSED (HTTP 200)${RESET}"
        passed=$((passed + 1))
    else
        echo "${RED}✘ FAILED (HTTP $trend_code)${RESET}"
        failed=$((failed + 1))
    fi

    # Test 8: GET /api/feed/recent (Live Feed)
    echo -n "  Testing GET /api/feed/recent?limit=10 (Live Feed) ... "
    local feed_code
    feed_code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 "$BASE_URL/api/feed/recent?limit=10" 2>/dev/null)
    if [[ "$feed_code" == "200" ]]; then
        echo "${GREEN}✓ PASSED (HTTP 200)${RESET}"
        passed=$((passed + 1))
    else
        echo "${RED}✘ FAILED (HTTP $feed_code)${RESET}"
        failed=$((failed + 1))
    fi

    # Test 9: POST /api/auth/token (JWT Auth)
    echo -n "  Testing POST /api/auth/token (JWT Auth) ... "
    local auth_resp
    auth_resp=$(curl -s -m 5 -X POST "$BASE_URL/api/auth/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "username=admin&password=admin123" 2>/dev/null)
    if echo "$auth_resp" | grep -q '"access_token"'; then
        echo "${GREEN}✓ PASSED${RESET}"
        passed=$((passed + 1))
    else
        echo "${RED}✘ FAILED${RESET}"
        failed=$((failed + 1))
    fi

    echo ""
    if [[ $failed -eq 0 ]]; then
        echo "${GREEN}${BOLD}🎉 ALL $passed VERIFICATION TESTS PASSED SUCCESSFULLY!${RESET}"
        echo ""
    else
        echo "${RED}${BOLD}⚠ $failed OF $((passed + failed)) TESTS FAILED.${RESET}"
        echo "Ensure INDRA backend is running via ${CYAN}./start.sh bg${RESET} or ${CYAN}./start.sh start${RESET}"
        echo ""
        exit 1
    fi
}

# --- Subcommand: logs ---
cmd_logs() {
    if [[ ! -f "$LOG_FILE" ]]; then
        echo "${YELLOW}ℹ Log file $LOG_FILE does not exist yet.${RESET}"
        touch "$LOG_FILE"
    fi
    echo "${CYAN}Streaming live logs from $LOG_FILE (Press Ctrl+C to exit)...${RESET}"
    tail -n "$LOG_LINES" -f "$LOG_FILE"
}

# --- Subcommand: clean ---
cmd_clean() {
    echo "${BOLD}🧹 Cleaning temporary files, caches, and logs...${RESET}"
    find "$ROOT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$ROOT_DIR" -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find "$ROOT_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    rm -rf "$FRONTEND_DIR/.next"
    rm -rf "$RUN_DIR"/*.pid "$LOG_DIR"/*.log
    echo "${GREEN}✓ Project cleaned (Python bytecode, test cache, and Next.js build cache purged).${RESET}"
}

# --- Argument Parsing ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        start|frontend|backend|bg|daemon|stop|restart|status|setup|infra|doctor|demo|test|logs|clean|help)
            COMMAND="$1"
            shift
            if [[ "$COMMAND" == "infra" && $# -gt 0 && ! "$1" =~ ^- ]]; then
                INFRA_ACTION="$1"
                shift
            fi
            ;;
        --frontend-port)
            FRONTEND_PORT="$2"
            shift 2
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -H|--host)
            HOST="$2"
            shift 2
            ;;
        -w|--workers)
            WORKERS="$2"
            shift 2
            ;;
        --reload)
            RELOAD=true
            shift
            ;;
        --no-reload)
            RELOAD=false
            shift
            ;;
        -n|--no-browser)
            NO_BROWSER=true
            shift
            ;;
        -b|--background)
            COMMAND="bg"
            shift
            ;;
        -f|--force)
            FORCE=true
            shift
            ;;
        --with-infra)
            WITH_INFRA=true
            shift
            ;;
        -n-lines)
            LOG_LINES="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "${RED}Unknown option or argument: $1${RESET}"
            echo "Run ${CYAN}./start.sh --help${RESET} for usage guidance."
            exit 1
            ;;
    esac
done

COMMAND="${COMMAND:-start}"

case "$COMMAND" in
    start)
        cmd_start
        ;;
    frontend)
        cmd_frontend
        ;;
    backend)
        cmd_backend
        ;;
    bg|daemon)
        cmd_bg
        ;;
    stop)
        cmd_stop
        ;;
    restart)
        cmd_restart
        ;;
    status)
        cmd_status
        ;;
    setup)
        cmd_setup
        ;;
    infra)
        cmd_infra "$INFRA_ACTION"
        ;;
    doctor)
        cmd_doctor
        ;;
    demo)
        cmd_demo
        ;;
    test)
        cmd_test
        ;;
    logs)
        cmd_logs
        ;;
    clean)
        cmd_clean
        ;;
    help)
        show_help
        ;;
    *)
        echo "${RED}Unrecognized command: $COMMAND${RESET}"
        show_help
        exit 1
        ;;
esac
