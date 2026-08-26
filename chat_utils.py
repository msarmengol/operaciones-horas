"""Utilidades compartidas para leer el export de WhatsApp y reconocer tecnicos.

Usado por extraer_horas.py y asignaciones.py.
"""
import json
import re
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "chat_ws_operaciones_2026.md"
DEFAULT_ALIASES = BASE_DIR / "aliases.json"

MSG_RE = re.compile(
    r"^‎?\[(?P<d>\d{1,2})/(?P<mo>\d{1,2})/(?P<y>\d{2,4}), "
    r"(?P<h>\d{1,2}):(?P<mi>\d{2}):(?P<s>\d{2})\]‎? (?P<sender>[^:]+): ?(?P<text>.*)$"
)

DEFAULT_ALIASES_SEED = {
    "Cesar": ["cesar"],
    "Josue Rosales": ["josue", "josué", "jouse"],
    "Yovany De Los Santos": ["yovany", "yova", "yoba", "jova"],
    "Carlos Alberto W": ["carlos"],
    "Juan Manuel Martinez": ["juan manuel", "jm"],
    "Silvana (Sil)": ["silvana", "sil"],
    "Santi Camilo Hno": ["santi", "santiago", "camilo"],
    "Francisco Pablo Hernandez": ["francisco pablo", "pablo hernandez", "francisco", "pablo"],
    "Fran": ["fran"],
    "Fran Amides": ["fran amides"],
    "Demetrio Instalador": ["demetrio"],
    "Jose Manuel Perez Practicas": ["jose manuel", "jose", "josé"],
    "Cristian": ["cristian", "christian", "crisitian", "crsitian", "criatian", "crisitan", "cristin", "cristrian", "crsitan"],
    "Guillermo": ["guillermo", "guillrmos", "guillermos"],
    "Yorman Duran": ["yorman"],
    "Janover": ["janover", "janower", "jabover", "janlver", "jano"],
    "Sherifo": ["sherifo", "sheriff", "sherif", "zherifo", "cherifo", "cheriffo", "sheriffo"],
    "Elio Tecnico": ["elio"],
    "Wiki Tecnico": ["wiki", "wikipedia", "wilki", "wikilfor"],
    "Alex": ["alex"],
    "Ricardo": ["ricardo"],
    "Aitor": ["aitor", "airto"],
    "Dani": ["dani"],
    "Musta": ["musta"],
    "Kike": ["kike"],
    "Hector Electricista": ["hector"],
    "Haninho Santos": ["haniñho", "haninho"],
    "Gustavo": ["gustavo"],
}


def cargar_alias(path=DEFAULT_ALIASES):
    path = Path(path)
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_ALIASES_SEED, ensure_ascii=False, indent=2), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    variantes = []
    for canonico, lista in data.items():
        for v in lista:
            variantes.append((v.lower(), canonico))
    # Variantes mas largas primero: un alias largo ("jose manuel") reclama su
    # tramo de texto antes que uno corto solapado ("jose").
    variantes.sort(key=lambda x: -len(x[0]))
    return [(re.compile(r"\b" + re.escape(v) + r"\b", re.IGNORECASE), canon) for v, canon in variantes]


def parsear_mensajes(ruta=DEFAULT_INPUT):
    mensajes = []
    actual = None
    with open(ruta, encoding="utf-8") as f:
        for numero, linea in enumerate(f, start=1):
            linea = linea.rstrip("\n")
            m = MSG_RE.match(linea)
            if m:
                if actual:
                    mensajes.append(actual)
                anio = int(m.group("y"))
                if anio < 100:
                    anio += 2000
                fecha = datetime(anio, int(m.group("mo")), int(m.group("d")))
                actual = {
                    "fecha": fecha,
                    "hora": f"{m.group('h')}:{m.group('mi')}:{m.group('s')}",
                    "remitente": m.group("sender").strip(),
                    "texto": [m.group("text")],
                    "linea": numero,
                }
            elif actual is not None:
                actual["texto"].append(linea)
        if actual:
            mensajes.append(actual)
    for msg in mensajes:
        msg["texto"] = "\n".join(msg["texto"]).strip()
    return mensajes


def span_libre(inicio, fin, ocupados):
    return not any(inicio < f and o < fin for o, f in ocupados)


def encontrar_tecnicos(texto, alias_regexes):
    """Encuentra menciones de tecnicos en `texto` sin solapes (alias largo
    reclama su tramo antes que uno corto). Devuelve lista de (inicio, fin, canonico)
    ordenada por posicion."""
    ocupados = []
    coincidencias = []
    for regex, canonico in alias_regexes:
        for match in regex.finditer(texto):
            inicio, fin = match.span()
            if not span_libre(inicio, fin, ocupados):
                continue
            ocupados.append((inicio, fin))
            coincidencias.append((inicio, fin, canonico))
    coincidencias.sort(key=lambda c: c[0])
    return coincidencias
