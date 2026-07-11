#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "${script_dir}/.." && pwd)"

if command -v python3 >/dev/null 2>&1; then
  python_command=(python3)
elif command -v python >/dev/null 2>&1; then
  python_command=(python)
else
  echo "Python 3 is required to initialize local file secrets." >&2
  exit 1
fi

"${python_command[@]}" "${script_dir}/init-secrets.py"

compose_arguments=(compose)
if [[ -f "${repository_root}/.env" ]]; then
  compose_arguments+=(--env-file "${repository_root}/.env")
fi
compose_arguments+=(-f "${script_dir}/compose.yml" up --build --detach --wait)

cd -- "${repository_root}"
docker "${compose_arguments[@]}"
