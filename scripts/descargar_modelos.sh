#!/bin/zsh
# Descarga los modelos de openWakeWord (frase "hey jarvis" y extractores de audio)
# en ./modelos. Los modelos preentrenados tienen licencia CC BY-NC-SA 4.0.
set -e
cd "${0:A:h}/.."
uv run -q --with "openwakeword>=0.6" --with onnxruntime python -c "
from openwakeword.utils import download_models
download_models(['hey_jarvis'], target_directory='modelos')"
echo "Modelos en ./modelos"
