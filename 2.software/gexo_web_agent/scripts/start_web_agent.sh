#!/usr/bin/env bash
# Start the web agent.
#   ./start_web_agent.sh            → mock mode (no ROS 2 needed)
#   ./start_web_agent.sh ros2       → real topic mode (requires ROS 2 env)
set -euo pipefail

TRANSPORT="${1:-mock}"
PORT="${GEXO_PORT:-8000}"
cd "$(dirname "$0")/.."

exec python3 -m gexo_web_agent.main --transport "$TRANSPORT" --port "$PORT"
