# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.10,<2", "spotipy>=2.26", "openwakeword>=0.6", "onnxruntime"]
# ///
"""Cerebro de Spotify Voice DJ: recibe lo que dijiste (texto) y lo convierte en música.

1. Vía rápida (router.py): órdenes simples sin cargar el modelo (< 1 s).
2. Modelo local de LM Studio para lo abierto ("algo para asear", "otra más
   tranquila"), con tu perfil de gusto (perfil.json) y el contexto de la charla.

Servicio HTTP en 127.0.0.1:8765 (POST /pedir {"texto": "..."}). El modelo no vive
aquí: LM Studio lo carga al pedirlo y lo descarga solo tras `ttl_modelo` segundos.
"""
import importlib.util
import json
import sys
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DIR))
import router  # noqa: E402

API = "http://127.0.0.1:1234/v1/chat/completions"
MEMORIA_CHARLA = 300  # segundos que se recuerda la conversación
REGISTRO = DIR / "cerebro.log"
CONFIG = json.loads((DIR / "config.json").read_text())
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

_spec = importlib.util.spec_from_file_location("conector", DIR / "conector" / "spotify_mac.py")
conector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conector)

_TOOLS = conector.mcp._tool_manager.list_tools()
HERRAMIENTAS = {t.name: t.fn for t in _TOOLS}
ESQUEMAS = [{"type": "function", "function": {"name": t.name, "description": t.description,
             "parameters": t.parameters}} for t in _TOOLS]

historial = []
ultimo_uso = 0.0
cerrojo = threading.Lock()


def registrar(texto):
    with REGISTRO.open("a") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {texto}\n")


def resumen_perfil():
    """El perfil de gusto en pocas líneas: artista, energía, estilo y ambientes."""
    archivo = DIR / "perfil.json"
    if not archivo.exists():
        return ""
    artistas = [a for a in json.loads(archivo.read_text())["artistas"]
                if not conector.motivo_bloqueo([a["nombre"]])]
    artistas.sort(key=lambda a: -a["peso"])
    lineas = ["Su perfil (artistas que escucha; e = energía de 1 a 5):"]
    lineas += [f"- {a['nombre']} (e{a['energia']}, {a['estilo']}; {', '.join(a['ambientes'])})" for a in artistas[:45]]
    return "\n".join(lineas)


def artistas_conocidos():
    archivo = DIR / "perfil.json"
    if not archivo.exists():
        return frozenset()
    return frozenset(conector.clave(a["nombre"]) for a in json.loads(archivo.read_text())["artistas"])


def prompt_sistema():
    base = (DIR / "instrucciones.md").read_text().replace("{nombre}", CONFIG.get("nombre", "el usuario"))
    ahora = datetime.now()
    partes = [base, resumen_perfil(),
              f"Ahora son las {ahora:%H:%M} del {DIAS[ahora.weekday()]}.",
              f"Estado real de Spotify: {conector.estado_spotify()}"]
    if historial:
        partes.append("Lo último de esta conversación (para entender \"otra\", \"más tranquila\"…):\n" +
                      "\n".join(f"- Pidió: {h['pidio']} → hiciste: {h['hice']}" for h in historial[-4:]))
    return "\n\n".join(p for p in partes if p)


# El modelo responde con un JSON de forma fija (salida estructurada, forzada por
# LM Studio con una gramática). Con "tool calling" libre, el modelo pequeño a menudo
# anunciaba "pongo X" sin llamar a ninguna herramienta.
ESQUEMA_RESPUESTA = {
    "type": "object",
    "properties": {
        "herramienta": {"type": "string", "enum": [*HERRAMIENTAS, "ninguna"]},
        # Lo principal de la petición: artista, canción, álbum, playlist o género.
        "consulta": {"type": "string"},
        # Artista de la canción o del álbum, si lo dijo.
        "de_artista": {"type": "string"},
        "artistas": {"type": "array", "items": {"type": "string"}},
        "accion": {"type": "string", "enum": ["ninguna", "pausa", "seguir", "siguiente", "anterior", "aleatorio",
                                              "repetir", "adelantar", "retroceder", "volumen", "subir", "bajar"]},
        "numero": {"type": "integer"},
        "respuesta": {"type": "string"},
    },
    "required": ["herramienta", "consulta", "de_artista", "artistas", "accion", "numero", "respuesta"],
}
# Cómo se reparten los campos del JSON en los parámetros de cada herramienta.
CAMPO_PRINCIPAL = {"poner_artista": "artista", "radio_de_artista": "artista", "poner_cancion": "cancion",
                   "encolar": "cancion", "poner_album": "album", "poner_playlist": "nombre", "poner_genero": "genero"}


# Palabras de la petición → ambiente del perfil y energía máxima/mínima.
AMBIENTE_DE = [
    (r"dormir|sueño|relaj|calma|tranquil|estres|ansios|descans|medit", "tranquilo", (1, 3)),
    (r"triste|llorar|deprim|melanc|despecho|extraño|solo|sola", "melancolico", (1, 4)),
    (r"concentr|estudi|program|trabaj|leer|enfoc|foco", "concentracion", (1, 4)),
    (r"adrenalina|gym|gimnasio|correr|entren|pesad|energ|rabia|enoj|furia|intens", "adrenalina", (4, 5)),
    (r"fiesta|asea|limpi|cocin|lavar|feliz|buen humor|animo|anima|baila|flojera|manej", "fiesta", (3, 5)),
    (r"nostalg|recuerd|viej|antes", "nostalgico", (1, 5)),
    (r"oscur|dark|terror|noche", "oscuro", (3, 5)),
]


def artistas_para(texto, n=6):
    """Artistas del perfil que encajan con lo que pidió (si el modelo no eligió)."""
    import random
    import re as _re
    perfil = json.loads((DIR / "perfil.json").read_text())["artistas"] if (DIR / "perfil.json").exists() else []
    perfil = [a for a in perfil if not conector.motivo_bloqueo([a["nombre"]])]
    for patron, ambiente, (emin, emax) in AMBIENTE_DE:
        if _re.search(patron, texto.lower()):
            candidatos = [a for a in perfil if ambiente in a["ambientes"] and emin <= a["energia"] <= emax] or \
                         [a for a in perfil if emin <= a["energia"] <= emax]
            break
    else:
        candidatos = perfil  # "variada": de todo un poco
    candidatos = sorted(candidatos, key=lambda a: -a["peso"])[:n * 2]
    random.shuffle(candidatos)
    return [a["nombre"] for a in candidatos[:n]]


def argumentos(nombre, d, texto=""):
    args = {}
    if campo := CAMPO_PRINCIPAL.get(nombre):
        args[campo] = d.get("consulta", "")
        if nombre in ("poner_cancion", "encolar", "poner_album") and d.get("de_artista"):
            args["artista"] = d["de_artista"]
    if nombre == "poner_mezcla":
        args["artistas"] = [a for a in d.get("artistas") or [] if a.strip()] or artistas_para(texto)
    if nombre == "control":
        args["accion"] = d.get("accion", "")
        if d.get("numero"):
            args["valor"] = d["numero"]
    if nombre == "temporizador":
        args["minutos"] = d.get("numero", 0)
    return args


PARAMETROS = {t.name: set(t.parameters.get("properties", {})) for t in _TOOLS}


def llamar_modelo(mensajes):
    cuerpo = json.dumps({"model": CONFIG["modelo"], "messages": mensajes, "temperature": 0.2,
                         "reasoning_effort": "none", "ttl": CONFIG.get("ttl_modelo", 60),
                         "response_format": {"type": "json_schema", "json_schema": {
                             "name": "accion", "strict": True, "schema": ESQUEMA_RESPUESTA}}}).encode()
    req = urllib.request.Request(API, cuerpo, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(json.load(r)["choices"][0]["message"]["content"])


def ejecutar(nombre, args):
    try:
        return str(HERRAMIENTAS[nombre](**args))
    except Exception as e:
        return f"Error: {e}"


def para_voz(texto):
    """Respuesta de una herramienta → frase corta para leer en voz alta."""
    return texto.replace("Suena: ", "Suena ").replace("En pausa: ", "En pausa, ").strip()


def con_modelo(texto):
    decision = llamar_modelo([{"role": "system", "content": prompt_sistema()}, {"role": "user", "content": texto}])
    nombre = decision.get("herramienta", "ninguna")
    if nombre not in HERRAMIENTAS:
        return decision.get("respuesta") or "Listo.", []
    args = argumentos(nombre, decision, texto)
    resultado = ejecutar(nombre, args)
    registrar(f"   {nombre}({args}) → {resultado.splitlines()[0][:120]}")
    # Lo que se dice es el resultado real de la herramienta, no lo que el modelo supone.
    return para_voz(resultado), [(nombre, args)]


def atender(texto):
    """Devuelve (respuesta, vía, herramientas usadas)."""
    global historial, ultimo_uso
    with cerrojo:
        if time.time() - ultimo_uso > MEMORIA_CHARLA:
            historial = []
        ultimo_uso = time.time()
        rapida = router.resolver(texto, conector.artista_exacto, artistas_conocidos(), conector.clave)
        if rapida:
            nombre, args = rapida
            respuesta, via, hechas = para_voz(ejecutar(nombre, args)), "rapida", [(nombre, args)]
        else:
            (respuesta, hechas), via = con_modelo(texto), "modelo"
        resumen = ", ".join(f"{n}({', '.join(str(v) for v in a.values())})" for n, a in hechas) or "solo respondí"
        historial = (historial + [{"pidio": texto, "hice": resumen}])[-6:]
        registrar(f"» [{via}] {texto}  ←  {respuesta}")
        return respuesta, via, hechas


class Manejador(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/pedir":
            self.send_error(404)
            return
        datos = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
        texto = (datos.get("texto") or "").strip()
        try:
            respuesta = atender(texto)[0] if texto else "No te escuché bien."
        except Exception as e:
            registrar(f"ERROR {texto!r}: {e}")
            respuesta = "Algo falló, inténtalo otra vez."
        cuerpo = json.dumps({"respuesta": respuesta}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    registrar("cerebro en marcha")
    if CONFIG.get("activacion_por_voz", True):
        import despertador
        despertador.iniciar(CONFIG, registrar)
    ThreadingHTTPServer(("127.0.0.1", 8765), Manejador).serve_forever()
