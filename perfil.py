# /// script
# requires-python = ">=3.11"
# dependencies = ["spotipy>=2.26"]
# ///
"""Genera perfil.json: los artistas que escuchas, agrupados por energía y ambiente.

Uso:
  uv run perfil.py                         # usa tu actividad reciente en Spotify (API)
  uv run perfil.py --historial datos.zip   # usa tu historial completo (exportación de Spotify)

1. Toma tus ~70 artistas más escuchados.
2. Consulta sus etiquetas de estilo en MusicBrainz (1 consulta por segundo, sin clave).
3. Le pide al modelo local de LM Studio que clasifique cada artista.
El cerebro usa el resultado para entender "algo para concentrarme" o "adrenalina"
con TU música y no con una lista genérica.
"""
import argparse
import collections
import importlib.util
import json
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

DIR = Path(__file__).resolve().parent
API = "http://127.0.0.1:1234/v1/chat/completions"
MODELO = "qwen/qwen3.5-9b"
AGENTE = "SpotifyVoiceDJ/1.0 ( https://github.com/axchisan/spotify-voice-dj )"
AMBIENTES = ["adrenalina", "fiesta", "concentracion", "tranquilo", "melancolico", "nostalgico", "oscuro"]


def desde_historial(zip_path, n):
    horas = collections.Counter()
    recientes = collections.Counter()
    with zipfile.ZipFile(zip_path) as z:
        for nombre in z.namelist():
            if "Streaming_History_Audio" not in nombre or not nombre.endswith(".json"):
                continue
            for r in json.loads(z.read(nombre)):
                artista = r.get("master_metadata_album_artist_name")
                if artista:
                    horas[artista] += r["ms_played"] / 3.6e6
                    if r["ts"] >= ultimo_anio(z):
                        recientes[artista] += r["ms_played"] / 3.6e6
    elegidos = dict(horas.most_common(n))
    for a, h in recientes.most_common(n // 3):
        elegidos.setdefault(a, horas[a])
    return {a: round(h, 1) for a, h in elegidos.items()}


_corte = None


def ultimo_anio(z):
    global _corte
    if _corte is None:
        fechas = []
        for nombre in z.namelist():
            if "Streaming_History_Audio" in nombre and nombre.endswith(".json"):
                fechas += [r["ts"] for r in json.loads(z.read(nombre))[-50:]]
        ultima = max(fechas)
        _corte = f"{int(ultima[:4]) - 1}{ultima[4:]}"
    return _corte


def desde_api(n):
    spec = importlib.util.spec_from_file_location("conector", DIR / "conector" / "spotify_mac.py")
    conector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conector)
    puntos = collections.Counter()
    for peso, rango in ((3, "short_term"), (2, "medium_term"), (1, "long_term")):
        for i, a in enumerate(conector.sp().current_user_top_artists(limit=50, time_range=rango)["items"]):
            puntos[a["name"]] += peso * (50 - i)
    return {a: p for a, p in puntos.most_common(n)}


CACHE_TAGS = DIR / ".cache_etiquetas.json"


def etiquetas(artista):
    cache = json.loads(CACHE_TAGS.read_text()) if CACHE_TAGS.exists() else {}
    if artista in cache:
        return cache[artista]
    tags = _etiquetas_musicbrainz(artista)
    cache[artista] = tags
    CACHE_TAGS.write_text(json.dumps(cache, ensure_ascii=False))
    return tags


def _etiquetas_musicbrainz(artista):
    url = "https://musicbrainz.org/ws/2/artist/?" + urllib.parse.urlencode(
        {"query": f'artist:"{artista}"', "fmt": "json", "limit": 3})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
        with urllib.request.urlopen(req, timeout=8) as r:
            datos = json.load(r)["artists"]
    except Exception:
        return []
    finally:
        time.sleep(1.1)
    mejor = next((a for a in datos if a.get("score", 0) >= 90), None)
    tags = sorted(mejor.get("tags", []) if mejor else [], key=lambda t: -t.get("count", 0))
    return [t["name"] for t in tags[:6]]


def clasificar(lote):
    """Pide una línea por artista: nombre | energía | ambientes | estilo (más robusto que JSON)."""
    lineas = "\n".join(f"- {a}: {', '.join(t) or 'sin etiquetas'}" for a, t in lote)
    prompt = f"""Clasifica cada artista musical. Responde SOLO una línea por artista, con este formato exacto:
Nombre del artista | energía de 1 (muy calmado) a 5 (muy intenso) | 1 a 3 ambientes separados por coma de {AMBIENTES} | estilo en 2 a 4 palabras en español
Ejemplo: Metallica | 5 | adrenalina, oscuro | thrash metal clásico
Usa lo que sepas del artista y sus etiquetas. Artistas:
{lineas}"""
    cuerpo = json.dumps({"model": MODELO, "messages": [{"role": "user", "content": prompt}],
                         "temperature": 0.1, "reasoning_effort": "none", "ttl": 120}).encode()
    req = urllib.request.Request(API, cuerpo, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        texto = json.load(r)["choices"][0]["message"]["content"]
    resultado = {}
    for linea in texto.splitlines():
        partes = [p.strip(" -*") for p in linea.split("|")]
        if len(partes) < 4:
            continue
        try:
            energia = max(1, min(5, int(partes[1][:1])))
        except ValueError:
            energia = 3
        ambientes = [x.strip().lower() for x in partes[2].split(",") if x.strip().lower() in AMBIENTES]
        resultado[partes[0]] = {"energia": energia, "ambientes": ambientes, "estilo": partes[3]}
    return resultado


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--historial", help="zip de la exportación de datos de Spotify")
    p.add_argument("-n", type=int, default=70)
    args = p.parse_args()

    peso = desde_historial(args.historial, args.n) if args.historial else desde_api(args.n)
    print(f"{len(peso)} artistas. Consultando estilos en MusicBrainz…", flush=True)
    con_tags = [(a, etiquetas(a)) for a in peso]
    print("Clasificando con el modelo local…", flush=True)
    clasificados = {}
    for i in range(0, len(con_tags), 15):
        clasificados.update(clasificar(con_tags[i:i + 15]))

    artistas = []
    for a, tags in con_tags:
        c = clasificados.get(a) or next((v for k, v in clasificados.items() if k.lower() == a.lower()), {})
        artistas.append({"nombre": a, "peso": peso[a], "etiquetas": tags,
                         "energia": c.get("energia", 3), "ambientes": c.get("ambientes", []),
                         "estilo": c.get("estilo", "")})
    (DIR / "perfil.json").write_text(json.dumps({"artistas": artistas}, ensure_ascii=False, indent=1))
    print(f"perfil.json listo con {len(artistas)} artistas.")


if __name__ == "__main__":
    main()
