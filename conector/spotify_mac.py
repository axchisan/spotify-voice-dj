# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.10,<2", "spotipy>=2.26"]
# ///
"""Conector para controlar Spotify en este Mac desde una IA (MCP o directamente).

Herramientas de alto nivel, una por tipo de petición: a un modelo pequeño le
cuesta menos elegir "poner_artista" que encadenar buscar + reproducir.

Busca con la Web API de Spotify y reproduce por AppleScript en la app local:
así funciona aunque el Mac no sea el "dispositivo activo" y puede lanzar la DJ
y las radios de artista, que la Web API no permite. Las respuestas son frases
cortas pensadas para leerse en voz alta.
"""
import json
import random
import subprocess
import threading
import time
import unicodedata
from pathlib import Path

import spotipy
from mcp.server.fastmcp import FastMCP
from spotipy.oauth2 import SpotifyOAuth

DIR = Path(__file__).resolve().parent
DJ_URI = "spotify:playlist:37i9dQZF1EYkqdzj48dyYq"
MIS_ME_GUSTA_URI = "spotify:collection:tracks"

mcp = FastMCP("spotify-mac")


def _env():
    return dict(l.split("=", 1) for l in (DIR / ".env").read_text().split() if "=" in l)


_sp = None


def sp():
    global _sp
    if _sp is None:
        env = _env()
        auth = SpotifyOAuth(
            client_id=env["SPOTIFY_CLIENT_ID"], client_secret=env["SPOTIFY_CLIENT_SECRET"],
            redirect_uri="http://127.0.0.1:8888/callback", open_browser=True,
            cache_handler=spotipy.CacheFileHandler(cache_path=str(DIR / ".token")),
        )
        _sp = spotipy.Spotify(auth_manager=auth, requests_timeout=10, retries=2)
    return _sp


# --- Filtro de géneros prohibidos -------------------------------------------------

def clave(texto):
    texto = unicodedata.normalize("NFKD", texto.lower().replace("$", "s"))
    return "".join(c for c in texto if c.isalnum() and not unicodedata.combining(c))


def _sin_tildes(texto):
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def _bloqueados():
    archivo = DIR / "bloqueados.json"
    if not archivo.exists():
        return set(), ()
    datos = json.loads(archivo.read_text())
    return ({clave(a) for a in datos.get("artistas", [])},
            tuple(_sin_tildes(p) for p in datos.get("palabras", [])))


def motivo_bloqueo(artistas, nombre=""):
    """Motivo si algo está bloqueado (por artista o por palabra en el nombre), o None.
    Compara sin tildes ni mayúsculas: "Reggaetón" = "reggaeton"."""
    artistas_bloq, palabras = _bloqueados()
    for a in artistas:
        if clave(a) in artistas_bloq:
            return f"{a} está en tu lista de bloqueo"
    n = _sin_tildes(nombre)
    if p := next((p for p in palabras if p in n), None):
        return f"{p} es un género que tienes bloqueado"
    return None


# --- AppleScript -----------------------------------------------------------------

def _osa(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip()


def _spotify(cmd):
    return _osa(f'tell application "Spotify" to {cmd}')


def _abrir_spotify():
    if _osa('application "Spotify" is running') != "true":
        subprocess.run(["open", "-g", "-a", "Spotify"])
        for _ in range(20):
            time.sleep(0.5)
            if _spotify("get player state as string"):
                break
        time.sleep(1)


def estado_spotify():
    """Estado legible de Spotify (también lo usa el cerebro como contexto)."""
    if _osa('application "Spotify" is running') != "true":
        return "Spotify está cerrado."
    estado = _spotify("get player state as string")
    if estado not in ("playing", "paused"):
        return "No está sonando nada."
    nombre = _spotify("get name of current track")
    artista = _spotify("get artist of current track")
    return f"{'Suena' if estado == 'playing' else 'En pausa'}: {nombre}, de {artista}."


def _reproducir(uri, espera=1.5, aleatorio=None):
    _abrir_spotify()
    if aleatorio is not None:
        _spotify(f"set shuffling to {str(aleatorio).lower()}")
    _spotify(f'play track "{uri}"')
    time.sleep(espera)
    return estado_spotify()


def _artista(nombre):
    """El artista que mejor coincide con el nombre (o None)."""
    items = [a for a in sp().search(q=nombre, type="artist", limit=5)["artists"]["items"] if a]
    if not items:
        return None
    return next((a for a in items if clave(a["name"]) == clave(nombre)), items[0])


def artista_exacto(nombre):
    """Solo si el nombre coincide exactamente (lo usa la vía rápida para no equivocarse)."""
    items = [a for a in sp().search(q=nombre, type="artist", limit=5)["artists"]["items"] if a]
    return next((a for a in items if clave(a["name"]) == clave(nombre)), None)


def _canciones_de(artista, n):
    """Hasta n canciones del artista (Spotify retiró 'top-tracks' en 2026: se busca)."""
    items = sp().search(q=f'artist:"{artista["name"]}"', type="track", limit=10)["tracks"]["items"]
    propias = [t for t in items if t and any(a["id"] == artista["id"] for a in t["artists"])]
    return [t["uri"] for t in propias[:n]]


def _encolar_en_segundo_plano(uris):
    def tarea():
        time.sleep(2)  # que Spotify registre el Mac como dispositivo activo
        for uri in uris:
            try:
                sp().add_to_queue(uri)
            except Exception:
                break
    threading.Thread(target=tarea, daemon=True).start()


# --- Herramientas ------------------------------------------------------------------

@mcp.tool()
def poner_artista(artista: str) -> str:
    """Pone SOLO canciones de ese artista, en aleatorio. Úsala para "pon música de X",
    "ponme a X", "quiero escuchar X"."""
    a = _artista(artista)
    if not a:
        return f"No encontré a {artista}."
    if motivo := motivo_bloqueo([a["name"]]):
        return f"No lo pongo: {motivo}."
    _reproducir(a["uri"], aleatorio=True)
    return f"Poniendo {a['name']}. " + estado_spotify()


@mcp.tool()
def radio_de_artista(artista: str) -> str:
    """Pone la radio de un artista: ese artista mezclado con otros parecidos.
    Úsala para "radio de X", "algo como X", "música parecida a X"."""
    a = _artista(artista)
    if not a:
        return f"No encontré a {artista}."
    if motivo := motivo_bloqueo([a["name"]]):
        return f"No lo pongo: {motivo}."
    _reproducir(f"spotify:radio:artist:{a['id']}")
    return f"Radio de {a['name']}. " + estado_spotify()


@mcp.tool()
def poner_cancion(cancion: str, artista: str = "") -> str:
    """Pone una canción concreta. Al terminar, Spotify sigue con música parecida."""
    q = f'track:"{cancion}" artist:"{artista}"' if artista else cancion
    items = [t for t in sp().search(q=q, type="track", limit=5)["tracks"]["items"] if t]
    if not items and artista:
        items = [t for t in sp().search(q=f"{cancion} {artista}", type="track", limit=5)["tracks"]["items"] if t]
    if not items:
        return f"No encontré la canción {cancion}."
    t = items[0]
    if motivo := motivo_bloqueo([a["name"] for a in t["artists"]], t["name"]):
        return f"No la pongo: {motivo}."
    _reproducir(t["uri"])
    return f"{t['name']}, de {t['artists'][0]['name']}."


@mcp.tool()
def poner_album(album: str, artista: str = "") -> str:
    """Pone un álbum completo."""
    q = f'album:"{album}" artist:"{artista}"' if artista else album
    items = [a for a in sp().search(q=q, type="album", limit=5)["albums"]["items"] if a]
    if not items:
        return f"No encontré el álbum {album}."
    al = items[0]
    if motivo := motivo_bloqueo([a["name"] for a in al["artists"]], al["name"]):
        return f"No lo pongo: {motivo}."
    _reproducir(al["uri"], aleatorio=False)
    return f"Álbum {al['name']}, de {al['artists'][0]['name']}."


@mcp.tool()
def poner_playlist(nombre: str) -> str:
    """Pone una playlist: primero busca entre las del usuario y si no, en Spotify."""
    if motivo := motivo_bloqueo([], nombre):
        return f"No la pongo: {motivo}."
    propias = [p for p in sp().current_user_playlists(limit=50)["items"] if p]
    elegida = next((p for p in propias if clave(nombre) in clave(p["name"])), None)
    if elegida and (motivo := motivo_bloqueo([], f"{elegida['name']} {elegida.get('description') or ''}")):
        # Es una playlist suya pero de un género bloqueado: no se busca otra parecida.
        return f"No la pongo: {motivo}."
    if not elegida:
        encontradas = [p for p in sp().search(q=nombre, type="playlist", limit=10)["playlists"]["items"] if p]
        elegida = next((p for p in encontradas
                        if not motivo_bloqueo([], f"{p['name']} {p.get('description') or ''}")), None)
    if not elegida:
        return f"No encontré la playlist {nombre}."
    _reproducir(elegida["uri"])
    return f"Playlist {elegida['name']}. " + estado_spotify()


@mcp.tool()
def poner_genero(genero: str) -> str:
    """Pone música de un género o estilo que no sea de un artista concreto:
    "música clásica", "jazz", "lo-fi", "rock de los 80", "metal industrial"."""
    if motivo := motivo_bloqueo([], genero):
        return f"No lo pongo: {motivo}."
    encontradas = [p for p in sp().search(q=genero, type="playlist", limit=10)["playlists"]["items"] if p]
    # Se descartan también las playlists cuya descripción mencione algo bloqueado.
    elegida = next((p for p in encontradas
                    if not motivo_bloqueo([], f"{p['name']} {p.get('description') or ''}")), None)
    if not elegida:
        return f"No encontré música de {genero}."
    _reproducir(elegida["uri"], aleatorio=True)
    return f"Música {genero}: {elegida['name']}. " + estado_spotify()


@mcp.tool()
def poner_mezcla(artistas: list[str]) -> str:
    """Mezcla canciones de varios artistas en aleatorio y llena la cola. Úsala para
    "música variada" o para un estado de ánimo o actividad, eligiendo 4 a 8 artistas
    del gusto del usuario que encajen."""
    uris = []
    for nombre in artistas[:8]:
        a = _artista(nombre)
        if a and not motivo_bloqueo([a["name"]]):
            uris += _canciones_de(a, 4)
    if not uris:
        return "No pude armar la mezcla."
    random.shuffle(uris)
    _reproducir(uris[0], aleatorio=False)
    _encolar_en_segundo_plano(uris[1:])
    return f"Mezcla de {len(uris)} canciones. " + estado_spotify()


@mcp.tool()
def poner_dj() -> str:
    """Pone la DJ de Spotify, la DJ con IA que conoce el gusto del usuario."""
    _reproducir(DJ_URI, espera=4)
    return "Poniendo la DJ."


@mcp.tool()
def poner_mis_me_gusta() -> str:
    """Pone las canciones que el usuario guardó como "Me gusta", en aleatorio."""
    _reproducir(MIS_ME_GUSTA_URI, aleatorio=True)
    return "Tus Me gusta en aleatorio. " + estado_spotify()


@mcp.tool()
def encolar(cancion: str, artista: str = "") -> str:
    """Añade una canción a la cola, para que suene después de la actual."""
    q = f'track:"{cancion}" artist:"{artista}"' if artista else cancion
    items = [t for t in sp().search(q=q, type="track", limit=5)["tracks"]["items"] if t]
    if not items:
        return f"No encontré la canción {cancion}."
    t = items[0]
    if motivo := motivo_bloqueo([a["name"] for a in t["artists"]], t["name"]):
        return f"No la pongo: {motivo}."
    try:
        sp().add_to_queue(t["uri"])
    except Exception:
        return "No pude añadirla a la cola; pon algo a sonar primero."
    return f"{t['name']} va después."


@mcp.tool()
def control(accion: str, valor: int = 0) -> str:
    """Controla la reproducción. accion: pausa, seguir, siguiente, anterior,
    aleatorio (alterna), repetir (alterna), adelantar / retroceder (valor en segundos,
    30 por defecto), volumen (valor 0-100), subir o bajar (valor opcional, 15 por defecto)."""
    _abrir_spotify()
    if accion == "pausa":
        _spotify("pause")
        return "Pausado."
    if accion == "seguir":
        _spotify("play")
    elif accion == "siguiente":
        _spotify("next track")
    elif accion == "anterior":
        _spotify("previous track")
    elif accion in ("aleatorio", "repetir"):
        prop = "shuffling" if accion == "aleatorio" else "repeating"
        activo = _spotify(f"get {prop}") == "true"
        _spotify(f"set {prop} to {str(not activo).lower()}")
        return f"{accion.capitalize()} {'desactivado' if activo else 'activado'}."
    elif accion in ("adelantar", "retroceder"):
        segundos = valor or 30
        signo = "+" if accion == "adelantar" else "-"
        _spotify(f"set player position to (player position {signo} {segundos})")
    elif accion in ("volumen", "subir", "bajar"):
        actual = int(_spotify("get sound volume") or 50)
        paso = valor or 15
        nuevo = valor if accion == "volumen" else actual + (paso if accion == "subir" else -paso)
        nuevo = max(0, min(100, nuevo))
        _spotify(f"set sound volume to {nuevo}")
        return f"Volumen al {nuevo}."
    else:
        return f"Acción desconocida: {accion}."
    time.sleep(1)
    return estado_spotify()


@mcp.tool()
def que_suena() -> str:
    """Dice qué canción está sonando ahora."""
    return estado_spotify()


@mcp.tool()
def guardar_cancion_actual() -> str:
    """Guarda en "Me gusta" la canción que está sonando."""
    uri = _spotify("get spotify url of current track")
    if not uri.startswith("spotify:track:"):
        return "No suena ninguna canción que se pueda guardar."
    sp()._put("me/library", args={"uris": uri})
    return "Guardada en tus Me gusta."


def vigilar(registrar=print, intervalo=2):
    """Bucle que salta lo bloqueado que se cuele (DJ, radios, playlists de terceros).
    Solo consulta la app local; no hace peticiones a internet."""
    revisada = None
    while True:
        try:
            if _osa('application "Spotify" is running') == "true" and _spotify("get player state as string") == "playing":
                uri = _spotify("get spotify url of current track")
                if uri != revisada:
                    revisada = uri
                    artista = _spotify("get artist of current track")
                    nombre = _spotify("get name of current track")
                    if motivo := motivo_bloqueo([a.strip() for a in artista.replace(" & ", ",").split(",")], nombre):
                        _spotify("next track")
                        registrar(f"vigilante: saltada {nombre} — {artista} ({motivo})")
        except Exception:
            pass
        time.sleep(intervalo)


_temporizador = None


@mcp.tool()
def temporizador(minutos: int) -> str:
    """Pausa la música dentro de X minutos (para dormir). 0 cancela el temporizador."""
    global _temporizador
    if _temporizador:
        _temporizador.cancel()
        _temporizador = None
    if minutos <= 0:
        return "Temporizador cancelado."
    _temporizador = threading.Timer(minutos * 60, lambda: _spotify("pause"))
    _temporizador.daemon = True
    _temporizador.start()
    return f"Pauso la música en {minutos} minutos."


if __name__ == "__main__":
    mcp.run()
