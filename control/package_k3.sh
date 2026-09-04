#!/usr/bin/env bash

set -Eeuo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
output_path="${1:-${script_directory}/../gexo_control_k3.tar.gz}"

tar \
  --exclude='control/build*' \
  --exclude='control/deploy/build*' \
  --exclude='control/deploy/tcn_pd/build*' \
  --exclude='*.pyc' \
  --exclude='__pycache__' \
  --transform='s,^control,gexo_control,' \
  -czf "$output_path" \
  -C "${script_directory}/.." control

printf 'Wrote %s\n' "$output_path"
