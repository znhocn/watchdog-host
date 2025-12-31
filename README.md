# Watchdog-Host

Watchdog-Host is a daemon designed to **monitor bandwidth usage on cloud hosts**, helping prevent unexpected charges caused by exceeding monthly traffic quotas.

## Features

- Monthly network traffic accounting for cloud instances
- Configurable via `config.yaml`, including:
  - Bandwidth quota limits
  - Usage percentage alert thresholds
- Multiple notification channels:
  - Email
  - WeCom (WeChat Work)
  - DingTalk
- Optional **automatic shutdown** when traffic usage exceeds the configured quota
- Runs as a systemd service, suitable for long-term unattended operation

## Usage Notes

- Historical network usage prior to the first run cannot be determined:
  - **Traffic statistics for the current month will be inaccurate on the first run**
  - Accurate statistics will be available starting from the next execution cycle
- Additional watchdog capabilities may be added in the future

## Requirements

- Must be executed as the **root user**
- Running via `sudo` is **not supported**
  - This is required due to systemd management and low-level network statistics access

## Installation

```shell
pip install watchdog-host
watchdog-host init
vim /etc/watchdog/config.yaml
systemctl enable --now <service>.service
systemctl status <service>.service
```

## Uninstallation

```shell
systemctl disable --now <service>.service
watchdog-host clean
pip uninstall -y watchdog-host

# Optional
rm -f /etc/watchdog/config.yaml
rm -f /etc/watchdog/*.json
```
