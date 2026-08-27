# Operaciones · Horas y Programación

A partir del chat de WhatsApp exportado por el equipo de operaciones (técnicos de
instalación solar/eléctrica), esta herramienta extrae y estructura:

- **Horas trabajadas** por técnico, día y proyecto (a partir de los mensajes de
  "Imputación de horas" / "Reporte de horas").
- **Programación planificada** por equipo, día y proyecto (a partir de los mensajes
  "PROGRAMACIÓN \<día\>").
- El cruce entre ambas: qué se trabajó realmente frente a lo planificado, e
  imprevistos (horas reportadas por técnicos que no estaban programados ese día).

No hay base de datos: todo se recalcula bajo demanda a partir del export de chat
(`.md`), tanto en el script de línea de comandos como en la app.

## App de Streamlit

```
streamlit run app.py
```

El usuario sube el `.md` exportado desde la propia app (`st.file_uploader`), y esta
recalcula tablas y gráficos en el momento — no necesita ningún archivo de datos
presente en el repo ni en el servidor.

La app está pensada para desplegarse en Streamlit Community Cloud apuntando a
`app.py`.

## Uso por línea de comandos

Alternativa a la app: genera los CSV directamente en disco, con filtros.

```
python extraer_horas.py
python extraer_horas.py --desde 01/03/2026 --hasta 31/03/2026
python extraer_horas.py --tecnico Guillermo --proyecto Octopus
python extraer_horas.py --output tabla_marzo.csv --desde 01/03/2026 --hasta 31/03/2026
python extraer_horas.py --sin-diagnosticos   # omite los CSV de diagnóstico
```

Solo requiere el export de WhatsApp en `chat_ws_operaciones_2026.md` (mismo
directorio, o indicado con `--input`). No necesita las dependencias de
`requirements.txt` (son solo para la app) — usa únicamente la librería estándar de
Python.

## Instalación (para la app)

```
pip install -r requirements.txt
```

Requiere `streamlit`, `plotly` y `pandas`.

## Estructura del código

```
chat_ws_operaciones_2026.md   (no versionado — ver "Archivos no versionados")
        │
        ▼
  chat_utils.py   — parsea el export en mensajes; reconoce técnicos vía
                     aliases.json
        │
        ├──▶ extraer_horas.py   — extrae filas de horas por técnico/día/proyecto.
        │                          Punto de entrada del CLI (tabla_horas.csv).
        │
        └──▶ asignaciones.py    — extrae la programación planificada por equipo
                                   (tabla_asignaciones.csv).

extraer_horas.py cruza sus propias filas con la programación de asignaciones.py
para marcar cada hora reportada como programada / imprevisto, y para inferir el
proyecto cuando no viene explícito en el reporte de horas.
```

- **`app.py`** — interfaz Streamlit (filtros, tablas, gráficos, descargas).
- **`graficos.py`** — figuras Plotly usadas por la app.
- **`aliases.json`** — diccionario editable de apodo → nombre canónico de técnico.
  Se autogenera la primera vez si no existe. Es el único archivo generado que se
  mantiene a mano (no se sobrescribe si ya existe).

Para más detalle sobre las heurísticas de extracción (formatos de mensaje,
resolución de fechas, etc.), ver [`CLAUDE.md`](CLAUDE.md).

## Archivos no versionados

Este repo usa `.gitignore` para excluir datos y salidas generadas, porque
contienen información interna y se recalculan en cada ejecución:

- `chat_ws_operaciones_2026.md` (el export de chat en sí)
- `*.csv` (`tabla_horas.csv`, `tabla_asignaciones.csv`, `sin_reconocer.csv`,
  `sin_datos_imagen.csv`, `planificado_sin_horas.csv`)
- `streamlit.log`, `__pycache__/`, `.streamlit/secrets.toml`

Si clonas este repo en otro equipo y quieres trabajar con el CLI
(`extraer_horas.py`), necesitas copiar `chat_ws_operaciones_2026.md` aparte — git
no lo trae porque nunca se subió. La app de Streamlit no tiene este problema: el
archivo se sube desde el navegador en cada sesión.

## Notas

La extracción es heurística, no exacta: el chat no tiene un formato fijo (lo
escriben ~15 personas distintas). Cuando algo se ve mal contado, conviene revisar
antes los CSV de diagnóstico (`sin_reconocer.csv`, `sin_datos_imagen.csv`,
`planificado_sin_horas.csv`) — suele ser un alias que falta en `aliases.json` o un
reporte que llegó solo como imagen, no un bug de parsing.
