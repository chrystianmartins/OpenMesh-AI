#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  up) docker compose up -d --build ;;
  down) docker compose down ;;
  logs) docker compose logs -f ;;
  *)
    echo "uso: $0 {up|down|logs}"
    exit 1
    ;;
esac
