"""Extrae las asignaciones planificadas (dia, equipo, tecnico, proyecto) desde
los mensajes "PROGRAMACION <dia>" del chat, que se publican (normalmente la
noche anterior) con bloques del tipo:

    EQUIPO 1 PABLO / YOVA / CARLOS
    FV-Juan Lopez Fernandez
    Calle SENTMENAT 80, Polinya
    ...instrucciones libres...

No todos los mensajes tienen el mismo formato exacto (a veces los tecnicos
van cada uno en su propia linea, a veces no hay fecha explicita en el titulo
sino solo el nombre del dia, a veces el año del titulo esta mal escrito).
Por eso la fecha objetivo y los bloques se resuelven con heuristicas —
revisa tabla_asignaciones.csv si necesitas confirmar una fecha dudosa.
"""
import re
from datetime import timedelta

from chat_utils import encontrar_tecnicos

TITULO_RE = re.compile(r"^\*?\s*PROGRAMACI[OÓ]N\b", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")
EQUIPO_RE = re.compile(r"^\s*EQUIPO\s*(\d+)?\s*(.*)$", re.IGNORECASE)
PAREN_RE = re.compile(r"\([^)]*\)")
NOMBRE_TOKEN_RE = re.compile(r"^[A-Za-zÀ-ÿ]+(\s[A-Za-zÀ-ÿ]+){0,2}$")

DIAS_SEMANA = {
    "lunes": 0, "dilluns": 0,
    "martes": 1, "dimarts": 1,
    "miercoles": 2, "miércoles": 2, "dimecres": 2,
    "jueves": 3, "dijous": 3,
    "viernes": 4, "divendres": 4,
    "sabado": 5, "sábado": 5, "dissabte": 5,
    "domingo": 6, "diumenge": 6,
}


def _resolver_fecha_explicita(dia, mes, anio, fecha_envio):
    anio = int(anio)
    if anio < 100:
        anio += 2000
    candidatos = dict.fromkeys([anio, fecha_envio.year, fecha_envio.year + 1, fecha_envio.year - 1])
    mejor = None
    for a in candidatos:
        try:
            cand = fecha_envio.replace(year=a, month=int(mes), day=int(dia))
        except ValueError:
            continue
        diff = abs((cand - fecha_envio).days)
        if mejor is None or diff < mejor[1]:
            mejor = (cand, diff)
    return mejor[0] if mejor else None


def _resolver_fecha_dia_semana(nombre_dia, fecha_envio):
    idx = DIAS_SEMANA.get(nombre_dia.lower())
    if idx is None:
        return None
    for offset in range(0, 7):
        cand = fecha_envio + timedelta(days=offset)
        if cand.weekday() == idx:
            return cand
    return None


def resolver_fecha_programacion(primera_linea, fecha_envio):
    """Fecha a la que aplica la programacion. Prioridad: fecha explicita en
    el titulo (corrigiendo años mal escritos) > nombre del dia > "noche
    anterior => dia siguiente" como ultimo recurso."""
    m = DATE_RE.search(primera_linea)
    if m:
        f = _resolver_fecha_explicita(*m.groups(), fecha_envio=fecha_envio)
        if f:
            return f
    for nombre in DIAS_SEMANA:
        if re.search(r"\b" + nombre + r"\b", primera_linea, re.IGNORECASE):
            f = _resolver_fecha_dia_semana(nombre, fecha_envio)
            if f:
                return f
    return fecha_envio + timedelta(days=1)


def _tecnicos_de_linea(linea, alias_regexes, no_reconocidos):
    """Si `linea` esta compuesta solo por nombres de tecnicos (separados por
    "/" o ","), devuelve la lista de canonicos. Si contiene cualquier otra
    cosa (direccion, instrucciones...), devuelve None.

    Si algun token con forma de nombre no esta en aliases.json (apodo nuevo
    no registrado), se ignora ese token pero se sigue reconociendo el resto
    de la linea (se registra en `no_reconocidos` para poder avisar)."""
    limpia = PAREN_RE.sub("", linea)
    tokens = [t.strip() for t in re.split(r"[/,]", limpia) if t.strip()]
    if not tokens or not all(NOMBRE_TOKEN_RE.match(t) for t in tokens):
        return None
    canonicos = []
    sin_resolver = []
    for t in tokens:
        encontrado = None
        for regex, canonico in alias_regexes:
            if regex.fullmatch(t):
                encontrado = canonico
                break
        if encontrado is None:
            sin_resolver.append(t)
        else:
            canonicos.append(encontrado)
    # Solo vale la pena avisar del apodo no reconocido si la linea ya se
    # confirmo como linea de tecnicos (algun otro token si resolvio); si no
    # resuelve ninguno, es mas probable que la linea sea otra cosa (nombre de
    # cliente, instruccion corta) y no un apodo nuevo.
    if canonicos and sin_resolver:
        no_reconocidos.update(sin_resolver)
    return canonicos


def _limpiar_proyecto(texto):
    texto = PAREN_RE.sub("", texto)
    texto = texto.replace("*", "")
    texto = re.sub(r"^\d+\.\s*", "", texto)
    return texto.strip(" :;-)")


def parsear_bloques_equipo(texto, alias_regexes, no_reconocidos):
    bloques = []
    actual = None
    for cruda in texto.split("\n"):
        # WhatsApp envuelve en asteriscos ("*EQUIPO 3 ...*") para negrita.
        linea = cruda.strip().strip("*").strip()
        m = EQUIPO_RE.match(linea)
        if m:
            if actual and actual["tecnicos"]:
                bloques.append(actual)
            numero = m.group(1)
            actual = {"equipo": f"EQUIPO {numero}" if numero else "EQUIPO", "tecnicos": [], "proyecto": None}
            resto = m.group(2).strip()
            if resto:
                tec = _tecnicos_de_linea(resto, alias_regexes, no_reconocidos)
                if tec:
                    actual["tecnicos"].extend(tec)
                elif actual["proyecto"] is None:
                    actual["proyecto"] = resto
            continue
        if actual is None or linea == "":
            continue
        tec = _tecnicos_de_linea(linea, alias_regexes, no_reconocidos)
        if tec and actual["proyecto"] is None:
            actual["tecnicos"].extend(tec)
        elif actual["proyecto"] is None:
            actual["proyecto"] = linea
    if actual and actual["tecnicos"]:
        bloques.append(actual)

    for b in bloques:
        vistos = []
        for t in b["tecnicos"]:
            if t not in vistos:
                vistos.append(t)
        b["tecnicos"] = vistos
        b["proyecto"] = _limpiar_proyecto(b["proyecto"]) if b["proyecto"] else ""
    return bloques


def extraer_asignaciones(mensajes, alias_regexes):
    """Devuelve (filas, fechas_con_programacion, no_reconocidos).

    filas: una fila por (fecha, equipo, tecnico) con su proyecto planificado.
    fechas_con_programacion: set de fechas (date) para las que se encontro al
    menos un mensaje de programacion, util para distinguir "no estaba
    programado" de "no hay programacion registrada ese dia".
    no_reconocidos: apodos con forma de nombre que aparecieron en un bloque
    EQUIPO pero no estan en aliases.json (ese tecnico se pierde de la fila
    hasta que se añada su alias)."""
    filas = []
    fechas_con_programacion = set()
    no_reconocidos = set()
    for msg in mensajes:
        primera_linea = msg["texto"].split("\n", 1)[0]
        if not TITULO_RE.match(primera_linea.strip()):
            continue
        fecha = resolver_fecha_programacion(primera_linea, msg["fecha"])
        fechas_con_programacion.add(fecha.date())
        bloques = parsear_bloques_equipo(msg["texto"], alias_regexes, no_reconocidos)
        for b in bloques:
            for tecnico in b["tecnicos"]:
                filas.append({
                    "fecha": fecha.strftime("%Y-%m-%d"),
                    "equipo": b["equipo"],
                    "tecnico": tecnico,
                    "proyecto": b["proyecto"],
                    "responsable_equipo": msg["remitente"],
                    "fecha_mensaje": msg["fecha"].strftime("%Y-%m-%d"),
                    "hora_mensaje": msg["hora"],
                    "linea": msg["linea"],
                    "texto_original": primera_linea[:200],
                })
    return filas, fechas_con_programacion, no_reconocidos
