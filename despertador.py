"""Detector de la palabra de activación (por defecto "Hey Jarvis") con openWakeWord.

La app DJ (que tiene el permiso de micrófono) envía el audio continuo por un
socket local: PCM de 16 bits, 16 kHz, mono. Cuando el modelo detecta la frase,
responde con el byte b"W" y la app empieza a escuchar la petición.
Coste medido: ~1,5 % de un núcleo de CPU escuchando sin parar.
"""
import socket
import threading
import time
from pathlib import Path

import numpy as np

DIR = Path(__file__).resolve().parent
PUERTO = 8766
MUESTRAS = 1280          # 80 ms de audio a 16 kHz, el bloque que espera openWakeWord
PAUSA_TRAS_DETECTAR = 2  # segundos sin volver a disparar


def iniciar(config, registrar=print):
    from openwakeword.model import Model

    modelos = DIR / "modelos"
    archivo = modelos / config.get("modelo_activacion", "hey_jarvis_v0.1.onnx")
    umbral = float(config.get("umbral_activacion", 0.5))
    modelo = Model(wakeword_models=[str(archivo)], inference_framework="onnx",
                   melspec_model_path=str(modelos / "melspectrogram.onnx"),
                   embedding_model_path=str(modelos / "embedding_model.onnx"))
    registrar(f"despertador listo: {archivo.name} (umbral {umbral})")

    def atender_cliente(conexion):
        pendiente = b""
        ultimo = 0.0
        with conexion:
            while datos := conexion.recv(8192):
                pendiente += datos
                while len(pendiente) >= MUESTRAS * 2:
                    bloque = np.frombuffer(pendiente[:MUESTRAS * 2], dtype=np.int16)
                    pendiente = pendiente[MUESTRAS * 2:]
                    puntuacion = max(modelo.predict(bloque).values())
                    if puntuacion >= umbral and time.time() - ultimo > PAUSA_TRAS_DETECTAR:
                        ultimo = time.time()
                        modelo.reset()
                        registrar(f"despertador: activado ({puntuacion:.2f})")
                        conexion.sendall(b"W")

    def servir():
        servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        servidor.bind(("127.0.0.1", PUERTO))
        servidor.listen(1)
        while True:
            conexion, _ = servidor.accept()
            threading.Thread(target=atender_cliente, args=(conexion,), daemon=True).start()

    threading.Thread(target=servir, daemon=True).start()
