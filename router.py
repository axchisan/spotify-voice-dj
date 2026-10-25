"""Vía rápida: resuelve las órdenes simples sin cargar el modelo de IA.

Devuelve (herramienta, argumentos) o None. Solo responde cuando está segura; lo
ambiguo ("algo para asear", "otra más tranquila") lo resuelve el modelo.
Esto ahorra los ~6 GB y los segundos de carga en la mayoría de peticiones.
"""
import re
import unicodedata

RELLENO = r"^(?:(?:hey|ey|oye|ok|okey|eh|bueno|dj|porfa|por favor|please|a ver)[\s,]+)+"
RELLENO_FINAL = r"(?:[\s,]+(?:porfa|por favor|please|gracias|y nada mas|nada mas|solamente|y solo eso|solo eso))+$"
PONER = r"(?:pon(?:me|nos|le|te)?|reproduce|reproduceme|toca|tocame|quiero (?:escuchar|oir)|dame|mete(?:me)?|suena|echa a andar|arranca|activa|inicia)"

# Géneros y estilos reconocibles: "pon jazz", "algo de salsa", "música clásica de piano".
GENEROS = (r"clasica|opera|jazz|blues|salsa|bachata|merengue|cumbia|tango|bolero|boleros|flamenco|bossa nova|samba|"
           r"lo-?fi|lofi|electronica|electro|techno|house|trance|dubstep|drum and bass|synthwave|ambient|chill|chillout|"
           r"rock|metal|grunge|punk|emo|indie|pop|k-?pop|j-?pop|anime|soundtrack|bandas sonoras|instrumental|piano|"
           r"acustico|acustica|funk|soul|r&b|disco|reggae|ska|country|folk|gospel|rap|hip hop|trap|phonk|"
           r"metalcore|hardcore|nu metal|industrial|gotico|goth|post rock|progresivo|"
           r"reggaeton|regueton|perreo|dembow|corridos?|despecho|popular|carrilera|vallenato|guaracha|urbano")
NUM = {"media hora": 30, "una hora": 60, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
       "ocho": 8, "nueve": 9, "diez": 10, "quince": 15, "veinte": 20, "treinta": 30, "cuarenta": 40,
       "cincuenta": 50, "sesenta": 60, "noventa": 90, "cien": 100}


def normalizar(texto):
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[¿?¡!.,;:\"]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(RELLENO, "", t)
    t = re.sub(RELLENO_FINAL, "", t)
    return t.strip()


def numero(texto):
    texto = texto.strip().replace("minutos", "").replace("minuto", "").strip()
    if texto.isdigit():
        return int(texto)
    return NUM.get(texto)


# (patrón, herramienta, argumentos fijos) para órdenes sin parámetros.
CONTROLES = [
    (r"(?:pausa(?:la)?|pausar|para(?:la)?|detente|deten(?:la)?|stop|silencio|callate|para la musica|pausa la musica|quita la musica)", "control", {"accion": "pausa"}),
    (r"(?:sigue|seguir|continua(?:r)?|reanuda(?:r)?|dale play|play|dale|quita la pausa|vuelve a ponerla|ponla otra vez|reanuda la musica|sigue la musica)", "control", {"accion": "seguir"}),
    (r"(?:siguiente|la siguiente|siguiente cancion|pasa(?:la)?|pasa a la siguiente|pasa la cancion|salta(?:la)?|salta esta|skip|cambia(?:la)?|cambia de cancion|otra cancion|la que sigue|next|esa no|esta no)", "control", {"accion": "siguiente"}),
    (r"(?:anterior|la anterior|cancion anterior|vuelve atras|regresa la cancion|regresala|regresa|pon la anterior|atras)", "control", {"accion": "anterior"}),
    (r"(?:aleatorio|modo aleatorio|activa el aleatorio|quita el aleatorio|shuffle)", "control", {"accion": "aleatorio"}),
    (r"(?:repite|repitela|repite esta(?: cancion)?|repetir|pon(?:la)? en repetir|en bucle)", "control", {"accion": "repetir"}),
    (r"(?:sube(?:le)?|sube el volumen|subele(?: un poco)?(?: el volumen)?|sube(?: un poco)?(?: el volumen)?|mas (?:alto|duro|volumen)|subele mas)", "control", {"accion": "subir"}),
    (r"(?:baja(?:le)?|baja el volumen|bajale(?: un poco)?(?: el volumen)?|baja(?: un poco)?(?: el volumen)?|mas (?:bajo|suave|despacio)|menos volumen|bajale mas)", "control", {"accion": "bajar"}),
    (r"(?:que (?:suena|esta sonando|cancion es(?: esta)?|es esto|estoy escuchando)|quien canta(?: esto| esta)?|como se llama (?:esta|la) cancion|que cancion suena)", "que_suena", {}),
    (r"(?:me gusta(?: esta)?(?: cancion)?|me encanta(?: esta)?(?: cancion)?|guarda(?:la)?(?: esta)?(?: cancion)?|dale like|like|guardala en me gusta)", "guardar_cancion_actual", {}),
    (rf"(?:{PONER} )?(?:a )?(?:la |el )?(?:dj|livi|dj livi)(?: de spotify)?", "poner_dj", {}),
    (rf"(?:{PONER} |mezcla |pon en aleatorio )?(?:mis (?:me gusta|favoritas|canciones(?: favoritas)?|canciones guardadas)|(?:las )?canciones que me gustan)", "poner_mis_me_gusta", {}),
    (r"(?:cancela|quita) el temporizador", "temporizador", {"minutos": 0}),
]

# Patrones con un nombre de artista: solo se usan si el artista existe con ese nombre exacto.
CON_ARTISTA = [
    (rf"(?:{PONER} )?(?:la |una )?radio de (.+)", "radio_de_artista"),
    (rf"(?:{PONER} )?(?:algo|musica|canciones) (?:como|parecid[ao]s? a|similar(?:es)? a|del estilo de|tipo) (.+)", "radio_de_artista"),
    (rf"{PONER} (?:solo |solamente |unicamente )?(?:musica|canciones|temas|algo|exitos|lo mejor) de (.+?)(?: (?:y )?(?:nada mas|solamente|solo eso|y solo eso))?", "poner_artista"),
    (rf"{PONER} (?:a )?(.+)", "poner_artista_conocido"),
]


def resolver(texto, artista_exacto, conocidos=frozenset(), clave=lambda x: x):
    """artista_exacto(nombre) → artista de Spotify o None (para validar nombres).
    conocidos: claves de artistas del perfil; "pon X" a secas solo va por la vía
    rápida si X es uno de ellos (si no, podría ser una canción: "pon Lonely Day")."""
    t = normalizar(texto)
    if not t:
        return None
    for patron, herramienta, args in CONTROLES:
        if re.fullmatch(patron, t):
            return herramienta, dict(args)

    if m := re.fullmatch(r"(?:pon(?:le|me)? |sube |baja )?(?:el )?volumen (?:al? |en )?(\w+)(?: por ciento)?", t):
        if (n := numero(m.group(1))) is not None:
            return "control", {"accion": "volumen", "valor": n}
    if m := re.fullmatch(r"(?:adelanta(?:la)?|avanza)(?: (\w+) segundos)?", t):
        return "control", {"accion": "adelantar", "valor": numero(m.group(1) or "30") or 30}
    if m := re.fullmatch(r"(?:retrocede|atrasa|regresa)(?: (\w+) segundos)?", t):
        return "control", {"accion": "retroceder", "valor": numero(m.group(1) or "30") or 30}
    if m := re.fullmatch(r"(?:(?:apaga|para|pausa|quita) (?:la musica |todo )?en|temporizador de|pon un temporizador de) (\w+) minutos?", t):
        if (n := numero(m.group(1))) is not None:
            return "temporizador", {"minutos": n}

    # Variantes sueltas: se buscan dentro de la frase, no como frase exacta.
    if re.fullmatch(r"(?:salta|pasa|cambia|quita)(?:la|le)?(?: esta| esa)?(?: cancion| rola| tema)?", t):
        return "control", {"accion": "siguiente"}
    if re.fullmatch(r"(?:dale play|dale|continua|sigue|reanuda|vuelve a poner)(?: con)?(?: la)?(?: musica| cancion)?(?: otra vez| de nuevo)?", t):
        return "control", {"accion": "seguir"}
    if re.fullmatch(r"(?:vuelve|regresa|pon)(?: a)? la(?: cancion)? (?:de antes|anterior)", t):
        return "control", {"accion": "anterior"}
    if re.search(r"\b(?:guarda(?:la|me)?|me (?:gusta|encanta)(?: mucho)? esta)\b", t) and not re.search(r"\bpon", t):
        return "guardar_cancion_actual", {}
    if re.search(r"\b(?:no me gusta|no me late|que fea|horrible)\b", t) and re.search(r"\b(?:cambia|quita|pasa|salta|otra|siguiente)", t):
        return "control", {"accion": "siguiente"}
    if re.fullmatch(r"(?:esta|esta muy|muy|demasiado) (?:alto|duro|fuerte)(?: el volumen)?|(?:esta|suena) muy (?:alto|duro|fuerte)", t):
        return "control", {"accion": "bajar"}
    if re.fullmatch(r"(?:esta|esta muy|muy) (?:bajo|bajito|suave)(?: el volumen)?|no se (?:oye|escucha)(?: nada)?", t):
        return "control", {"accion": "subir"}
    if m := re.fullmatch(r"(sube|subele|baja|bajale)(?: el)?(?: volumen)?(?: un poco| un poquito| mas| bastante| mucho)?(?: el volumen)?(?: un poco| mas)?", t):
        paso = 30 if re.search(r"mucho|bastante", t) else 0
        return "control", {"accion": "subir" if m.group(1).startswith("sub") else "bajar", **({"valor": paso} if paso else {})}
    if m := re.search(r"(?:apaga|para|pausa|quita|deten) (?:la musica |todo |el spotify )?en (media hora|una hora|\w+ minutos?)", t):
        if (n := numero(m.group(1))) is not None:
            return "temporizador", {"minutos": n}

    # Géneros: van antes que los artistas ("algo de despecho" no es un artista).
    if m := re.fullmatch(rf"(?:{PONER} )?(?:un poco de |algo de |musica |musica de |canciones de |puro |pura )?((?:[\w&-]+ )*?(?:{GENEROS})(?: [\w&-]+)*)", t):
        genero = re.sub(r" para .*$", "", m.group(1))
        if re.search(r"\b(?:playlist|lista|album|el disco|un disco|cancion|tema|rola)\b", genero):
            return None
        if re.match(rf"(?:{PONER} )?musica ", t) and " " not in genero:
            genero = f"musica {genero}"
        if (re.search(rf"\b(?:{GENEROS})\b", genero) and
                (not re.search(r"\b(?:como|tipo|parecid|mis|de (?!los \d|los anos))\b", genero) or re.search(r"\bde los\b", genero))):
            return "poner_genero", {"genero": genero}

    for patron, herramienta in CON_ARTISTA:
        if m := re.fullmatch(patron, t):
            nombre = m.group(1).strip()
            # "música de los 80", "algo de rock" no son artistas: se le dejan al modelo.
            if len(nombre) < 2 or re.search(r"\b(?:los \d0|rock|metal|pop|jazz|clasica|musica|algo|variad|tranquil|"
                                             r"para|fiesta|momento|ambiente|genero|estilo|playlist|lista|album|disco)\b", nombre):
                return None
            if herramienta == "poner_artista_conocido":
                if clave(nombre) not in conocidos:
                    return None
                herramienta = "poner_artista"
            artista = artista_exacto(nombre)
            if artista:
                return herramienta, {"artista": artista["name"]}
            return None
    return None
