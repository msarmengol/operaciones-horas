"""App de Streamlit para que el cliente suba el chat de WhatsApp, lance la
extraccion y revise resultados (tablas + graficos) sin tocar la terminal.

Ejecutar local:   streamlit run app.py
Desplegar:        Streamlit Community Cloud, apuntando a este archivo.
"""
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from chat_utils import DEFAULT_ALIASES, cargar_alias, parsear_mensajes
from extraer_horas import cruzar_con_programacion, procesar
from graficos import (
    asignacion_tecnico_semana,
    heatmap_tecnico_semana,
    horas_por_tecnico,
    planificado_sin_horas_mensual,
    planificado_vs_real_mensual,
)

st.set_page_config(page_title="Operaciones · Horas y Programación", layout="wide")


@st.cache_data(show_spinner=False)
def procesar_chat(contenido_bytes):
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp:
        tmp.write(contenido_bytes)
        ruta_tmp = Path(tmp.name)
    try:
        alias_regexes = cargar_alias(DEFAULT_ALIASES)
        mensajes = parsear_mensajes(ruta_tmp)
        filas, sin_reconocer, sin_datos = procesar(mensajes, alias_regexes)
        filas, planificado_sin_horas, no_reconocidos_prog, asignaciones = cruzar_con_programacion(
            filas, mensajes, alias_regexes
        )
    finally:
        ruta_tmp.unlink(missing_ok=True)
    return {
        "filas": filas,
        "sin_reconocer": sin_reconocer,
        "sin_datos": sin_datos,
        "planificado_sin_horas": planificado_sin_horas,
        "no_reconocidos_prog": sorted(no_reconocidos_prog),
        "asignaciones": asignaciones,
    }


def a_df_filas(filas):
    cols = [
        "fecha", "proyecto_final", "proyecto_fuente", "tecnico", "horas", "horas_extra",
        "estado_programacion", "equipo_programado", "responsable_equipo", "hora_mensaje",
        "linea", "texto_original",
    ]
    return pd.DataFrame(filas, columns=cols)


def a_df_diag(mensajes_diag):
    filas = [{
        "fecha": m["fecha"].strftime("%Y-%m-%d"),
        "responsable_equipo": m["remitente"],
        "hora_mensaje": m["hora"],
        "linea": m["linea"],
        "texto_original": m["texto"].replace("\n", " | ")[:200],
    } for m in mensajes_diag]
    return pd.DataFrame(filas, columns=["fecha", "responsable_equipo", "hora_mensaje", "linea", "texto_original"])


def a_df_planificacion(lista):
    cols = ["fecha", "equipo", "tecnico", "proyecto", "responsable_equipo", "fecha_mensaje", "hora_mensaje", "linea", "texto_original"]
    return pd.DataFrame(lista, columns=cols)


def descargar(df, etiqueta, nombre_archivo):
    st.download_button(
        etiqueta, df.to_csv(index=False).encode("utf-8-sig"), file_name=nombre_archivo,
        mime="text/csv",
    )


def filtrar(lista, desde, hasta, tecnicos_sel, proyecto_txt, clave_proyecto):
    out = []
    for r in lista:
        fecha = datetime.strptime(r["fecha"], "%Y-%m-%d").date()
        if desde and fecha < desde:
            continue
        if hasta and fecha > hasta:
            continue
        if tecnicos_sel and r["tecnico"] not in tecnicos_sel:
            continue
        if proyecto_txt and proyecto_txt.lower() not in (r.get(clave_proyecto) or "").lower():
            continue
        out.append(r)
    return out


st.title("Horas y programación de operaciones")
st.caption(
    "Sube el chat de WhatsApp exportado (.md) para extraer la tabla de horas, cruzarla con la "
    "programación planificada, y ver las visualizaciones — todo se recalcula con el archivo que subas."
)

archivo = st.file_uploader("Chat de WhatsApp exportado", type=["md", "txt"])

if not archivo:
    st.info("Subí un archivo .md para empezar.")
    st.stop()

with st.spinner("Procesando el chat…"):
    resultado = procesar_chat(archivo.getvalue())

filas_todas = resultado["filas"]
if not filas_todas:
    st.warning("No se encontraron filas de horas en este archivo. Revisá que sea el export correcto.")
    st.stop()

# --- Filtros (sidebar) ---------------------------------------------------
todas_fechas = sorted(datetime.strptime(f["fecha"], "%Y-%m-%d").date() for f in filas_todas)
todos_tecnicos = sorted({f["tecnico"] for f in filas_todas})

st.sidebar.header("Filtros")
rango = st.sidebar.date_input(
    "Rango de fechas", value=(todas_fechas[0], todas_fechas[-1]),
    min_value=todas_fechas[0], max_value=todas_fechas[-1],
)
desde, hasta = (rango if isinstance(rango, tuple) and len(rango) == 2 else (todas_fechas[0], todas_fechas[-1]))
tecnicos_sel = st.sidebar.multiselect("Técnico", options=todos_tecnicos)
proyecto_txt = st.sidebar.text_input("Proyecto contiene…")
if st.sidebar.button("Limpiar filtros"):
    st.rerun()

filas = filtrar(filas_todas, desde, hasta, tecnicos_sel, proyecto_txt, "proyecto_final")
asignaciones = filtrar(resultado["asignaciones"], desde, hasta, tecnicos_sel, proyecto_txt, "proyecto")
planificado_sin_horas = filtrar(resultado["planificado_sin_horas"], desde, hasta, tecnicos_sel, proyecto_txt, "proyecto")

if not filas:
    st.warning("No hay filas de horas con estos filtros. Ajustalos en la barra lateral.")
    st.stop()

df_filas = a_df_filas(filas)
horas_totales = (df_filas["horas"].astype(float) + df_filas["horas_extra"].replace("", 0).astype(float)).sum()
n_tecnicos = df_filas["tecnico"].nunique()
n_imprevisto = (df_filas["estado_programacion"] == "no_programado").sum()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Filas extraídas", len(df_filas))
c2.metric("Técnicos distintos", n_tecnicos)
c3.metric("Horas totales", f"{horas_totales:,.1f}".replace(",", "."))
c4.metric("Filas imprevisto", n_imprevisto)

if resultado["no_reconocidos_prog"]:
    st.warning(
        "Apodos en la programación sin alias registrado (revisar aliases.json): "
        + ", ".join(resultado["no_reconocidos_prog"])
    )

tab_resumen, tab_tecnico, tab_asignacion, tab_plan_real, tab_diag = st.tabs([
    "🗓️ Resumen global", "📊 Horas por técnico", "🧭 Asignación de equipos",
    "🎯 Planificado vs. real", "🩺 Diagnósticos",
])

with tab_resumen:
    st.plotly_chart(heatmap_tecnico_semana(filas), use_container_width=True)
    st.dataframe(df_filas, use_container_width=True, hide_index=True)
    descargar(df_filas, "Descargar tabla_horas.csv", "tabla_horas.csv")

with tab_tecnico:
    st.plotly_chart(horas_por_tecnico(filas), use_container_width=True)
    st.dataframe(df_filas, use_container_width=True, hide_index=True)
    descargar(df_filas, "Descargar tabla_horas.csv", "tabla_horas.csv")

with tab_asignacion:
    st.caption(
        "A diferencia de las otras pestañas, esto viene de tabla_asignaciones (lo planificado en "
        "los mensajes \"PROGRAMACION <día>\"), no de las horas reportadas — por eso cuenta días "
        "asignados, no horas."
    )
    if asignaciones:
        st.plotly_chart(asignacion_tecnico_semana(asignaciones), use_container_width=True)
    else:
        st.info("No hay datos de programación planificada para estos filtros.")
    df_asign = a_df_planificacion(asignaciones)
    st.dataframe(df_asign, use_container_width=True, hide_index=True)
    descargar(df_asign, "Descargar tabla_asignaciones.csv", "tabla_asignaciones.csv")

with tab_plan_real:
    st.plotly_chart(planificado_vs_real_mensual(filas), use_container_width=True)
    st.plotly_chart(planificado_sin_horas_mensual(planificado_sin_horas), use_container_width=True)
    st.caption(
        "El segundo gráfico no es el inverso del primero: cuenta técnico-días planificados sin "
        "ninguna fila de horas ese día, y mezcla ausencias reales con reportes que llegaron solo "
        "por imagen de WhatsApp (no legibles como texto)."
    )
    df_plan = a_df_planificacion(planificado_sin_horas)
    st.dataframe(df_plan, use_container_width=True, hide_index=True)
    descargar(df_plan, "Descargar planificado_sin_horas.csv", "planificado_sin_horas.csv")

with tab_diag:
    st.subheader("Mensajes con horas pero técnico no reconocido")
    df_sr = a_df_diag(resultado["sin_reconocer"])
    st.dataframe(df_sr, use_container_width=True, hide_index=True)
    descargar(df_sr, "Descargar sin_reconocer.csv", "sin_reconocer.csv")

    st.subheader("Mensajes 'Imputación de horas' sin datos en texto (dato solo en imagen)")
    df_sd = a_df_diag(resultado["sin_datos"])
    st.dataframe(df_sd, use_container_width=True, hide_index=True)
    descargar(df_sd, "Descargar sin_datos_imagen.csv", "sin_datos_imagen.csv")
