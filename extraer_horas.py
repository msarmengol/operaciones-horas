#!/usr/bin/env python3
"""Extrae una tabla (fecha, proyecto, tecnico, horas) desde el export de WhatsApp
del grupo de operaciones, y la escribe a CSV. Se puede ejecutar a demanda con
filtros de fecha/tecnico/proyecto.

Los reportes de horas en el chat NO tienen un formato unico: cada persona los
escribe distinto ("Imputacion de horas: Nombre 8 horas", "8 horas Nombre",
"Reporte de horas: Nombre ... (8 horas)", etc.), hay apodos con erratas, y en
muchos casos el dato real esta solo en una imagen adjunta ("imagen omitida")
que no se puede leer en texto. Por eso la extraccion es heuristica:

  - Los tecnicos se reconocen contra un diccionario de alias editable en
    aliases.json (se crea automaticamente la primera vez que se ejecuta).
  - El proyecto EXPLICITO se extrae solo cuando aparece en el propio mensaje
    de horas (palabra "proyecto", o la descripcion tipo cliente/gestoria que
    usa Demetrio).
  - Ademas, el script cruza cada fila con los mensajes "PROGRAMACION <dia>"
    (asignaciones.py) para saber si ese tecnico estaba planificado ese dia y,
    si el proyecto no vino explicito en el reporte de horas, lo infiere de la
    planificacion (columna proyecto_fuente indica si es "explicito" o
    "inferido_programacion").
  - Ademas de tabla_horas.csv, el script escribe tabla_asignaciones.csv con
    la programacion planificada en crudo (fecha, equipo, tecnico, proyecto),
    por si se quiere inspeccionar o usar aparte de la tabla de horas.
  - Ademas de la tabla principal, el script genera listas de diagnostico:
      * sin_reconocer.csv: mensajes que mencionan horas pero cuyo/s tecnico/s
        no estan en aliases.json (hay que anadir el alias y re-ejecutar).
      * sin_datos_imagen.csv: mensajes tipo "Imputacion de horas" sin ningun
        dato en texto (el dato esta solo en la imagen adjunta en WhatsApp).
      * planificado_sin_horas.csv: tecnicos que aparecian programados en la
        "PROGRAMACION" de ese dia pero no tienen ninguna fila de horas ese
        dia (ausencia, cambio de ultima hora, o reporte solo en imagen).
  Revisa esas listas: son las que hay que completar o corregir a mano.

Uso:
    python extraer_horas.py
    python extraer_horas.py --desde 01/03/2026 --hasta 31/03/2026
    python extraer_horas.py --tecnico Guillermo --proyecto Octopus
    python extraer_horas.py --output tabla_marzo.csv --desde 01/03/2026 --hasta 31/03/2026
"""
import argparse
import csv
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from chat_utils import BASE_DIR, DEFAULT_ALIASES, DEFAULT_INPUT, cargar_alias, encontrar_tecnicos, parsear_mensajes
from asignaciones import TITULO_RE, extraer_asignaciones

DEFAULT_OUTPUT = BASE_DIR / "tabla_horas.csv"
DEFAULT_OUTPUT_ASIGNACIONES = BASE_DIR / "tabla_asignaciones.csv"

HOURS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:hrs?\.?|horas?)\b", re.IGNORECASE)
# El "horas"/"hrs" antes de "extra" es opcional: mucha gente escribe
# "8 horas +1.5 extra" o "8hrs + 3 extra" sin repetir la palabra horas.
EXTRA_RE = re.compile(r"\+?\s*(\d+(?:[.,]\d+)?)\s*(?:hrs?\.?|horas?)?\s*extras?\b", re.IGNORECASE)
# Formato abreviado sin la palabra "horas" en absoluto: "Nombre 8 + 1",
# "Nombre 8/+2" (base + extra). Solo se usa dentro de mensajes de cabecera
# de horas (HEADER_RE) para no disparar con telefonos u otros "+numero".
NM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*/?\s*\+\s*(\d+(?:[.,]\d+)?)")
PROYECTO_RE = re.compile(r"proyecto(?:\s+de|\s+del)?\s+([^\n;.,]{3,80})", re.IGNORECASE)
HEADER_RE = re.compile(r"imputaci|reporte de hora", re.IGNORECASE)


def _linea_de(texto, inicio, fin):
    """Devuelve (linea_completa, offset_absoluto_del_inicio_de_linea) para la
    linea que contiene el tramo [inicio, fin) de `texto`. Las busquedas de
    horas se acotan a esta linea para no "enganchar" un numero con la
    palabra horas de un parrafo distinto del mismo mensaje."""
    line_start = texto.rfind("\n", 0, inicio) + 1
    line_end = texto.find("\n", fin)
    if line_end == -1:
        line_end = len(texto)
    return texto[line_start:line_end], line_start


def extraer_proyecto(texto):
    m = PROYECTO_RE.search(texto)
    if m:
        return m.group(1).strip(" :;-")
    m2 = re.search(r"\)\s*([A-ZÁÉÍÓÚÑ][^\n]{5,120})", texto)
    if m2:
        return m2.group(1).strip(" :;-")
    return ""


def extraer_filas(msg, alias_regexes):
    texto = msg["texto"]
    proyecto = extraer_proyecto(texto)
    filas = []
    vistos = set()
    tecnicos_matched = False

    coincidencias = encontrar_tecnicos(texto, alias_regexes)
    es_cabecera = bool(HEADER_RE.search(texto))
    un_solo_tecnico = len(coincidencias) == 1 and es_cabecera

    for inicio, fin, canonico in coincidencias:
        linea, line_start = _linea_de(texto, inicio, fin)
        li, lf = inicio - line_start, fin - line_start

        horas_val = extra_val = None
        pos_abs = None

        # Formato "Nombre 8 + 1" / "Nombre 8/+2" (sin la palabra "horas"):
        # se prueba primero porque da base y extra en un solo match.
        nm = NM_RE.search(linea[lf:lf + 30]) if es_cabecera else None
        if nm:
            horas_val, extra_val = nm.group(1), nm.group(2)
            pos_abs = line_start + lf + nm.start()
        else:
            # Las horas y sus "extra" se buscan dentro de la MISMA linea
            # (nunca cruzando a otro parrafo del mensaje), y en la misma
            # direccion en la que se encontro el nombre, para no engancharse
            # con un "horas" de otra frase ni robarle el extra al compañero
            # de la linea siguiente.
            adelante = HOURS_RE.search(linea[lf:lf + 40])
            atras = HOURS_RE.search(linea[max(0, li - 40):li])
            if adelante:
                horas_val = adelante.group(1)
                pos_abs = line_start + lf + adelante.start()
                e = EXTRA_RE.search(linea[lf:lf + 80])
            elif atras:
                horas_val = atras.group(1)
                pos_abs = line_start + max(0, li - 40) + atras.start()
                e = EXTRA_RE.search(linea[max(0, li - 80):li])
            elif un_solo_tecnico:
                # Unico tecnico mencionado en el mensaje: buscar las horas en
                # todo el texto aunque esten lejos del nombre (mensajes largos
                # tipo "Reporte de horas: Nombre <descripcion> (N horas)").
                h = HOURS_RE.search(texto)
                e = EXTRA_RE.search(texto) if h else None
                if h:
                    horas_val, pos_abs = h.group(1), h.start()
            else:
                e = None
            if e:
                extra_val = e.group(1)

        if horas_val is None:
            continue
        tecnicos_matched = True
        clave = (canonico, pos_abs)
        if clave in vistos:
            continue
        vistos.add(clave)
        filas.append({
            "fecha": msg["fecha"].strftime("%Y-%m-%d"),
            "tecnico": canonico,
            "horas": horas_val.replace(",", "."),
            "horas_extra": extra_val.replace(",", ".") if extra_val else "",
            "proyecto": proyecto,
            "responsable_equipo": msg["remitente"],
            "hora_mensaje": msg["hora"],
            "linea": msg["linea"],
            "texto_original": texto.replace("\n", " | ")[:200],
        })
    return filas, tecnicos_matched


def procesar(mensajes, alias_regexes):
    filas, sin_reconocer, sin_datos = [], [], []
    for msg in mensajes:
        texto = msg["texto"]
        primera_linea = texto.split("\n", 1)[0].strip()
        if TITULO_RE.match(primera_linea):
            # Mensajes "PROGRAMACION <dia>": los procesa asignaciones.py, no
            # este pipeline. A veces mencionan horas como estimacion de
            # duracion del trabajo ("tiene para unas 6 horas"), no como
            # reporte de horas trabajadas, y terminan en sin_reconocer.csv
            # sin ser un caso real que arreglar.
            continue
        tiene_horas = bool(HOURS_RE.search(texto))
        es_cabecera = bool(HEADER_RE.search(texto))
        if not tiene_horas and not es_cabecera:
            continue
        if not tiene_horas and es_cabecera:
            sin_datos.append(msg)
            continue
        msg_filas, matched = extraer_filas(msg, alias_regexes)
        filas.extend(msg_filas)
        if tiene_horas and not matched:
            sin_reconocer.append(msg)
    return filas, sin_reconocer, sin_datos


def cruzar_con_programacion(filas, mensajes, alias_regexes):
    """Anade a cada fila de horas el resultado de compararla con la
    programacion planificada de ese dia, y devuelve tambien la lista de
    (fecha, equipo, tecnico, proyecto) programados que no tienen ninguna
    fila de horas ese dia."""
    asignaciones, fechas_con_programacion, no_reconocidos_prog = extraer_asignaciones(mensajes, alias_regexes)

    plan_por_fecha_tecnico = defaultdict(list)
    for a in asignaciones:
        plan_por_fecha_tecnico[(a["fecha"], a["tecnico"])].append(a)

    horas_por_fecha_tecnico = defaultdict(int)
    for f in filas:
        horas_por_fecha_tecnico[(f["fecha"], f["tecnico"])] += 1

    for f in filas:
        clave = (f["fecha"], f["tecnico"])
        plan = plan_por_fecha_tecnico.get(clave)
        if plan:
            f["estado_programacion"] = "programado"
            f["equipo_programado"] = ", ".join(sorted({p["equipo"] for p in plan}))
            proyecto_programado = "; ".join(sorted({p["proyecto"] for p in plan if p["proyecto"]}))
        elif datetime.strptime(f["fecha"], "%Y-%m-%d").date() in fechas_con_programacion:
            f["estado_programacion"] = "no_programado"
            f["equipo_programado"] = ""
            proyecto_programado = ""
        else:
            f["estado_programacion"] = "sin_programacion_dia"
            f["equipo_programado"] = ""
            proyecto_programado = ""

        if f["proyecto"]:
            f["proyecto_final"] = f["proyecto"]
            f["proyecto_fuente"] = "explicito"
        elif proyecto_programado:
            f["proyecto_final"] = proyecto_programado
            f["proyecto_fuente"] = "inferido_programacion"
        else:
            f["proyecto_final"] = ""
            f["proyecto_fuente"] = "sin_dato"

    planificado_sin_horas = []
    for (fecha, tecnico), plan in plan_por_fecha_tecnico.items():
        if horas_por_fecha_tecnico.get((fecha, tecnico)):
            continue
        for p in plan:
            planificado_sin_horas.append(p)

    return filas, planificado_sin_horas, no_reconocidos_prog, asignaciones


def aplicar_filtros(filas, desde, hasta, tecnico, proyecto):
    def ok(f):
        fecha = datetime.strptime(f["fecha"], "%Y-%m-%d")
        if desde and fecha < desde:
            return False
        if hasta and fecha > hasta:
            return False
        if tecnico and tecnico.lower() not in f["tecnico"].lower():
            return False
        if proyecto and proyecto.lower() not in f["proyecto_final"].lower():
            return False
        return True
    return [f for f in filas if ok(f)]


def escribir_csv(filas, ruta, columnas):
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        for fila in filas:
            w.writerow({c: fila.get(c, "") for c in columnas})


def resumen(filas):
    if not filas:
        print("No se extrajeron filas con los filtros indicados.")
        return
    por_tecnico = {}
    no_programado = 0
    for f in filas:
        try:
            h = float(f["horas"]) + float(f["horas_extra"] or 0)
        except ValueError:
            h = 0
        por_tecnico[f["tecnico"]] = por_tecnico.get(f["tecnico"], 0) + h
        if f["estado_programacion"] == "no_programado":
            no_programado += 1
    print(f"\nFilas extraidas: {len(filas)}")
    print(f"Filas con horas reportadas por tecnicos NO programados ese dia (imprevistos): {no_programado}")
    print("Horas totales por tecnico:")
    for nombre, total in sorted(por_tecnico.items(), key=lambda x: -x[1]):
        print(f"  {nombre:<30} {total:>6.1f} h")


def parse_fecha_arg(s):
    return datetime.strptime(s, "%d/%m/%Y") if s else None


def main():
    ap = argparse.ArgumentParser(description="Genera tabla dia/proyecto/tecnico/horas desde el chat de WhatsApp.")
    ap.add_argument("--input", default=str(DEFAULT_INPUT), help="Ruta al .md exportado de WhatsApp")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Ruta del CSV de salida")
    ap.add_argument("--output-asignaciones", default=str(DEFAULT_OUTPUT_ASIGNACIONES), help="Ruta del CSV de la programacion planificada (dia/equipo/tecnico/proyecto)")
    ap.add_argument("--alias", default=str(DEFAULT_ALIASES), help="Ruta al JSON de alias de tecnicos")
    ap.add_argument("--desde", help="Filtra desde esta fecha (DD/MM/AAAA)")
    ap.add_argument("--hasta", help="Filtra hasta esta fecha (DD/MM/AAAA)")
    ap.add_argument("--tecnico", help="Filtra por nombre de tecnico (substring)")
    ap.add_argument("--proyecto", help="Filtra por proyecto (substring, sobre proyecto_final)")
    ap.add_argument("--sin-diagnosticos", action="store_true", help="No escribir los CSV de diagnostico")
    args = ap.parse_args()

    alias_regexes = cargar_alias(Path(args.alias))
    mensajes = parsear_mensajes(Path(args.input))
    filas, sin_reconocer, sin_datos = procesar(mensajes, alias_regexes)
    filas, planificado_sin_horas, no_reconocidos_prog, asignaciones = cruzar_con_programacion(filas, mensajes, alias_regexes)

    filas = aplicar_filtros(
        filas,
        parse_fecha_arg(args.desde),
        parse_fecha_arg(args.hasta),
        args.tecnico,
        args.proyecto,
    )
    filas.sort(key=lambda f: (f["fecha"], f["tecnico"]))

    columnas = [
        "fecha", "proyecto_final", "proyecto_fuente", "tecnico", "horas", "horas_extra",
        "estado_programacion", "equipo_programado", "responsable_equipo", "hora_mensaje",
        "linea", "texto_original",
    ]
    escribir_csv(filas, args.output, columnas)
    print(f"Tabla escrita en: {args.output}")

    desde, hasta = parse_fecha_arg(args.desde), parse_fecha_arg(args.hasta)

    def asignacion_ok(a):
        fecha = datetime.strptime(a["fecha"], "%Y-%m-%d")
        if desde and fecha < desde:
            return False
        if hasta and fecha > hasta:
            return False
        if args.tecnico and args.tecnico.lower() not in a["tecnico"].lower():
            return False
        return True

    asignaciones_filtradas = sorted(
        (a for a in asignaciones if asignacion_ok(a)),
        key=lambda a: (a["fecha"], a["equipo"], a["tecnico"]),
    )
    escribir_csv(
        asignaciones_filtradas,
        args.output_asignaciones,
        ["fecha", "equipo", "tecnico", "proyecto", "responsable_equipo", "fecha_mensaje", "hora_mensaje", "linea", "texto_original"],
    )
    print(f"Programacion planificada escrita en: {args.output_asignaciones} ({len(asignaciones_filtradas)} filas)")

    if not args.sin_diagnosticos:
        diag_cols = ["fecha", "responsable_equipo", "hora_mensaje", "linea", "texto_original"]

        def a_fila_diag(m):
            return {
                "fecha": m["fecha"].strftime("%Y-%m-%d"),
                "responsable_equipo": m["remitente"],
                "hora_mensaje": m["hora"],
                "linea": m["linea"],
                "texto_original": m["texto"].replace("\n", " | ")[:200],
            }

        ruta_sr = BASE_DIR / "sin_reconocer.csv"
        ruta_sd = BASE_DIR / "sin_datos_imagen.csv"
        ruta_psh = BASE_DIR / "planificado_sin_horas.csv"
        escribir_csv([a_fila_diag(m) for m in sin_reconocer], ruta_sr, diag_cols)
        escribir_csv([a_fila_diag(m) for m in sin_datos], ruta_sd, diag_cols)
        escribir_csv(
            sorted(planificado_sin_horas, key=lambda p: (p["fecha"], p["tecnico"])),
            ruta_psh,
            ["fecha", "equipo", "tecnico", "proyecto", "responsable_equipo", "fecha_mensaje", "hora_mensaje", "linea", "texto_original"],
        )
        print(f"Mensajes con horas pero tecnico no reconocido: {len(sin_reconocer)} -> {ruta_sr}")
        print(f"  (revisa esas lineas y añade el alias que falte en {args.alias})")
        print(f"Mensajes tipo 'Imputacion de horas' sin datos en texto (dato solo en imagen): {len(sin_datos)} -> {ruta_sd}")
        print(f"Tecnicos programados sin horas reportadas ese dia: {len(planificado_sin_horas)} -> {ruta_psh}")
        if no_reconocidos_prog:
            print(f"Apodos en bloques EQUIPO sin alias registrado (revisar aliases.json): {sorted(no_reconocidos_prog)}")

    resumen(filas)


if __name__ == "__main__":
    main()
