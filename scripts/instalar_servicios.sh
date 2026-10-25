#!/bin/zsh
# Crea los servicios de inicio de sesión (launchd): cerebro, LM Studio sin ventana
# y la app DJ. Requiere el repositorio clonado en ~/spotify-voice-dj.
set -e
DIR="$HOME/spotify-voice-dj"
LA="$HOME/Library/LaunchAgents"
UV="$(command -v uv)"
mkdir -p "$LA"
plist() {  # etiqueta, argumentos (<string>…</string>), extra
  cat > "$LA/$1.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array>$2</array>
  <key>RunAtLoad</key><true/>
  $3
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$(dirname "$UV"):/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StandardErrorPath</key><string>$DIR/$1.err.log</string>
</dict></plist>
PL
  launchctl bootout "gui/$(id -u)/$1" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$LA/$1.plist"
}
plist spotifyvoicedj.cerebro "<string>$UV</string><string>run</string><string>-q</string><string>--script</string><string>$DIR/cerebro.py</string>" "<key>KeepAlive</key><true/>"
plist spotifyvoicedj.lmstudio "<string>$DIR/iniciar_lmstudio.sh</string>" ""
plist spotifyvoicedj.app "<string>/usr/bin/open</string><string>-a</string><string>/Applications/DJ.app</string>" ""
echo "Servicios instalados."
