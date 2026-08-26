"""Figuras Plotly para la app de Streamlit, calculadas a partir de las filas
que produce extraer_horas.py (dinamicas: se recalculan con cada archivo que
suba el usuario, a diferencia de los HTML estaticos publicados como
artefactos)."""
from collections import defaultdict
from datetime import datetime

import plotly.graph_objects as go
from plotly.subplots import make_subplots

ACCENT = "#eb6c36"
MUTED = "#4f5d75"
SOFT = "#7a8399"
INK = "#2d3142"
NEUTRAL = "rgba(45,49,66,0.35)"


def _semana(fecha_str):
    d = datetime.strptime(fecha_str, "%Y-%m-%d")
    y, w, _ = d.isocalendar()
    return y, w


def horas_por_tecnico(filas):
    normal, extra = defaultdict(float), defaultdict(float)
    for f in filas:
        normal[f["tecnico"]] += float(f["horas"] or 0)
        extra[f["tecnico"]] += float(f["horas_extra"] or 0)
    tecnicos = sorted(normal, key=lambda t: -(normal[t] + extra[t]))
    tecnicos = tecnicos[::-1]  # de menor a mayor para que el mas alto quede arriba en barra horizontal

    def etiquetas(valores):
        return [f"{v:g}" if v >= 1 else "" for v in valores]

    fig = go.Figure()
    fig.add_bar(
        y=tecnicos, x=[normal[t] for t in tecnicos], name="Horas normales",
        orientation="h", marker_color="rgba(79,93,117,0.35)",
        marker_line_color=MUTED, marker_line_width=1,
        text=etiquetas([normal[t] for t in tecnicos]), textposition="inside",
        insidetextanchor="middle", textfont=dict(color=INK, size=10),
    )
    fig.add_bar(
        y=tecnicos, x=[extra[t] for t in tecnicos], name="Horas extra",
        orientation="h", marker_color="rgba(235,108,54,0.55)",
        marker_line_color=ACCENT, marker_line_width=1,
        text=etiquetas([extra[t] for t in tecnicos]), textposition="inside",
        insidetextanchor="middle", textfont=dict(color=INK, size=10),
    )
    fig.update_layout(
        barmode="stack",
        title="Horas por técnico (normales + extra)",
        height=max(360, 24 * len(tecnicos) + 120),
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis_title="Horas",
        template="plotly_white",
    )
    return fig


def planificado_vs_real_mensual(filas):
    por_mes = defaultdict(lambda: defaultdict(float))
    for f in filas:
        h = float(f["horas"] or 0) + float(f["horas_extra"] or 0)
        por_mes[f["fecha"][:7]][f["estado_programacion"]] += h
    meses = sorted(por_mes)

    estados = [
        ("programado", "Programado", "rgba(79,93,117,0.35)", MUTED),
        ("no_programado", "Imprevisto (no programado)", "rgba(235,108,54,0.55)", ACCENT),
        ("sin_programacion_dia", "Sin programación registrada", "rgba(45,49,66,0.08)", "rgba(45,49,66,0.4)"),
    ]

    fig = go.Figure()
    for clave, nombre, fill, line in estados:
        fig.add_bar(
            x=meses, y=[por_mes[m].get(clave, 0) for m in meses], name=nombre,
            marker_color=fill, marker_line_color=line, marker_line_width=1,
        )
    fig.update_layout(
        barmode="stack",
        title="Horas planificadas vs. reales, por mes",
        height=440,
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        yaxis_title="Horas",
        template="plotly_white",
    )
    return fig


def planificado_sin_horas_mensual(planificado_sin_horas):
    por_mes = defaultdict(int)
    for p in planificado_sin_horas:
        por_mes[p["fecha"][:7]] += 1
    meses = sorted(por_mes)
    fig = go.Figure()
    fig.add_bar(
        x=meses, y=[por_mes[m] for m in meses],
        marker_color="rgba(45,49,66,0.12)", marker_line_color=SOFT, marker_line_width=1,
    )
    fig.update_layout(
        title="Técnico-días planificados sin ningún reporte de horas, por mes",
        height=320,
        margin=dict(l=10, r=10, t=50, b=10),
        yaxis_title="Técnico-días",
        template="plotly_white",
    )
    return fig


def heatmap_tecnico_semana(filas):
    por_tec_sem = defaultdict(lambda: defaultdict(float))
    por_tec_mes = defaultdict(lambda: defaultdict(float))
    por_tec_total = defaultdict(float)
    for f in filas:
        h = float(f["horas"] or 0) + float(f["horas_extra"] or 0)
        t = f["tecnico"]
        y, w = _semana(f["fecha"])
        por_tec_sem[t][f"{y}-S{w:02d}"] += h
        por_tec_mes[t][f["fecha"][:7]] += h
        por_tec_total[t] += h

    tecnicos = sorted(por_tec_total, key=lambda t: -por_tec_total[t])
    semanas = sorted({k for t in por_tec_sem for k in por_tec_sem[t]})
    meses = sorted({m for t in por_tec_mes for m in por_tec_mes[t]})

    z_sem = [[por_tec_sem[t].get(s, 0) for s in semanas] for t in tecnicos]
    z_mes = [[por_tec_mes[t].get(m, 0) for m in meses] for t in tecnicos]
    text_sem = [[f"{v:g}" if v else "" for v in row] for row in z_sem]
    text_mes = [[f"{v:g}" if v else "" for v in row] for row in z_mes]

    fig = make_subplots(
        rows=1, cols=2, column_widths=[0.82, 0.18], shared_yaxes=True,
        horizontal_spacing=0.02,
        subplot_titles=("Por semana", "Agregado mensual"),
    )
    fig.add_trace(go.Heatmap(
        z=z_sem, x=[s.split("-")[1] for s in semanas], y=tecnicos, text=text_sem,
        texttemplate="%{text}", textfont=dict(size=9),
        colorscale=[[0, "rgba(235,108,54,0.03)"], [1, ACCENT]],
        showscale=False, xgap=2, ygap=2,
        hovertemplate="%{y} · %{x}: %{z:g} h<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Heatmap(
        z=z_mes, x=meses, y=tecnicos, text=text_mes,
        texttemplate="%{text}", textfont=dict(size=9, color=INK),
        colorscale=[[0, "rgba(235,108,54,0.03)"], [1, ACCENT]],
        showscale=False, xgap=2, ygap=2,
        hovertemplate="%{y} · %{x}: %{z:g} h<extra></extra>",
    ), row=1, col=2)

    fig.update_layout(
        title="Horas por técnico y semana, con agregado mensual",
        height=max(420, 26 * len(tecnicos) + 140),
        margin=dict(l=10, r=10, t=70, b=10),
        template="plotly_white",
    )
    fig.update_yaxes(autorange="reversed")
    return fig


def asignacion_proyecto_semana(asignaciones):
    """Igual formato que heatmap_tecnico_semana pero a partir de
    tabla_asignaciones (lo planificado, no lo trabajado), agrupado por
    PROYECTO en vez de tecnico: celda = numero de dias esa semana en los
    que el proyecto tenia algun equipo asignado. Escala de color distinta
    (muted, no accent) para que a simple vista se note que es un dato de
    planificacion, no de horas reales."""
    por_proy_sem = defaultdict(lambda: defaultdict(set))
    por_proy_total = defaultdict(set)
    for a in asignaciones:
        p = (a["proyecto"] or "").strip() or "(sin proyecto)"
        y, w = _semana(a["fecha"])
        por_proy_sem[p][f"{y}-S{w:02d}"].add(a["fecha"])
        por_proy_total[p].add(a["fecha"])

    proyectos = sorted(por_proy_total, key=lambda p: -len(por_proy_total[p]))
    semanas = sorted({k for p in por_proy_sem for k in por_proy_sem[p]})

    z = [[len(por_proy_sem[p].get(s, ())) for s in semanas] for p in proyectos]
    text = [[str(v) if v else "" for v in row] for row in z]

    fig = go.Figure(go.Heatmap(
        z=z, x=[s.split("-")[1] for s in semanas], y=proyectos, text=text,
        texttemplate="%{text}", textfont=dict(size=9),
        colorscale=[[0, "rgba(79,93,117,0.05)"], [1, MUTED]],
        showscale=False, xgap=2, ygap=2,
        hovertemplate="%{y} · %{x}: %{z} día(s) asignado(s)<extra></extra>",
    ))
    fig.update_layout(
        title="Días asignados por proyecto y semana (programación planificada)",
        height=max(420, 20 * len(proyectos) + 140),
        margin=dict(l=10, r=10, t=50, b=10),
        template="plotly_white",
    )
    fig.update_yaxes(autorange="reversed")
    return fig
