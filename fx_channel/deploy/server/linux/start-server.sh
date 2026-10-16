#!/usr/bin/env sh
set -eu

BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SERVER_BIN="$BASE_DIR/fx-channel-server"
CONFIG_FILE="$BASE_DIR/config/operator.yaml"
CONTENT_DIR="$BASE_DIR/content"
WEB_USER_DIR="$BASE_DIR/web-user"

if [ ! -f "$SERVER_BIN" ]; then
  echo "ERROR: $SERVER_BIN not found." >&2
  exit 1
fi

if [ ! -f "$CONFIG_FILE" ]; then
  echo "ERROR: $CONFIG_FILE not found." >&2
  echo "Copy config/operator.example.yaml to config/operator.yaml first." >&2
  exit 1
fi

if [ -z "${FX_CHANNEL_OPERATOR_TOKEN:-}" ]; then
  echo "ERROR: FX_CHANNEL_OPERATOR_TOKEN is not set." >&2
  exit 1
fi

exec "$SERVER_BIN" --operator "$CONFIG_FILE" --content "$CONTENT_DIR" --web-user "$WEB_USER_DIR"
