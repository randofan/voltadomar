## Goal
Make Controller and Agent run as simple Linux services with minimal configuration files and reliable log rotation. Keep everything straightforward.

## Scope (Linux only)
- OS: Linux with systemd (Ubuntu/Debian/CentOS).
- No macOS/Windows support in this iteration.
- No advanced observability/metrics. Focus on logs with rotation.
- Aim for minimal moving parts and easy install/operate.

## Components
- Binaries (built from Go sources under src/voltadomar):
  - controller-binary (cmd/controller)
  - agent-binary (cmd/agent)
- Config files (YAML):
  - /etc/voltadomar/controller.yaml
  - /etc/voltadomar/agent.yaml
- Services (systemd):
  - voltadomar-controller.service
  - voltadomar-agent.service
- Logs with rotation (logrotate):
  - /var/log/voltadomar/controller.log
  - /var/log/voltadomar/agent.log

## Configuration (simple)
- Format: YAML.
- No environment variable layer. CLI flags may override config for ad-hoc testing, but services will use config files.
- Controller config (controller.yaml):
  - port: 50051
  - session_range: "10000-20000"  # START-END
  - block_size: 100
  - log_level: info
- Agent config (agent.yaml):
  - agent_id: ""                    # default to hostname if empty
  - controller_address: "127.0.0.1:50051"
  - log_level: info
- Behavior:
  - Add a simple --config flag to both binaries to load YAML.
  - Precedence: CLI flags > config file > defaults.
  - No live reload; change config then restart service.

## Logging and rotation
- Services will redirect stdout/stderr to files under /var/log/voltadomar using systemd unit options or simple shell redirection.
- Use logrotate with copytruncate to rotate without requiring app log reopen support.
- Rotation policy (initial recommendation):
  - size 10M
  - rotate 7
  - daily
  - compress, delaycompress, missingok, notifempty, copytruncate

## Service management (systemd)
- Users/permissions (keep simple):
  - Controller runs as dedicated user: voltadomar (no shell, no home).
  - Agent runs as root (simplest for raw sockets). Optionally switch later to non-root + CAP_NET_RAW.
- Unit files (key settings):
  - Restart=on-failure, RestartSec=2s
  - WorkingDirectory=/var/lib/voltadomar
  - Ensure /etc/voltadomar exists and is readable by service user.
  - Logging: redirect to /var/log/voltadomar/*.log (via StandardOutput/StandardError or ExecStart shell redirection).
- Enable on boot; start/stop with systemctl.

## Filesystem layout
- Binaries: /usr/local/bin/{controller-binary, agent-binary}
- Configs: /etc/voltadomar/{controller.yaml, agent.yaml}
- State dir: /var/lib/voltadomar/
- Logs: /var/log/voltadomar/{controller.log, agent.log}
- Logrotate rule: /etc/logrotate.d/voltadomar

## Installation outline (simple)
1) Build binaries (make build or go build in src/voltadomar):
   - controller-binary, agent-binary
2) Create directories and users:
   - mkdir -p /etc/voltadomar /var/lib/voltadomar /var/log/voltadomar
   - useradd --system --no-create-home --shell /usr/sbin/nologin voltadomar (if not exists)
   - chown -R voltadomar:voltadomar /etc/voltadomar /var/lib/voltadomar /var/log/voltadomar (agent logs can still be root-owned if running as root)
3) Install binaries:
   - cp controller-binary agent-binary -> /usr/local/bin/
   - chmod 0755 on binaries
4) Place example configs into /etc/voltadomar and adjust values.
5) Install systemd units:
   - /etc/systemd/system/voltadomar-controller.service
   - /etc/systemd/system/voltadomar-agent.service
   - systemctl daemon-reload
   - systemctl enable voltadomar-controller
   - systemctl enable voltadomar-agent
6) Install logrotate config:
   - /etc/logrotate.d/voltadomar with rotation policy above
7) Start services:
   - systemctl start voltadomar-controller
   - systemctl start voltadomar-agent

## Operations
- Check status: systemctl status voltadomar-controller/voltadomar-agent
- View logs: tail -f /var/log/voltadomar/{controller.log,agent.log}
- Apply config changes: edit /etc/voltadomar/*.yaml, then systemctl restart <service>
- Troubleshoot: check permissions on /var/log/voltadomar and config paths; verify controller address and port.

## Work breakdown (implementation tasks)
1) Add minimal YAML config loading to both binaries:
   - --config flag
   - Load file into struct; apply defaults; allow CLI overrides
2) Create example configs under examples/config/{controller.yaml,agent.yaml}
3) Provide simple systemd unit files and a basic install script (or Makefile targets) for Linux only
4) Add logrotate config example and include it in install step
5) Update README with a short "Run as services on Linux" section

## Acceptance criteria
- Both controller and agent run as systemd services on Linux using only YAML config files
- Services produce logs at /var/log/voltadomar and rotate via logrotate with the stated policy
- Agent raw socket operations work when the service runs as root
- Install/start/stop/restart steps are documented and work on a standard Ubuntu/Debian system

## Next steps
- Confirm the above simplifications meet requirements
- Implement tasks 1–5 in order, test on a Linux VM, and iterate
