#!/bin/zsh
# Compila la app DJ, la instala en /Applications y borra la copia de compilación
# (si queda registrada, macOS puede abrir esa en lugar de la instalada).
set -e
cd "${0:A:h}"
LS=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
xcodegen generate -q
xcodebuild -project Oido.xcodeproj -scheme Oido -configuration Release -derivedDataPath build \
  -allowProvisioningUpdates -quiet build 2>&1 | grep -E "error:" || true
pkill -x DJ || true
rm -rf /Applications/DJ.app
cp -R build/Build/Products/Release/DJ.app /Applications/
$LS -u build/Build/Products/Release/DJ.app || true
rm -rf build/Build/Products
$LS -f /Applications/DJ.app
open /Applications/DJ.app
echo "DJ instalada."
