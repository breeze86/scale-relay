#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "error: please run with sudo" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="${SERVICE_NAME:-scale-relay}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
SERVICE_GROUP="${SERVICE_GROUP:-$(id -gn "${SERVICE_USER}")}"
CONFIG_PATH="${CONFIG_PATH:-${PROJECT_DIR}/config.yaml}"
LOG_DIR="${LOG_DIR:-/var/log/scale-relay}"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
LOGROTATE_FILE="/etc/logrotate.d/${SERVICE_NAME}"

if [ ! -f "${CONFIG_PATH}" ]; then
  echo "error: config file not found: ${CONFIG_PATH}" >&2
  echo "hint: set CONFIG_PATH=/path/to/config.yaml if your config is elsewhere" >&2
  exit 1
fi

if [ -x "${PROJECT_DIR}/.venv/bin/scale-relay" ]; then
  SCALE_RELAY_BIN="${SCALE_RELAY_BIN:-${PROJECT_DIR}/.venv/bin/scale-relay}"
else
  SCALE_RELAY_BIN="${SCALE_RELAY_BIN:-$(command -v scale-relay || true)}"
fi

if [ -z "${SCALE_RELAY_BIN}" ] || [ ! -x "${SCALE_RELAY_BIN}" ]; then
  echo "error: scale-relay executable not found" >&2
  echo "hint: install the project first, or set SCALE_RELAY_BIN=/path/to/scale-relay" >&2
  exit 1
fi

if ! command -v logrotate >/dev/null 2>&1; then
  echo "error: logrotate is required to keep logs within about 100MB" >&2
  echo "hint: install it first, for example: sudo apt install -y logrotate" >&2
  exit 1
fi

install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0755 "${LOG_DIR}"

sed \
  -e "s#__SERVICE_USER__#${SERVICE_USER}#g" \
  -e "s#__SERVICE_GROUP__#${SERVICE_GROUP}#g" \
  -e "s#__PROJECT_DIR__#${PROJECT_DIR}#g" \
  -e "s#__SCALE_RELAY_BIN__#${SCALE_RELAY_BIN}#g" \
  -e "s#__CONFIG_PATH__#${CONFIG_PATH}#g" \
  -e "s#__LOG_DIR__#${LOG_DIR}#g" \
  "${SCRIPT_DIR}/scale-relay.service.template" > "${SERVICE_FILE}"

cat > "${LOGROTATE_FILE}" <<EOF
${LOG_DIR}/scale-relay.log {
    size 10M
    rotate 2
    missingok
    notifempty
    compress
    copytruncate
    create 0644 ${SERVICE_USER} ${SERVICE_GROUP}
}
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

echo "installed systemd service: ${SERVICE_FILE}"
echo "installed logrotate config: ${LOGROTATE_FILE}"
echo "log limit: up to 3 files, about 30MB total (${LOG_DIR}/scale-relay.log + 2 rotated files)"
echo
echo "start:   sudo systemctl start ${SERVICE_NAME}"
echo "status:  sudo systemctl status ${SERVICE_NAME}"
echo "logs:    tail -f ${LOG_DIR}/scale-relay.log"
