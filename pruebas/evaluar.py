# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.10,<2", "spotipy>=2.26"]
# ///
"""Banco de pruebas: pasa cada frase de casos.json por el cerebro y comprueba qué
herramienta eligió. Las herramientas que tocan Spotify se sustituyen por simulacros
(no suena nada); las búsquedas de artistas sí consultan Spotify, que es de solo lectura.

  uv run pruebas/evaluar.py            # todo
  uv run pruebas/evaluar.py adrenalina # solo frases que contengan la palabra
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("cerebro", DIR / "cerebro.py")
cerebro = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cerebro)

BLOQUEADOS_RAPIDOS = cerebro.conector.motivo_bloqueo


def simulacro(nombre):
    def f(**args):
        artista = args.get("artista") or ""
        if artista and BLOQUEADOS_RAPIDOS([artista]):
            return f"No lo pongo: {artista} está en tu lista de bloqueo."
        genero = args.get("genero") or ""
        if genero and BLOQUEADOS_RAPIDOS([], genero):
            return f"No lo pongo: '{genero}' es de un género que tienes bloqueado."
        if nombre == "poner_mezcla":
            if any(BLOQUEADOS_RAPIDOS([a]) for a in args.get("artistas", [])):
                return "No lo pongo: hay artistas bloqueados en la mezcla."
            return "Mezcla de 24 canciones. Suena: Flesh, de Ghostemane."
        return f"Hecho ({nombre}). Suena: Square Hammer, de Ghost."
    return f


cerebro.HERRAMIENTAS = {n: simulacro(n) for n in cerebro.HERRAMIENTAS}
cerebro.conector.estado_spotify = lambda: "Suena: Square Hammer, de Ghost."
cerebro.registrar = lambda *_: None

archivo = "casos_nuevos.json" if "--nuevos" in sys.argv else "casos.json"
sys.argv = [a for a in sys.argv if a != "--nuevos"]
casos = json.loads((DIR / "pruebas" / archivo).read_text())
if len(sys.argv) > 1:
    casos = [c for c in casos if sys.argv[1].lower() in c["frase"].lower()]

aciertos, fallos, tiempos = 0, [], {"rapida": [], "modelo": []}
for c in casos:
    cerebro.historial = []
    if c["frase"] in ("otra más tranquila", "algo más pesado"):
        cerebro.historial = [{"pidio": "pon la radio de Ghost", "hice": "radio_de_artista(Ghost)"}]
    cerebro.ultimo_uso = time.time()
    t0 = time.time()
    respuesta, via, hechas = cerebro.atender(c["frase"])
    dt = time.time() - t0
    tiempos[via].append(dt)
    usadas = [n for n, _ in hechas] or ["ninguna"]
    ok = usadas[0] in c["herramientas"]
    if ok and c["args"] and hechas:
        args = {k: str(v).lower() for k, v in hechas[0][1].items()}
        for k, opciones in c["args"].items():
            if k.startswith("_"):
                continue
            if not any(o.lower() in args.get(k, "") for o in opciones):
                ok = False
    if ok and hechas and hechas[0][0] == "poner_mezcla":
        artistas = hechas[0][1].get("artistas", [])
        energia = {a["nombre"]: a["energia"] for a in json.loads((DIR / "perfil.json").read_text())["artistas"]}
        es = [energia.get(a, 3) for a in artistas]
        if len(artistas) < 3:
            ok = False
        elif any(w in c["frase"] for w in ("dormir", "relaj", "tranquil", "estresado")) and sum(es) / len(es) > 3.2:
            ok = False
        elif any(w in c["frase"] for w in ("adrenalina", "pesado", "energía", "gym", "correr")) and sum(es) / len(es) < 3.8:
            ok = False
    if ok and "_bloqueo" in c["args"]:
        ok = any(w in respuesta.lower() for w in ("no lo pongo", "no puedo", "no pongo", "bloque", "no la pongo"))
    aciertos += ok
    marca = "✓" if ok else "✗"
    detalle = f"{hechas[0][0]}({hechas[0][1]})" if hechas else "—"
    print(f"{marca} [{via:6} {dt:4.1f}s] {c['frase']:<50} → {detalle[:70]} | {respuesta[:60]}", flush=True)
    if not ok:
        fallos.append(c["frase"])

print(f"\nAcierto: {aciertos}/{len(casos)} = {100 * aciertos / len(casos):.0f}%")
for via, ts in tiempos.items():
    if ts:
        print(f"  {via}: {len(ts)} frases, media {sum(ts) / len(ts):.1f}s")
if fallos:
    print("Fallos:", "; ".join(fallos))
