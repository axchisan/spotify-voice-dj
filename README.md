# Spotify Voice DJ

Un DJ por voz para **Spotify en macOS** que funciona entero en tu Mac: le hablas
("ponme algo para concentrarme", "radio de Ghost", "pasa a la siguiente") y una IA
local decide qué poner según **tu** gusto. Gratis, sin nube y sin gastar tokens.

> Proyecto experimental y personal, construido con Claude Code. El autor ya no lo
> usa a diario; se publica por si a alguien le sirve como punto de partida.

*English summary at the end.*

## Por qué existe

Spotify para Mac no se integra con Siri, y en macOS 27 Siri no entrega las
peticiones de música a apps de terceros sin adoptar esquemas de audio poco
documentados. Este proyecto toma otro camino: reconocimiento de voz de Apple en
el propio Mac + un modelo local en LM Studio + control de Spotify por AppleScript
y la Web API.

## Qué hace

- **Habla con él:** atajo **⌥Espacio** o frase de activación **"Hey Jarvis"**
  (opcional, se enciende y apaga con **⌥⇧Espacio**). Responde en voz alta y se
  queda unos segundos escuchando por si pides otra cosa.
- **Entiende muchas formas de pedir:** solo un artista, radio de un artista,
  canción, álbum, playlist, género ("música clásica", "lo-fi"), estado de ánimo o
  actividad ("algo que eleve mi adrenalina", "para asear la casa"), "música
  variada", la DJ de Spotify, cola, volumen, repetir, adelantar, temporizador para
  dormir…
- **Usa tu perfil de gusto:** `perfil.py` clasifica tus artistas más escuchados por
  energía y ambiente (a partir de tu historial o de la API).
- **Lista de bloqueo:** artistas y géneros que nunca deben sonar. Se filtran al
  pedir y un vigilante salta lo que se cuele en la DJ o en radios.
- **Ligero:** las órdenes simples se resuelven sin modelo en ~0,1 s (`router.py`);
  el modelo solo se carga para lo ambiguo y se descarga solo al minuto.

## Cómo está hecho

```
DJ.app (Swift, barra de menús)  ── micrófono, voz→texto en el Mac, respuesta hablada
   │  POST /pedir {"texto"}                         │ audio 16 kHz (si "Hey Jarvis" está activo)
   ▼                                                ▼
cerebro.py (127.0.0.1:8765) ── router.py (vía rápida)      despertador.py (openWakeWord, :8766)
   │            └── LM Studio (Qwen 3.5 9B, salida JSON estructurada)
   ▼
conector/spotify_mac.py ── Spotify: Web API para buscar, AppleScript para reproducir
```

El conector también es un **servidor MCP**, así que puedes usarlo desde el chat de
LM Studio (ver `lmstudio-mcp.example.json`).

## Requisitos

- Mac con chip Apple y **16 GB de RAM** (el modelo ocupa ~6 GB mientras se usa).
- **macOS 27** (la app usa APIs recientes; con ajustes debería compilar en 14+).
- **Spotify Premium** y la app de escritorio. Desde 2026 Spotify exige Premium al
  dueño de una app de desarrollador para usar su Web API.
- [LM Studio](https://lmstudio.ai), [uv](https://docs.astral.sh/uv/), Xcode y
  [XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`).

## Instalación

1. **Clona** el repositorio en `~/spotify-voice-dj` (las rutas lo asumen):
   `git clone https://github.com/axchisan/spotify-voice-dj ~/spotify-voice-dj`
2. **Spotify:** crea una app en <https://developer.spotify.com/dashboard> con la
   Redirect URI `http://127.0.0.1:8888/callback` y la Web API marcada. Crea
   `conector/.env` con:
   ```
   SPOTIFY_CLIENT_ID=...
   SPOTIFY_CLIENT_SECRET=...
   ```
   La primera vez se abrirá el navegador para autorizar.
3. **Configuración:** `cp config.example.json config.json` y
   `cp conector/bloqueados.example.json conector/bloqueados.json` (edítalos a tu gusto).
4. **Modelo:** en LM Studio descarga `qwen/qwen3.5-9b` (o `lms get qwen/qwen3.5-9b --mlx`).
5. **Perfil de gusto:** `uv run perfil.py` (o `uv run perfil.py --historial my_spotify_data.zip`
   con tu exportación de datos de Spotify).
6. **Frase de activación (opcional):** `scripts/descargar_modelos.sh`.
7. **App:** en `oido/project.yml` cambia `PRODUCT_BUNDLE_IDENTIFIER` y añade tu
   `DEVELOPMENT_TEAM` (un Apple ID gratuito sirve). Luego `oido/instalar.sh`.
8. **Servicios de inicio:** `scripts/instalar_servicios.sh`.

La primera vez macOS pedirá permisos de micrófono, reconocimiento de voz y
control de Spotify.

## Pruebas

`uv run pruebas/evaluar.py` pasa 106 frases (y `--nuevos`, 40 más que no se usaron
para afinar) por el cerebro con las herramientas simuladas y mide el acierto.
En el equipo del autor: 100 % en ambos bancos. Los casos usan los artistas del
autor; adáptalos a tu perfil.

## Limitaciones conocidas

- La frase de activación es "Hey Jarvis" (modelo preentrenado de openWakeWord).
  Entrenar una propia requiere el cuaderno oficial de openWakeWord.
- openWakeWord en Python gasta ~8 % de un núcleo cuando hay ruido de fondo.
- Spotify ya no devuelve géneros ni "top tracks" en su API; algunas funciones
  buscan alternativas (MusicBrainz, búsquedas por artista).
- Las playlists editoriales de Spotify no aparecen en la búsqueda de la API.

## Desinstalar

`scripts/desinstalar.sh` y borra la carpeta. Revoca el acceso en
<https://www.spotify.com/account/apps/> y borra tu app de desarrollador.

## Licencias

Código bajo licencia MIT. Los modelos preentrenados de openWakeWord tienen
licencia CC BY-NC-SA 4.0 y no se incluyen en el repositorio.

---

## English summary

A fully local voice DJ for Spotify on macOS. A Swift menu-bar app listens (⌥Space
or the optional "Hey Jarvis" wake word), transcribes speech on-device, and sends it
to a small Python "brain": a regex fast path handles simple commands instantly, and
a local LLM (Qwen 3.5 9B in LM Studio, structured JSON output) handles open-ended
requests like "something to boost my adrenaline" using a taste profile built from
your listening history. Playback goes through AppleScript (so the Spotify DJ and
artist radios work) and search through the Spotify Web API. Includes a blocklist
with a guardian that skips unwanted tracks, an MCP server for LM Studio chat, and
an evaluation suite. Requires Apple Silicon, 16 GB RAM, macOS 27 and Spotify
Premium. Experimental; the UI and docs are in Spanish.
