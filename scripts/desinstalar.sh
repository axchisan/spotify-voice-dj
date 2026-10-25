#!/bin/zsh
# Quita los servicios y la app DJ. No toca LM Studio ni tus credenciales.
for s in spotifyvoicedj.cerebro spotifyvoicedj.lmstudio spotifyvoicedj.app; do
  launchctl bootout "gui/$(id -u)/$s" 2>/dev/null
  rm -f "$HOME/Library/LaunchAgents/$s.plist"
done
pkill -x DJ 2>/dev/null
rm -rf /Applications/DJ.app
echo "Desinstalado. Puedes borrar la carpeta del repositorio."
