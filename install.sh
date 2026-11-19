#!/bin/bash
# ./install.sh          set up Python env and config files
# ./install.sh service  run as a login service (starts at login, restarts on crash)
# ./install.sh uninstall
set -euo pipefail
cd "$(dirname "$0")"
DIR="$PWD"
LABEL="com.github.mac-remote"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

case "${1:-setup}" in
setup)
  command -v uv >/dev/null || { echo "Install uv first: brew install uv"; exit 1; }
  # uv-managed Python has a fixed path, so macOS permissions survive Homebrew upgrades
  uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python -r requirements.txt
  # Voice messages: a small Swift tool using macOS's on-device dictation model (macOS 26+)
  if command -v swiftc >/dev/null && swiftc -O -parse-as-library transcribe.swift -o .venv/bin/transcribe 2>/dev/null; then
    echo "Voice messages: on"
  else
    echo "Voice messages: off (needs macOS 26 or later and the Xcode Command Line Tools)"
  fi
  [ -f .env ] || { cp .env.example .env; chmod 600 .env; }
  [ -f config.toml ] || cp config.example.toml config.toml
  echo "Next: put your bot token in .env, then run: .venv/bin/python bot.py"
  ;;
service)
  [ -x .venv/bin/python ] || { echo "Run ./install.sh first"; exit 1; }
  CLAUDE_DIR="$(dirname "$(command -v claude || echo /usr/local/bin/claude)")"
  mkdir -p logs "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$DIR/.venv/bin/python</string><string>$DIR/bot.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$CLAUDE_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>$DIR/logs/stderr.log</string>
</dict></plist>
PLIST
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$PLIST"
  echo "Service running. Logs: $DIR/logs/"
  echo "For screenshots, add this binary under System Settings > Privacy & Security > Screen Recording:"
  echo "  $(readlink -f .venv/bin/python)"
  ;;
uninstall)
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Service removed."
  ;;
*) echo "usage: ./install.sh [setup|service|uninstall]"; exit 1 ;;
esac
