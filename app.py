# =============================================================================
# app.py — Agente SECOP II con IA (Versión 2.0)
# Perfil institucional real · Procesamiento paralelo · Caché · Tabs
# =============================================================================
import streamlit as st
import pandas as pd
from datetime import datetime
import backend_ia
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Agente SECOP II — Gestión Contractual IA",
    page_icon="Agent_Principal.png",
    layout="wide",
)

# =============================================================================
# ESTILOS GLOBALES
# =============================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;800&display=swap');
html, body, [class*="css"] { font-family: 'Montserrat', sans-serif !important; }

[data-testid="block-container"] {
    background-color: #FFFFFF;
    border-radius: 20px;
    padding: 36px !important;
    margin-top: 40px !important;
    margin-bottom: 40px !important;
    box-shadow: 0 10px 30px rgba(0, 42, 66, 0.08);
    max-width: 90% !important;
}

[data-testid="stSidebar"] { background-color: #002A42 !important; }
[data-testid="stSidebar"] * { color: #E8F4FD !important; }

.sidebar-menu-active {
    border-left: 4px solid #1DD2C1;
    background-color: rgba(29,210,193,0.10);
    padding: 10px 15px;
    margin-left: -15px;
    font-weight: bold;
    border-radius: 0 8px 8px 0; 
}

[data-testid="stNumberInput"] input {
    color: #0083BF !important; /* Azul Unicafam */
    font-weight: 800 !important;
    font-size: 1.1rem !important;
}

.stButton > button {
    background: linear-gradient(90deg, #1DD2C1 0%, #0083BF 100%) !important;
    color: white !important;
    font-weight: 800 !important;
    border-radius: 30px !important;
    border: none !important;
    padding: 10px 30px !important;
    box-shadow: 0 4px 15px rgba(0, 131, 191, 0.3);
    transition: all 0.3s ease;
}
.stButton > button:hover { transform: scale(1.02); }

.status-pill {
    background-color: #D3F5ED; color: #0F7A6A;
    padding: 6px 15px; border-radius: 20px;
    font-size: 0.85rem; font-weight: bold;
    position: absolute; top: -40px; right: 0;
    display: flex; align-items: center; gap: 8px;
}
.status-dot {
    height: 8px; width: 8px; background-color: #1DD2C1;
    border-radius: 50%; display: inline-block; animation: pulse 2s infinite;
}
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

h1, h2, h3, h4, h5 { color: #002A42 !important; font-weight: 800 !important; }
p { color: #333333; }

[data-testid="stMetric"] {
    background: linear-gradient(135deg, #F0FAFF 0%, #E8F7F5 100%);
    border-radius: 12px;
    padding: 16px !important;
    border-left: 4px solid #1DD2C1;
}

.streamlit-expanderHeader { font-weight: 700 !important; font-size: 0.95rem !important; }

.unspsc-chip {
    display: inline-block; background: #E8F4FD; color: #0083BF;
    border-radius: 20px; padding: 3px 10px; font-size: 0.78rem;
    font-weight: 600; margin-right: 5px;
}
.rup-chip {
    display: inline-block; background: #D3F5ED; color: #0F7A6A;
    border-radius: 20px; padding: 3px 10px; font-size: 0.78rem;
    font-weight: 600; margin-right: 5px;
}
.urgente-chip {
    display: inline-block; background: #FFE5E5; color: #C0392B;
    border-radius: 20px; padding: 3px 10px; font-size: 0.78rem;
    font-weight: 700; margin-right: 5px; animation: pulse 1.5s infinite;
}
.profile-card {
    background: linear-gradient(135deg, #002A42 0%, #004A72 100%);
    color: white !important; border-radius: 14px;
    padding: 20px; margin-bottom: 12px;
}
.profile-card h4 { color: #1DD2C1 !important; font-size: 0.9rem; margin-bottom: 8px; }
.profile-card p  { color: #E0F0FF !important; font-size: 0.82rem; line-height: 1.6; }

.executive-summary {
    background: linear-gradient(135deg, #F8FFFD 0%, #EBF9F6 100%);
    border: 1.5px solid #1DD2C1; border-radius: 14px;
    padding: 22px; margin-top: 16px;
}
</style>
""", unsafe_allow_html=True)


# =============================================================================
# UTILIDADES
# =============================================================================
def semaforo_tiempo(fecha_str: str) -> str:
    if fecha_str in ("Fecha inválida", "Sin fecha definida", ""):
        return "⚪ Fecha no disponible"
    try:
        fecha_cierre   = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M")
        dias_restantes = (fecha_cierre - datetime.now()).days
        if dias_restantes < 0:    return "⚫ Proceso cerrado"
        elif dias_restantes <= 3: return f"🔴 ¡URGENTE! — {dias_restantes} día(s)"
        elif dias_restantes <= 7: return f"🟡 Precaución — {dias_restantes} días"
        else:                     return f"🟢 Buen tiempo — {dias_restantes} días"
    except Exception:
        return "⚪ Error en fecha"


def dias_para_cierre(fecha_str: str) -> int:
    try:
        fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M")
        return (fecha_obj - datetime.now()).days
    except Exception:
        return 9999


def color_viabilidad(v: str) -> str:
    return {"VIABLE": "#1DD2C1", "REQUIERE AJUSTES": "#F4A636", "NO VIABLE": "#E85D5D"}.get(v, "#999")


def icono_viabilidad(v: str) -> str:
    return {"VIABLE": "✅", "REQUIERE AJUSTES": "⚠️", "NO VIABLE": "❌"}.get(v, "❓")


def score_compuesto(r: dict) -> float:
    """Score compuesto para ordenamiento: aplicabilidad + bonus urgencia."""
    pct    = r.get("porcentaje_aplicabilidad", 0)
    dias   = dias_para_cierre(r.get("fecha_cierre", ""))
    bonus  = 20 if 0 <= dias <= 3 else (10 if 0 <= dias <= 7 else 0)
    return pct + bonus


# =============================================================================
# SESSION STATE
# =============================================================================
for key, default in [
    ("resultados_analisis", []),
    ("resumen_ejecutivo", ""),
    ("ids_en_cache", set()),
    ("ultimo_analisis", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# =============================================================================
# ESTADO EN LÍNEA
# =============================================================================
st.markdown("""
<div class="status-pill">
    <span class="status-dot"></span> En línea · IA SECOP II Activo &nbsp;👤
</div>
""", unsafe_allow_html=True)


# =============================================================================
# BARRA LATERAL
# =============================================================================
try:
    st.sidebar.image("Agent_lateral.png", width=150)
except Exception:
    pass

st.sidebar.markdown("<div class='sidebar-menu-active'>⊞ Panel de Gestión Contractual</div>",
                    unsafe_allow_html=True)
st.sidebar.markdown("<br>", unsafe_allow_html=True)

# --- Filtros de resultados ---
st.sidebar.markdown("#### ☷ Filtros de Resultados")
filtro_viabilidad = st.sidebar.multiselect(
    "Veredicto IA:",
    options=["VIABLE", "REQUIERE AJUSTES", "NO VIABLE"],
    default=["VIABLE", "REQUIERE AJUSTES", "NO VIABLE"],
)
filtro_porcentaje = st.sidebar.slider(
    "Aplicabilidad mínima (%):", min_value=0, max_value=100, value=0, step=10
)

st.sidebar.divider()

# --- Búsqueda avanzada ---
st.sidebar.markdown("#### 🔍 Búsqueda Avanzada")

UNSPSC_OPCIONES = {
    "86 — Educación y Formación"                    : "86",
    "80 — Consultoría y Gestión Empresarial"         : "80",
    "81 — Ingeniería, Investigación y Tecnología"    : "81",
    "60 — Materiales y Recursos Educativos"          : "60",
    "45 — Equipos AV y Presentación"                 : "45",
    "82 — Diseño Artístico y Creativos"              : "82",
    "84 — Asistencia para el Desarrollo"             : "84",
    "93 — Desarrollo Social, Urbano y Regional"      : "93",
    "90 — Turismo y Cultura"                         : "90",
    "94 — Organizaciones No Gubernamentales"         : "94",
    "43 — TIC, Software e Infraestructura"           : "43",
    "55 — Publicaciones y Material Educativo"        : "55",
}

unspsc_seleccionados_labels = st.sidebar.multiselect(
    "Categorías UNSPSC:",
    options=list(UNSPSC_OPCIONES.keys()),
    default=list(UNSPSC_OPCIONES.keys()),
    help="Filtra los procesos por categoría antes de enviarlos a la IA.",
)
codigos_unspsc_activos = [UNSPSC_OPCIONES[l] for l in unspsc_seleccionados_labels]
TOTAL_CATEGORIAS = len(UNSPSC_OPCIONES)
unspsc_para_backend = (
    None
    if len(codigos_unspsc_activos) == TOTAL_CATEGORIAS or not codigos_unspsc_activos
    else codigos_unspsc_activos
)

limite_resultados = st.sidebar.number_input(
    "Máximo de ofertas a analizar:", min_value=1, max_value=50, value=10, step=1
)

# Tiempo estimado teniendo en cuenta delay de 4s para API gratuita
tiempo_est_seg = int(limite_resultados) * 4
st.sidebar.caption(
    f"⏱️ Tiempo estimado: **~{tiempo_est_seg}–{tiempo_est_seg + 10} seg** "
    f"para {int(limite_resultados)} oferta(s) con API gratuita (4 s/llamada). "
    "♻️ Las que ya están en caché se saltan el delay."
)

st.sidebar.divider()

# --- Modo API ---
st.sidebar.markdown("#### ⚙️ Configuración de IA")
delay_groq = st.sidebar.slider(
    "Delay entre llamadas Groq (seg):",
    min_value=0.0, max_value=4.0, value=2.0, step=0.5,
    help="Groq gratis: mínimo 2s (30 req/min). En 0 puede dar error 429 si analizas más de 5 ofertas seguidas.",
)
st.sidebar.caption(
    "🆓 **Free tier**: 30 solicitudes/minuto → usa 2–3 s\n"
    "💳 **Paid tier**: puedes bajar a 0 s"
)

st.sidebar.divider()

# --- Diagnóstico ---
st.sidebar.markdown("#### 🔧 Diagnóstico de Conexión")
if st.sidebar.button("🩺 Probar API SECOP II", use_container_width=True):
    with st.sidebar:
        with st.spinner("Probando..."):
            diag = backend_ia.diagnosticar_api()
        if diag["conexion_ok"]:
            st.sidebar.success(f"✅ Conexión OK — {diag['total_sin_filtro']} registros de muestra")
            st.sidebar.caption(f"Estados vistos: {diag['muestra_estados']}")
            st.sidebar.caption(f"IDs: {diag['muestra_ids']}")
        else:
            st.sidebar.error(f"❌ Error: {diag['error']}")

st.sidebar.divider()

# --- Caché ---
st.sidebar.markdown("#### ♻️ Caché de Análisis")
n_cache = len(backend_ia._cache_analisis)
st.sidebar.caption(f"Procesos en caché esta sesión: **{n_cache}**")
if st.sidebar.button("🗑️ Limpiar caché", use_container_width=True):
    backend_ia.limpiar_cache()
    st.session_state.resultados_analisis = []
    st.session_state.resumen_ejecutivo   = ""
    st.session_state.ultimo_analisis     = None
    st.rerun()

st.sidebar.divider()


# =============================================================================
# TABS PRINCIPALES
# =============================================================================
tab_analisis, tab_dashboard, tab_perfil = st.tabs([
    "🔎 Análisis SECOP II",
    "📊 Dashboard",
    "🏛️ Perfil Institucional",
])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1: ANÁLISIS
# ─────────────────────────────────────────────────────────────────────────────
with tab_analisis:

    _, col_centro, _ = st.columns([1, 4, 1])

    with col_centro:
        _, col_logo, _ = st.columns([1.5, 2, 1.5])
        with col_logo:
            try:
                st.image("Agent_Principal.png", use_container_width=True)
            except Exception:
                st.warning("⚠️ No se encontró 'Agent_Principal.png'.")

        st.markdown(
            "<h3 style='text-align:center;'>Agente IA de Contratación SECOP II</h3>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='text-align:center;'>Supervisión inteligente de oportunidades contractuales.<br>"
            "Análisis en paralelo · Perfil real acreditado · Caché por sesión.</p><br>",
            unsafe_allow_html=True,
        )

        palabra_busqueda = st.text_input(
            "Búsqueda por palabra clave (opcional):",
            placeholder="Ej: Educación virtual, Consultoría TIC, Plataforma e-learning...",
        )

        col_solo_viables = st.columns(1)[0]
        solo_urgentes = st.checkbox(
            "🔴 Mostrar primero los que cierran en ≤7 días",
            value=False,
            help="Al activar, el análisis priorizará automáticamente los más urgentes.",
        )

        st.markdown("<br>", unsafe_allow_html=True)
        _, col_btn, _ = st.columns([1, 2, 1])
        with col_btn:
            btn_analizar = st.button(
                "🔎 Iniciar análisis inteligente",
                type="primary",
                use_container_width=True,
            )

    # --- LÓGICA DE BÚSQUEDA Y ANÁLISIS ---
    if btn_analizar:
        st.session_state.resultados_analisis = []
        st.session_state.resumen_ejecutivo   = ""

        with st.spinner("Consultando SECOP II — descargando y aplicando pre-filtros..."):
            ofertas_filtradas = backend_ia.obtener_ofertas_secop(
                limite=int(limite_resultados),
                palabra_clave=palabra_busqueda or None,
                codigos_unspsc=unspsc_para_backend,
            )

        if not ofertas_filtradas:
            st.error(
                "⚠️ No se encontraron ofertas relevantes. **Posibles causas:**\n\n"
                "- El TOKEN de Socrata puede estar inválido o vencido.\n"
                "- El dataset no tiene registros recientes con esas categorías.\n"
                "- Prueba el botón **🩺 Probar API SECOP II** en el panel lateral para diagnosticar.\n"
                "- Amplía las categorías UNSPSC o deja la palabra clave vacía."
            )
        else:
            total = len(ofertas_filtradas)
            en_cache  = sum(1 for o in ofertas_filtradas
                            if o.get("id_del_proceso") in backend_ia._cache_analisis)
            a_analizar = total - en_cache
            tiempo_est = a_analizar * delay_groq

            st.info(
                f"✅ **{total} oferta(s)** pasaron el pre-filtro. "
                f"♻️ **{en_cache}** en caché · 🧠 **{a_analizar}** nuevas "
                f"(tiempo estimado: ~{int(tiempo_est)}–{int(tiempo_est) + 10} seg con API gratuita)."
            )

            barra      = st.progress(0, text="Iniciando análisis con Groq...")
            status_txt = st.empty()

            def actualizar_progreso(completados, total_t, id_proc, desde_cache):
                pct = completados / total_t if total_t > 0 else 0
                origen = "⚡ caché" if desde_cache else "🧠 IA Groq"
                msg = f"[{completados}/{total_t}] {origen} → {id_proc}"
                barra.progress(pct, text=msg)
                status_txt.caption(msg)

            resultados_nuevos = backend_ia.analizar_ofertas_secuencial(
                ofertas=ofertas_filtradas,
                delay_segundos=float(delay_groq),
                callback_progreso=actualizar_progreso,
            )

            st.session_state.resultados_analisis = resultados_nuevos
            st.session_state.ultimo_analisis = datetime.now().strftime("%Y-%m-%d %H:%M")
            barra.empty()
            status_txt.empty()
            st.success(
                f"🎉 Análisis completado — **{len(resultados_nuevos)} oferta(s) evaluadas**. "
                f"💾 Guardadas en caché para el resto de la sesión."
            )

            # Resumen ejecutivo IA
            if len(resultados_nuevos) >= 2:
                with st.spinner("Generando resumen ejecutivo estratégico..."):
                    st.session_state.resumen_ejecutivo = backend_ia.generar_resumen_ejecutivo(
                        resultados_nuevos
                    )

    # --- SECCIÓN DE RESULTADOS ---
    if st.session_state.resultados_analisis:
        st.divider()

        # Filtros laterales sobre resultados
        resultados_visibles = [
            r for r in st.session_state.resultados_analisis
            if r.get("viabilidad", "NO VIABLE") in filtro_viabilidad
            and r.get("porcentaje_aplicabilidad", 0) >= filtro_porcentaje
        ]

        if not resultados_visibles:
            st.warning("⚠️ Ningún resultado coincide con los filtros laterales actuales.")
        else:
            total_vis = len(resultados_visibles)
            viables   = sum(1 for r in resultados_visibles if r.get("viabilidad") == "VIABLE")
            ajustes   = sum(1 for r in resultados_visibles if r.get("viabilidad") == "REQUIERE AJUSTES")
            promedio  = int(sum(r.get("porcentaje_aplicabilidad", 0) for r in resultados_visibles) / total_vis)
            urgentes  = sum(1 for r in resultados_visibles if 0 <= dias_para_cierre(r.get("fecha_cierre","")) <= 7)

            # --- Métricas resumen ---
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("📊 Analizadas",      total_vis)
            c2.metric("✅ Viables",          viables)
            c3.metric("⚠️ Con Ajustes",     ajustes)
            c4.metric("📈 Aplicabilidad",   f"{promedio}%")
            c5.metric("🔴 Urgentes (≤7d)",  urgentes)

            # --- Resumen Ejecutivo IA ---
            if st.session_state.resumen_ejecutivo:
                st.markdown("<div class='executive-summary'>", unsafe_allow_html=True)
                st.markdown("#### 🧠 Resumen Ejecutivo Estratégico")
                st.markdown(st.session_state.resumen_ejecutivo)
                if st.session_state.ultimo_analisis:
                    st.caption(f"Generado: {st.session_state.ultimo_analisis}")
                st.markdown("</div>", unsafe_allow_html=True)

            # --- Botón Exportar ---
            st.markdown("<br>", unsafe_allow_html=True)
            col_exp1, col_exp2, _ = st.columns([1, 2, 3])
            with col_exp2:
                excel_bytes = backend_ia.exportar_reporte_excel(resultados_visibles)
                if excel_bytes:
                    nombre_archivo = f"reporte_viabilidad_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                    st.download_button(
                        label="📥 Exportar Reporte Excel (2 hojas)",
                        data=excel_bytes,
                        file_name=nombre_archivo,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )

            st.divider()

            # --- Alertas urgentes ---
            urgentes_lista = [
                r for r in resultados_visibles
                if 0 <= dias_para_cierre(r.get("fecha_cierre","")) <= 7
                and r.get("viabilidad") in ("VIABLE", "REQUIERE AJUSTES")
            ]
            if urgentes_lista:
                st.markdown("### 🔴 Procesos Urgentes — Cierran en ≤ 7 días")
                for r in sorted(urgentes_lista, key=lambda x: dias_para_cierre(x.get("fecha_cierre",""))):
                    dias = dias_para_cierre(r.get("fecha_cierre",""))
                    st.markdown(
                        f"<span class='urgente-chip'>🔴 {dias} días</span> "
                        f"**{r.get('id_oferta','')}** — {r.get('entidad','')} · "
                        f"_{r.get('objeto_contrato','')}_",
                        unsafe_allow_html=True,
                    )
                st.divider()

            # --- Listado completo ---
            st.subheader("📋 Detalle del Análisis por Proceso")

            # Ordenamiento: score compuesto (aplicabilidad + urgencia), VIABLE primero
            orden_viab = {"VIABLE": 0, "REQUIERE AJUSTES": 1, "NO VIABLE": 2}
            resultados_ord = sorted(
                resultados_visibles,
                key=lambda r: (
                    orden_viab.get(r.get("viabilidad", "NO VIABLE"), 3),
                    -score_compuesto(r),
                ),
            )

            for oferta in resultados_ord:
                viabilidad  = oferta.get("viabilidad", "DESCONOCIDO")
                porcentaje  = oferta.get("porcentaje_aplicabilidad", 0)
                score_fin   = oferta.get("score_financiero", 0)
                icono       = icono_viabilidad(viabilidad)
                color       = color_viabilidad(viabilidad)
                entidad     = oferta.get("entidad", "Sin entidad")
                objeto      = oferta.get("objeto_contrato", oferta.get("id_oferta", ""))
                categoria   = oferta.get("categoria_unspsc", "")
                codigo_u    = oferta.get("codigo_unspsc", "")
                competencia = oferta.get("nivel_competencia", "")
                duracion_c  = oferta.get("duracion_contrato", "")
                match_rup   = oferta.get("match_unspsc_rup", False)
                dias_cierre = dias_para_cierre(oferta.get("fecha_cierre", ""))

                icono_comp   = {"BAJO": "🟢", "MEDIO": "🟡", "ALTO": "🔴"}.get(competencia, "⚪")
                urgente_badge = " 🔴" if 0 <= dias_cierre <= 7 else ""
                rup_badge     = " ⭐RUP" if match_rup else ""

                etiqueta = (
                    f"{icono} {oferta.get('id_oferta', 'Sin ID')} — "
                    f"{entidad[:40]} · {porcentaje}% aplicable{urgente_badge}{rup_badge}"
                )

                with st.expander(etiqueta, expanded=(viabilidad == "VIABLE" and dias_cierre <= 7)):

                    # Chips de estado
                    chips = f"<span class='unspsc-chip'>UNSPSC {codigo_u} · {categoria}</span>"
                    if match_rup:
                        chips += "<span class='rup-chip'>⭐ Código RUP exacto</span>"
                    if 0 <= dias_cierre <= 7:
                        chips += f"<span class='urgente-chip'>🔴 Cierra en {dias_cierre} día(s)</span>"

                    st.markdown(f"**📌 Objeto:** {objeto} &nbsp;&nbsp;{chips}", unsafe_allow_html=True)

                    # Metadatos clave
                    col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
                    col_m1.markdown(f"**Modalidad**\n\n`{oferta.get('modalidad', 'N/D')}`")
                    col_m2.markdown(f"**Valor estimado**\n\n`${oferta.get('valor_estimado', 'N/D')} COP`")
                    col_m3.markdown(f"**Duración**\n\n`{duracion_c or 'N/D'}`")
                    col_m4.markdown(f"**Competencia**\n\n{icono_comp} `{competencia or 'N/D'}`")
                    col_m5.markdown(f"**Score Financiero**\n\n`{score_fin}/100`")
                    st.markdown("---")

                    col_izq, col_der = st.columns([3, 1])

                    with col_izq:
                        st.markdown(
                            f"**Veredicto IA:** <span style='color:{color}; font-weight:800;'>{viabilidad}</span>",
                            unsafe_allow_html=True,
                        )
                        st.progress(porcentaje / 100.0)
                        st.markdown(f"*{porcentaje}% de aplicabilidad institucional*")
                        st.markdown("<br>", unsafe_allow_html=True)
                        st.info(f"**💡 Recomendación estratégica:** {oferta.get('recomendacion', '')}")

                        tab_f, tab_r, tab_a = st.tabs(["💪 Fortalezas", "⚠️ Riesgos", "🛠️ Acciones de Mejora"])

                        with tab_f:
                            fortalezas = oferta.get("fortalezas", [])
                            if fortalezas:
                                for f in fortalezas:
                                    st.markdown(f"- ✅ {f}")
                            else:
                                st.caption("Sin fortalezas identificadas.")

                        with tab_r:
                            riesgos = oferta.get("riesgos", [])
                            if riesgos:
                                for r in riesgos:
                                    st.markdown(f"- 🔺 {r}")
                            else:
                                st.caption("Sin riesgos identificados.")

                        with tab_a:
                            acciones = oferta.get("acciones_mejora", [])
                            if acciones:
                                for a in acciones:
                                    st.markdown(f"- 🛠️ {a}")
                            else:
                                st.caption("Sin acciones de mejora recomendadas.")

                    with col_der:
                        st.markdown("**⏰ Tiempo para cierre:**")
                        st.markdown(f"*{semaforo_tiempo(oferta.get('fecha_cierre', ''))}*")
                        st.markdown(f"📅 `{oferta.get('fecha_cierre', 'Sin fecha')}`")
                        st.markdown("<br>", unsafe_allow_html=True)
                        enlace = oferta.get("enlace_secop", "#")
                        if enlace and enlace not in ("#", "Sin enlace"):
                            st.link_button("🌐 Ver en SECOP II", enlace, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2: DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
with tab_dashboard:
    st.markdown("### 📊 Dashboard de Gestión Contractual")

    resultados = st.session_state.resultados_analisis

    if not resultados:
        st.info("💡 Ejecuta un análisis en la pestaña **🔎 Análisis SECOP II** para ver el dashboard.")
    else:
        total_r = len(resultados)
        viables_r = sum(1 for r in resultados if r.get("viabilidad") == "VIABLE")
        ajustes_r = sum(1 for r in resultados if r.get("viabilidad") == "REQUIERE AJUSTES")
        noviabl_r = total_r - viables_r - ajustes_r
        prom_pct  = int(sum(r.get("porcentaje_aplicabilidad", 0) for r in resultados) / total_r)
        urg_r     = sum(1 for r in resultados if 0 <= dias_para_cierre(r.get("fecha_cierre","")) <= 7)
        rup_exact = sum(1 for r in resultados if r.get("match_unspsc_rup"))

        # KPIs
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("📂 Total Analizadas",    total_r)
        c2.metric("✅ Viables",             viables_r)
        c3.metric("⚠️ Con Ajustes",        ajustes_r)
        c4.metric("❌ No Viables",         noviabl_r)
        c5.metric("📈 Aplicabilidad Prom.", f"{prom_pct}%")
        c6.metric("⭐ Match RUP Exacto",   rup_exact)

        st.divider()

        # --- Distribución de viabilidad ---
        col_chart1, col_chart2 = st.columns(2)

        with col_chart1:
            st.markdown("#### Distribución de Viabilidad")
            df_viab = pd.DataFrame({
                "Viabilidad": ["VIABLE", "REQUIERE AJUSTES", "NO VIABLE"],
                "Cantidad"  : [viables_r, ajustes_r, noviabl_r],
            })
            st.bar_chart(df_viab.set_index("Viabilidad"), color="#1DD2C1")

        with col_chart2:
            st.markdown("#### Aplicabilidad por Proceso (Top 15)")
            df_top = pd.DataFrame([
                {
                    "Proceso"       : f"{r.get('id_oferta','?')[:12]}…",
                    "Aplicabilidad" : r.get("porcentaje_aplicabilidad", 0),
                }
                for r in sorted(resultados, key=lambda x: x.get("porcentaje_aplicabilidad", 0), reverse=True)[:15]
            ])
            st.bar_chart(df_top.set_index("Proceso"), color="#0083BF")

        st.divider()

        # --- Tabla consolidada ---
        st.markdown("#### 📋 Tabla Consolidada de Resultados")
        df_tabla = pd.DataFrame([
            {
                "ID"            : r.get("id_oferta", ""),
                "Entidad"       : r.get("entidad", "")[:40],
                "Viabilidad"    : r.get("viabilidad", ""),
                "Aplicabilidad" : f"{r.get('porcentaje_aplicabilidad', 0)}%",
                "Score Fin."    : r.get("score_financiero", 0),
                "Competencia"   : r.get("nivel_competencia", ""),
                "Cierre"        : r.get("fecha_cierre", ""),
                "Match RUP"     : "⭐ Sí" if r.get("match_unspsc_rup") else "No",
                "Valor (COP)"   : r.get("valor_estimado", ""),
            }
            for r in sorted(resultados, key=lambda x: x.get("porcentaje_aplicabilidad", 0), reverse=True)
        ])
        st.dataframe(df_tabla, use_container_width=True, hide_index=True)

        # Export desde dashboard
        excel_dash = backend_ia.exportar_reporte_excel(resultados)
        if excel_dash:
            st.download_button(
                label="📥 Descargar Excel Completo",
                data=excel_dash,
                file_name=f"dashboard_contractual_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3: PERFIL INSTITUCIONAL
# ─────────────────────────────────────────────────────────────────────────────
with tab_perfil:
    st.markdown("### 🏛️ Perfil Institucional Acreditado")
    st.caption(
        "Datos basados en documentos institucionales y RUP — corte 31/12/2024. "
        "Este perfil alimenta el motor de análisis IA y determina la viabilidad de cada proceso."
    )

    col_p1, col_p2 = st.columns(2)

    with col_p1:
        st.markdown("<div class='profile-card'><h4>📋 Datos Generales</h4><p>"
                    "• Trayectoria: <b>17+ años</b> (constitución 2008)<br>"
                    "• Proponente RUP vigente desde: <b>2016</b><br>"
                    "• Contratos ejecutados: <b>+50</b><br>"
                    "• Cobertura: <b>Nacional</b><br>"
                    "• Participación en consorcios y U. Temporales: <b>Sí</b>"
                    "</p></div>", unsafe_allow_html=True)

        st.markdown("<div class='profile-card'><h4>💰 Indicadores Financieros (RUP 2024)</h4><p>"
                    "• Índice de Liquidez: <b>1.36</b> — Aceptable<br>"
                    "• Índice de Endeudamiento: <b>0.59</b> — Aceptable (límite 0.60)<br>"
                    "• Razón Ácida: No reportada explícitamente<br>"
                    "• Estado financiero: <b>Vigente — sin alertas críticas</b>"
                    "</p></div>", unsafe_allow_html=True)

    with col_p2:
        st.markdown("<div class='profile-card'><h4>🎯 Áreas de Alta Competencia</h4><p>"
                    "• Educación superior y politécnicos (86121700)<br>"
                    "• E-learning y aprendizaje a distancia (86111500)<br>"
                    "• Capacitación vocacional científica/no científica<br>"
                    "• Consultoría de negocios y gerencia de proyectos<br>"
                    "• Ingeniería de software y metodología de sistemas<br>"
                    "• Desarrollo de recursos humanos y formación docente<br>"
                    "• Materiales y recursos educativos digitales"
                    "</p></div>", unsafe_allow_html=True)

        st.markdown("<div class='profile-card'><h4>🚫 Fuera del Perfil (Rechazo automático)</h4><p>"
                    "• Construcción civil y obras de infraestructura<br>"
                    "• Suministro de alimentos y bienes físicos<br>"
                    "• Aseo, limpieza y mantenimiento<br>"
                    "• Vigilancia y seguridad física<br>"
                    "• Transporte y manufactura"
                    "</p></div>", unsafe_allow_html=True)

    st.divider()
    st.markdown("#### 🗂️ Códigos UNSPSC Acreditados en RUP (35 códigos)")

    UNSPSC_TABLE = {
        "45111800": "Equipos de presentación de video y sonido",
        "60101100": "Materiales educativos (general)",
        "60105200": "Materiales de aprendizaje interactivo",
        "60105300": "Materiales educativos de ciencias",
        "60105400": "Materiales educativos de arte",
        "60105600": "Materiales educativos de tecnología",
        "80101500": "Consultoría de negocios y administración corporativa",
        "80101600": "Gerencia de proyectos",
        "80101700": "Gerencia industrial",
        "80111500": "Desarrollo de recursos humanos",
        "80141500": "Investigación de mercados",
        "80141600": "Ventas y promoción de negocios",
        "80141900": "Asistencia técnica organizacional",
        "81111500": "Ingeniería de software",
        "81131500": "Metodología y análisis de sistemas",
        "81161500": "Administración de accesos y seguridad lógica",
        "82141500": "Servicios de diseño artístico",
        "84101500": "Asistencia para el desarrollo",
        "86101500": "Capacitación vocacional científica",
        "86101700": "Capacitación vocacional no científica",
        "86101800": "Educación y formación especializada",
        "86111500": "Aprendizaje a distancia",
        "86111600": "Educación de adultos",
        "86121700": "Universidades y politécnicos",
        "86132000": "Educación y capacitación en administración",
        "86141500": "Servicios de guía educacional",
        "86141700": "Tecnología educacional",
        "90121500": "Actividades turísticas",
        "90151800": "Eventos culturales",
        "93141500": "Desarrollo social",
        "93141600": "Desarrollo poblacional",
        "93141700": "Desarrollo cultural",
        "93142000": "Desarrollo urbano",
        "93142100": "Desarrollo regional",
        "94131500": "Organizaciones no gubernamentales",
    }

    df_unspsc = pd.DataFrame(
        [{"Código UNSPSC": k, "Descripción": v} for k, v in UNSPSC_TABLE.items()]
    )
    st.dataframe(df_unspsc, use_container_width=True, hide_index=True, height=500)

    st.caption(
        "⭐ Cuando un proceso de SECOP II coincide exactamente con uno de estos códigos, "
        "el motor IA le asigna un bonus de +15 puntos en el porcentaje de aplicabilidad "
        "y lo marca como **Match RUP Exacto**."
    )