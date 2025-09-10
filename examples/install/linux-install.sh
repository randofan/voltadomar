#!/usr/bin/env bash
set -euo pipefail

# Simple installer for Voltadomar (Linux/systemd)
# This script must be run as root.

if [[ $EUID -ne 0 ]]; then
  echo "This script must be run as root." >&2
  exit 1
fi

# Paths
BIN_DIR=/usr/local/bin
CONF_DIR=/etc/voltadomar
STATE_DIR=/var/lib/voltadomar
LOG_DIR=/var/log/voltadomar
SYSTEMD_DIR=/etc/systemd/system
LOGROTATE_DIR=/etc/logrotate.d

# Build binaries
pushd "$(dirname "$0")/../../src/voltadomar" >/dev/null
  go build -o controller-binary ./cmd/controller
  go build -o agent-binary ./cmd/agent
popd >/dev/null

# Create users and dirs
id -u voltadomar &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin voltadomar
mkdir -p "$CONF_DIR" "$STATE_DIR" "$LOG_DIR"
chown -R voltadomar:voltadomar "$CONF_DIR" "$STATE_DIR" "$LOG_DIR"
chmod 0755 "$CONF_DIR" "$STATE_DIR" "$LOG_DIR"

# Install binaries
install -m 0755 src/voltadomar/controller-binary "$BIN_DIR/controller-binary"
install -m 0755 src/voltadomar/agent-binary "$BIN_DIR/agent-binary"

# Install example configs if not present
[[ -f "$CONF_DIR/controller.yaml" ]] || install -m 0644 examples/config/controller.yaml "$CONF_DIR/controller.yaml"
[[ -f "$CONF_DIR/agent.yaml" ]] || install -m 0644 examples/config/agent.yaml "$CONF_DIR/agent.yaml"

# Install systemd units
install -m 0644 examples/systemd/voltadomar-controller.service "$SYSTEMD_DIR/voltadomar-controller.service"
install -m 0644 examples/systemd/voltadomar-agent.service "$SYSTEMD_DIR/voltadomar-agent.service"

systemctl daemon-reload
systemctl enable voltadomar-controller.service
systemctl enable voltadomar-agent.service

# Install logrotate
install -m 0644 examples/logrotate/voltadomar "$LOGROTATE_DIR/voltadomar"

# Done
cat <<EOF
Installation complete.
- Edit configs in $CONF_DIR/*.yaml
- Start services: systemctl start voltadomar-controller voltadomar-agent
- Logs: $LOG_DIR/{controller.log,agent.log}
EOF

