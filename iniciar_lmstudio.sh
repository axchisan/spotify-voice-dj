#!/bin/zsh
# Al iniciar sesión: LM Studio en segundo plano (sin ventana) con su servidor local.
# No carga ningún modelo: el cerebro lo pide al usarse y se descarga solo al minuto.
"/Applications/LM Studio.app/Contents/Resources/app/.webpack/lms" daemon up
sleep 5
"/Applications/LM Studio.app/Contents/Resources/app/.webpack/lms" server start --port 1234
