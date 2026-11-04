#!/usr/bin/env bash
set -euo pipefail

if (( $# == 0 )); then
  echo "usage: bash run-no-egress.sh <command> [args...]" >&2
  exit 64
fi

if ! command -v unshare >/dev/null 2>&1; then
  echo "unshare is required for the Linux no-egress runner" >&2
  exit 69
fi

# This intentionally creates a fresh network namespace with no configured
# external interfaces. The caller must have permission to create the namespace
# (normally root/CAP_SYS_ADMIN or a suitable user-namespace configuration).
exec unshare --net -- "$@"
