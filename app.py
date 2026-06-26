# =============================================================================
# app.py — Agente SECOP II con IA (Versión 3.0)
# Mejoras: state management robusto, UX mejorada, código más limpio,
# manejo de errores defensivo, separación clara de responsabilidades
# =============================================================================
from __future__ import annotations

import streamlit as st
import pandas as pd
from datetime import datetime
import backend_ia

# =============================================================================
# CONFIGURACIÓN DE PÁGINA — debe ser el primer comando Streamlit
# =============================================================================
st.set_page_config(
    page_title="Agente SECOP II — Gestión Contractual IA",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =============================================================================
# ESTILOS GLOBALES
# =============================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Montserrat', sans-serif !important;
}

/* Contenedor principal */
[data-testid="block-container"] {
    background-color: #FFFFFF;
    border-radius: 20px;
    padding: 32px !important;
    margin-top: 32px !important;
    margin-bottom: 32px !important;
    box-shadow: 0 8px 24px rgba(0, 42, 66, 0.07);
    max-width: 92% !important;
}

/* Sidebar */
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

/* Inputs */
[data-testid="stNumberInput"] input {
    color: #0083BF !important;
    font-weight: 800 !important;
    font-size: 1.1rem !important;
}

/* Botones */
.stButton > button {
    background: linear-gradient(90deg, #1DD2C1 0%, #0083BF 100%) !important;
    color: white !important;
    font-weight: 800 !important;
    border-radius: 30px !important;
    border: none !important;
    padding: 10px 30px !important;
    box-shadow: 0 4px 15px rgba(0, 131, 191, 0.25);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(0, 131, 191, 0.35);
}
.stButton > button:active { transform: translateY(0); }

/* Pill de estado en línea */
.status-pill {
    background-color: #D3F5ED;
    color: #0F7A6A;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 0.82rem;
    font-weight: bold;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
}
.status-dot {
    height: 8px;
    width: 8px;
    background-color: #1DD2C1;
    border-radius: 50%;
    display: inline-block;
    animation: pulse 2s infinite;
}
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

/* Tipografía */
h1, h2, h3, h4, h5 { color: #002A42 !important; font-weight: 800 !important; }
p { color: #333333; }

/* Métricas */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #F0FAFF 0%, #E8F7F5 100%);
    border-radius: 12px;
    padding: 16px !important;
    border-left: 4px solid #1DD2C1;
}

/* Expanders */
.streamlit-expanderHeader { font-weight: 700 !important; font-size: 0.95rem !important; }

/* Chips */
.unspsc-chip {
    display: inline-block; background: #E8F4FD; color: #0083BF;
    border-radius: 20px; padding: 3px 10px; font-size: 0.78rem;
    font-weight: 600; margin-right: 5px; margin-bottom: 4px;
}
.rup-chip {
    display: inline-block; background: #D3F5ED; color: #0F7A6A;
    border-radius: 20px; padding: 3px 10px; font-size: 0.78rem;
    font-weight: 600; margin-right: 5px; margin-bottom: 4px;
}
.urgente-chip {
    display: inline-block; background: #FFE5E5; color: #C0392B;
    border-radius: 20px; padding: 3px 10px; font-size: 0.78rem;
    font-weight: 700; margin-right: 5px; margin-bottom: 4px;
    animation: pulse 1.5s infinite;
}

/* Cards del perfil */
.profile-card {
    background: linear-gradient(135deg, #002A42 0%, #004A72 100%);
    color: white !important;
    border-radius: 14px;
    padding: 20px;
    margin-bottom: 12px;
}
.profile-card h4 { color: #1DD2C1 !important; font-size: 0.9rem; margin-bottom: 8px; }
.profile-card p  { color: #E0F0FF !important; font-size: 0.82rem; line-height: 1.6; }

/* Resumen ejecutivo */
.executive-summary {
    background: linear-gradient(135deg, #F8FFFD 0%, #EBF9F6 100%);
    border: 1.5px solid #1DD2C1;
    border-radius: 14px;
    padding: 22px;
    margin-top: 16px;
}

/* Separador de sección */
.section-divider {
    border-top: 2px solid #E8F4FD;
    margin: 24px 0;
}
</style>
""", unsafe_allow_html=True)


# =============================================================================
# UTILIDADES — Funciones puras sin efectos secundarios en UI
# =============================================================================
def semaforo_tiempo(fecha_str: str) -> str:
    """Retorna un emoji + texto según los días restantes para el cierre."""
    if not fecha_str or fecha_str in ("Fecha inválida", "Sin fecha definida"):
        return "⚪ Fecha no disponible"
    try:
        dias = (datetime.strptime(fecha_str, "%Y-%m-%d %H:%M") - datetime.now()).days
        if dias < 0:    return "⚫ Proceso cerrado"
        if dias <= 3:   return f"🔴 ¡URGENTE! — {dias} día(s)"
        if dias <= 7:   return f"🟡 Precaución — {dias} días"
        return f"🟢 Buen tiempo — {dias} días"
    except (ValueError, TypeError):
        return "⚪ Error en fecha"


def dias_para_cierre(fecha_str: str) -> int:
    """Retorna días enteros para el cierre. 9999 si la fecha no es válida."""
    try:
        return (datetime.strptime(fecha_str, "%Y-%m-%d %H:%M") - datetime.now()).days
    except (ValueError, TypeError):
        return 9999


def color_viabilidad(v: str) -> str:
    return {"VIABLE": "#1DD2C1", "REQUIERE AJUSTES": "#F4A636", "NO VIABLE": "#E85D5D"}.get(v, "#999")


def icono_viabilidad(v: str) -> str:
    return {"VIABLE": "✅", "REQUIERE AJUSTES": "⚠️", "NO VIABLE": "❌"}.get(v, "❓")


def score_compuesto(r: dict) -> float:
    """Score de ordenamiento UI: aplicabilidad + bonus por urgencia."""
    pct  = r.get("porcentaje_aplicabilidad", 0)
    dias = dias_para_cierre(r.get("fecha_cierre", ""))
    if 0 <= dias <= 3:  return pct + 20
    if 0 <= dias <= 7:  return pct + 10
    return float(pct)


def formatear_cuantia(valor: str) -> str:
    """Formatea un valor numérico como moneda COP o devuelve el string original."""
    try:
        return f"${float(valor):,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return str(valor) if valor else "No especificado"


# =============================================================================
# INICIALIZACIÓN DE SESSION STATE
# =============================================================================
_ESTADO_INICIAL: dict = {
    "resultados_analisis": [],
    "resumen_ejecutivo"  : "",
    "ultimo_analisis"    : None,
    "analisis_en_curso"  : False,
}
for clave, valor_default in _ESTADO_INICIAL.items():
    if clave not in st.session_state:
        st.session_state[clave] = valor_default


# =============================================================================
# SIDEBAR
# =============================================================================
with st.sidebar:
    # Logo
    try:
        st.image("Agent_lateral.png", width=150)
    except Exception:
        st.markdown("### 🔎 SECOP IA")

    st.markdown("<div class='sidebar-menu-active'>⊞ Panel de Gestión Contractual</div>",
                unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Filtros de resultados ─────────────────────────────────────────────────
    st.markdown("#### ☷ Filtros de Resultados")
    filtro_viabilidad = st.multiselect(
        "Veredicto IA:",
        options=["VIABLE", "REQUIERE AJUSTES", "NO VIABLE"],
        default=["VIABLE", "REQUIERE AJUSTES", "NO VIABLE"],
    )
    filtro_porcentaje = st.slider(
        "Aplicabilidad mínima (%):", min_value=0, max_value=100, value=0, step=10
    )

    st.divider()

    # ── Búsqueda avanzada ─────────────────────────────────────────────────────
    st.markdown("#### 🔍 Búsqueda Avanzada")

    UNSPSC_OPCIONES: dict[str, str] = {
        "86 — Educación y Formación"                : "86",
        "80 — Consultoría y Gestión Empresarial"    : "80",
        "81 — Ingeniería, Investigación y Tecnología": "81",
        "60 — Materiales y Recursos Educativos"     : "60",
        "45 — Equipos AV y Presentación"            : "45",
        "82 — Diseño Artístico y Creativos"         : "82",
        "84 — Asistencia para el Desarrollo"        : "84",
        "93 — Desarrollo Social, Urbano y Regional" : "93",
        "90 — Turismo y Cultura"                    : "90",
        "94 — Organizaciones No Gubernamentales"    : "94",
        "43 — TIC, Software e Infraestructura"      : "43",
        "55 — Publicaciones y Material Educativo"   : "55",
    }

    unspsc_labels = st.multiselect(
        "Categorías UNSPSC:",
        options=list(UNSPSC_OPCIONES.keys()),
        default=list(UNSPSC_OPCIONES.keys()),
        help="Filtra procesos por categoría antes de enviarlos a la IA.",
    )
    codigos_activos = [UNSPSC_OPCIONES[l] for l in unspsc_labels]
    # Si están todas → no filtrar en backend (más eficiente)
    unspsc_para_backend = (
        None
        if len(codigos_activos) == len(UNSPSC_OPCIONES) or not codigos_activos
        else codigos_activos
    )

    limite_resultados = st.number_input(
        "Máximo de ofertas a analizar:", min_value=1, max_value=50, value=10, step=1
    )

    st.divider()

    # ── Selector de modelo IA ─────────────────────────────────────────────────
    st.markdown("#### ⚙️ Configuración de IA")

    modelo_seleccionado_key = st.selectbox(
        "🤖 Modelo de IA:",
        options=list(backend_ia.MODELOS_DISPONIBLES.keys()),
        index=0,
        help="Selecciona el modelo que analizará las ofertas.",
    )
    modelo_cfg_activo = backend_ia.MODELOS_DISPONIBLES[modelo_seleccionado_key]

    st.caption(f"📝 {modelo_cfg_activo['descripcion']}")

    proveedor_label = "☁️ Google AI Studio" if modelo_cfg_activo["proveedor"] == "gemini" else "⚡ Groq LPU"
    json_label      = "✅ JSON nativo" if modelo_cfg_activo["soporta_json_mode"] else "🔧 Post-procesado"
    reason_label    = "🧠 Razonamiento" if modelo_cfg_activo["es_reasoning"] else ""

    badges = f"`{proveedor_label}` &nbsp; `{json_label}`"
    if reason_label:
        badges += f" &nbsp; `{reason_label}`"
    st.markdown(badges, unsafe_allow_html=True)

    # Avisos contextuales por modelo
    if modelo_cfg_activo["proveedor"] == "gemini" and not backend_ia.GOOGLE_API_KEY:
        st.warning(
            "⚠️ **GOOGLE_API_KEY** no detectada.\n\n"
            "Agrega en tu `.env`:\n`GOOGLE_API_KEY=tu_clave`\n\n"
            "Obtén tu clave gratis en [aistudio.google.com](https://aistudio.google.com)"
        )
    if modelo_cfg_activo["es_reasoning"]:
        st.info(
            "🧠 **Modelo de razonamiento**: genera pensamiento interno antes de responder. "
            "Más lento pero más reflexivo. Los bloques `<think>` se limpian automáticamente."
        )

    st.markdown("<br>", unsafe_allow_html=True)

    delay_groq = st.slider(
        "Delay entre llamadas (seg):",
        min_value=0.0, max_value=6.0,
        value=float(modelo_cfg_activo["delay_recomendado"]),
        step=0.5,
        help="Groq free: mínimo 2 s (30 RPM). Gemini free: mínimo 4 s (15 RPM).",
    )

    caption_delay = (
        "🆓 **Groq free**: 30 req/min · 1.000 req/día → usa ≥ 2 s"
        if modelo_cfg_activo["proveedor"] == "groq"
        else "🆓 **Gemini free**: 15 req/min · 1.500 req/día → usa ≥ 4 s"
    )
    st.caption(caption_delay)

    st.divider()

    # ── Diagnóstico ──────────────────────────────────────────────────────────
    st.markdown("#### 🔧 Diagnóstico de Conexión")
    if st.button("🩺 Probar API SECOP II", use_container_width=True):
        with st.spinner("Probando conexión Socrata…"):
            diag = backend_ia.diagnosticar_api()
        if diag["conexion_ok"]:
            st.success(f"✅ Conexión OK — {diag['total_sin_filtro']} registros")
            st.caption(f"Estados: {diag['muestra_estados']}")
            st.caption(f"IDs: {diag['muestra_ids']}")
        else:
            st.error(f"❌ Error: {diag['error']}")

    st.divider()

    # ── Caché ─────────────────────────────────────────────────────────────────
    st.markdown("#### ♻️ Caché de Análisis")
    stats_cache = backend_ia.obtener_stats_cache()
    st.caption(f"Procesos en caché esta sesión: **{stats_cache['total_entradas']}**")
    if st.button("🗑️ Limpiar caché", use_container_width=True):
        backend_ia.limpiar_cache()
        st.session_state.resultados_analisis = []
        st.session_state.resumen_ejecutivo   = ""
        st.session_state.ultimo_analisis     = None
        st.rerun()


# =============================================================================
# CONTENIDO PRINCIPAL — TABS
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

    # Status pill dinámico
    modelo_nombre_corto = modelo_seleccionado_key.split("—")[0].strip()
    st.markdown(
        f"<div class='status-pill'>"
        f"<span class='status-dot'></span>"
        f"En línea · {modelo_nombre_corto} activo"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Cabecera centrada
    _, col_centro, _ = st.columns([1, 4, 1])
    with col_centro:
        _, col_logo, _ = st.columns([1.5, 2, 1.5])
        with col_logo:
            try:
                st.image("Agent_Principal.png", use_container_width=True)
            except Exception:
                st.markdown("## 🔎")

        st.markdown(
            "<h3 style='text-align:center;'>Agente IA de Contratación SECOP II</h3>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='text-align:center; color:#555;'>"
            "Supervisión inteligente de oportunidades contractuales.<br>"
            "Análisis secuencial · Perfil RUP acreditado · Caché por sesión."
            "</p><br>",
            unsafe_allow_html=True,
        )

        palabra_busqueda = st.text_input(
            "Búsqueda por palabra clave (opcional):",
            placeholder="Ej: Educación virtual, Consultoría TIC, Plataforma e-learning…",
            help="Filtra la búsqueda en SECOP II antes del análisis IA.",
        )

        solo_urgentes = st.checkbox(
            "🔴 Priorizar los que cierran en ≤ 7 días",
            value=False,
            help="Los urgentes se destacan automáticamente sin necesidad de activar esto.",
        )

        st.markdown("<br>", unsafe_allow_html=True)
        _, col_btn, _ = st.columns([1, 2, 1])
        with col_btn:
            btn_analizar = st.button(
                "🔎 Iniciar análisis inteligente",
                type="primary",
                use_container_width=True,
                disabled=st.session_state.analisis_en_curso,
            )

    # ── Lógica de análisis ───────────────────────────────────────────────────
    if btn_analizar:
        st.session_state.analisis_en_curso  = True
        st.session_state.resultados_analisis = []
        st.session_state.resumen_ejecutivo   = ""

        with st.spinner("Consultando SECOP II — descargando y aplicando pre-filtros…"):
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
                "- Prueba el botón **🩺 Probar API SECOP II** en el panel lateral.\n"
                "- Amplía las categorías UNSPSC o deja la palabra clave vacía."
            )
            st.session_state.analisis_en_curso = False
        else:
            model_id_activo = modelo_cfg_activo["model_id"]
            total      = len(ofertas_filtradas)
            en_cache   = sum(
                1 for o in ofertas_filtradas
                if f"{o.get('id_del_proceso')}_{model_id_activo}" in backend_ia._cache_analisis
            )
            a_analizar = total - en_cache
            tiempo_est = int(a_analizar * delay_groq)

            st.info(
                f"✅ **{total} oferta(s)** pasaron el pre-filtro — "
                f"usando **{modelo_seleccionado_key}**\n\n"
                f"♻️ **{en_cache}** en caché · 🧠 **{a_analizar}** nuevas "
                f"(tiempo estimado: ~{tiempo_est}–{tiempo_est + 10} seg)"
            )

            proveedor_txt = "Google Gemini" if modelo_cfg_activo["proveedor"] == "gemini" else "Groq"
            barra         = st.progress(0, text=f"Iniciando análisis con {proveedor_txt}…")
            status_txt    = st.empty()

            def actualizar_progreso(completados: int, total_t: int, id_proc: str, desde_cache: bool):
                pct    = completados / total_t if total_t > 0 else 0
                origen = "⚡ caché" if desde_cache else f"🧠 {proveedor_txt}"
                msg    = f"[{completados}/{total_t}] {origen} → {id_proc}"
                barra.progress(pct, text=msg)
                status_txt.caption(msg)

            resultados_nuevos = backend_ia.analizar_ofertas_secuencial(
                ofertas           = ofertas_filtradas,
                delay_segundos    = float(delay_groq),
                callback_progreso = actualizar_progreso,
                modelo_cfg        = modelo_cfg_activo,
            )

            st.session_state.resultados_analisis = resultados_nuevos
            st.session_state.ultimo_analisis     = datetime.now().strftime("%Y-%m-%d %H:%M")
            st.session_state.analisis_en_curso   = False
            barra.empty()
            status_txt.empty()

            n_ok = len(resultados_nuevos)
            if n_ok > 0:
                st.success(
                    f"🎉 Análisis completado con **{modelo_seleccionado_key}** — "
                    f"**{n_ok} oferta(s) evaluadas**. "
                    f"💾 Resultados guardados en caché."
                )
            else:
                st.warning(
                    "⚠️ El análisis terminó pero ninguna oferta generó un resultado válido. "
                    "Revisa los logs en la consola para más detalles."
                )

            # Resumen ejecutivo (solo si hay al menos 2 resultados)
            if len(resultados_nuevos) >= 2:
                with st.spinner(f"Generando resumen ejecutivo con {modelo_nombre_corto}…"):
                    st.session_state.resumen_ejecutivo = backend_ia.generar_resumen_ejecutivo(
                        resultados_nuevos, modelo_cfg=modelo_cfg_activo,
                    )

    # ── Sección de resultados ─────────────────────────────────────────────────
    if st.session_state.resultados_analisis:
        st.divider()

        # Aplicar filtros laterales
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
            promedio  = int(
                sum(r.get("porcentaje_aplicabilidad", 0) for r in resultados_visibles) / total_vis
            )
            urgentes  = sum(
                1 for r in resultados_visibles
                if 0 <= dias_para_cierre(r.get("fecha_cierre", "")) <= 7
            )

            # KPIs rápidos
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("📊 Analizadas",    total_vis)
            c2.metric("✅ Viables",       viables)
            c3.metric("⚠️ Con Ajustes",  ajustes)
            c4.metric("📈 Aplicabilidad", f"{promedio}%")
            c5.metric("🔴 Urgentes",      urgentes)

            # Resumen ejecutivo IA
            if st.session_state.resumen_ejecutivo:
                st.markdown("<div class='executive-summary'>", unsafe_allow_html=True)
                st.markdown("#### 🧠 Resumen Ejecutivo Estratégico")
                st.markdown(st.session_state.resumen_ejecutivo)
                if st.session_state.ultimo_analisis:
                    st.caption(f"Generado: {st.session_state.ultimo_analisis}")
                st.markdown("</div>", unsafe_allow_html=True)

            # Botón de exportación
            st.markdown("<br>", unsafe_allow_html=True)
            _, col_exp, _ = st.columns([1, 2, 3])
            with col_exp:
                excel_bytes = backend_ia.exportar_reporte_excel(resultados_visibles)
                if excel_bytes:
                    nombre_archivo = f"reporte_secop_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                    st.download_button(
                        label="📥 Exportar Reporte Excel (2 hojas)",
                        data=excel_bytes,
                        file_name=nombre_archivo,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )

            st.divider()

            # Alertas urgentes (destacadas al inicio)
            urgentes_lista = [
                r for r in resultados_visibles
                if 0 <= dias_para_cierre(r.get("fecha_cierre", "")) <= 7
                and r.get("viabilidad") in ("VIABLE", "REQUIERE AJUSTES")
            ]
            if urgentes_lista:
                st.markdown("### 🔴 Procesos Urgentes — Cierran en ≤ 7 días")
                for r in sorted(urgentes_lista, key=lambda x: dias_para_cierre(x.get("fecha_cierre", ""))):
                    dias = dias_para_cierre(r.get("fecha_cierre", ""))
                    st.markdown(
                        f"<span class='urgente-chip'>🔴 {dias} día(s)</span> "
                        f"**{r.get('id_oferta', '')}** — {r.get('entidad', '')} · "
                        f"_{r.get('objeto_contrato', '')}_",
                        unsafe_allow_html=True,
                    )
                st.divider()

            # Listado detallado ordenado
            st.subheader("📋 Detalle del Análisis por Proceso")

            ORDEN_VIAB = {"VIABLE": 0, "REQUIERE AJUSTES": 1, "NO VIABLE": 2}
            resultados_ord = sorted(
                resultados_visibles,
                key=lambda r: (
                    ORDEN_VIAB.get(r.get("viabilidad", "NO VIABLE"), 3),
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
                codigo_u    = oferta.get("codigo_unspsc", "")
                categoria   = oferta.get("categoria_unspsc", "")
                competencia = oferta.get("nivel_competencia", "")
                duracion_c  = oferta.get("duracion_contrato", "")
                match_rup   = oferta.get("match_unspsc_rup", False)
                dias_cierre = dias_para_cierre(oferta.get("fecha_cierre", ""))
                valor_fmt   = formatear_cuantia(oferta.get("valor_estimado", ""))

                icono_comp    = {"BAJO": "🟢", "MEDIO": "🟡", "ALTO": "🔴"}.get(competencia, "⚪")
                urgente_badge = " 🔴" if 0 <= dias_cierre <= 7 else ""
                rup_badge     = " ⭐" if match_rup else ""

                etiqueta = (
                    f"{icono} {oferta.get('id_oferta', 'Sin ID')} — "
                    f"{entidad[:40]} · {porcentaje}% aplicable{urgente_badge}{rup_badge}"
                )

                auto_expand = viabilidad == "VIABLE" and 0 <= dias_cierre <= 7

                with st.expander(etiqueta, expanded=auto_expand):
                    # Chips de estado
                    chips = f"<span class='unspsc-chip'>UNSPSC {codigo_u} · {categoria}</span>"
                    if match_rup:
                        chips += "<span class='rup-chip'>⭐ Código RUP exacto</span>"
                    if 0 <= dias_cierre <= 7:
                        chips += f"<span class='urgente-chip'>🔴 Cierra en {dias_cierre} día(s)</span>"

                    st.markdown(f"**📌 Objeto:** {objeto} &nbsp;&nbsp;{chips}", unsafe_allow_html=True)
                    st.markdown("---")

                    # Metadatos en columnas
                    col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
                    col_m1.markdown(f"**Modalidad**\n\n`{oferta.get('modalidad', 'N/D')}`")
                    col_m2.markdown(f"**Valor estimado**\n\n`{valor_fmt} COP`")
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
                        st.caption(f"{porcentaje}% de aplicabilidad institucional")
                        st.markdown("<br>", unsafe_allow_html=True)
                        st.info(f"**💡 Recomendación:** {oferta.get('recomendacion', '')}")

                        tab_f, tab_r, tab_a = st.tabs(["💪 Fortalezas", "⚠️ Riesgos", "🛠️ Acciones"])

                        with tab_f:
                            fortalezas = oferta.get("fortalezas") or []
                            for item in fortalezas:
                                st.markdown(f"- ✅ {item}")
                            if not fortalezas:
                                st.caption("Sin fortalezas identificadas.")

                        with tab_r:
                            riesgos = oferta.get("riesgos") or []
                            for item in riesgos:
                                st.markdown(f"- 🔺 {item}")
                            if not riesgos:
                                st.caption("Sin riesgos identificados.")

                        with tab_a:
                            acciones = oferta.get("acciones_mejora") or []
                            for item in acciones:
                                st.markdown(f"- 🛠️ {item}")
                            if not acciones:
                                st.caption("Sin acciones recomendadas.")

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
        total_r   = len(resultados)
        viables_r = sum(1 for r in resultados if r.get("viabilidad") == "VIABLE")
        ajustes_r = sum(1 for r in resultados if r.get("viabilidad") == "REQUIERE AJUSTES")
        noviabl_r = total_r - viables_r - ajustes_r
        prom_pct  = int(sum(r.get("porcentaje_aplicabilidad", 0) for r in resultados) / total_r)
        urg_r     = sum(1 for r in resultados if 0 <= dias_para_cierre(r.get("fecha_cierre", "")) <= 7)
        rup_exact = sum(1 for r in resultados if r.get("match_unspsc_rup"))

        # KPIs
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("📂 Total",          total_r)
        c2.metric("✅ Viables",        viables_r)
        c3.metric("⚠️ Ajustes",        ajustes_r)
        c4.metric("❌ No Viables",     noviabl_r)
        c5.metric("📈 Aplicab. Prom.", f"{prom_pct}%")
        c6.metric("⭐ Match RUP",      rup_exact)

        st.divider()

        col_chart1, col_chart2 = st.columns(2)

        with col_chart1:
            st.markdown("#### Distribución de Viabilidad")
            df_viab = pd.DataFrame({
                "Viabilidad": ["VIABLE", "REQUIERE AJUSTES", "NO VIABLE"],
                "Cantidad"  : [viables_r, ajustes_r, noviabl_r],
            })
            st.bar_chart(df_viab.set_index("Viabilidad"), color="#1DD2C1")

        with col_chart2:
            st.markdown("#### Top 15 por Aplicabilidad")
            top15 = sorted(resultados, key=lambda x: x.get("porcentaje_aplicabilidad", 0), reverse=True)[:15]
            df_top = pd.DataFrame([
                {
                    "Proceso"       : f"{r.get('id_oferta','?')[:12]}…",
                    "Aplicabilidad" : r.get("porcentaje_aplicabilidad", 0),
                }
                for r in top15
            ])
            st.bar_chart(df_top.set_index("Proceso"), color="#0083BF")

        st.divider()

        # Tabla consolidada
        st.markdown("#### 📋 Tabla Consolidada")
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
                "Valor (COP)"   : formatear_cuantia(r.get("valor_estimado", "")),
            }
            for r in sorted(resultados, key=lambda x: x.get("porcentaje_aplicabilidad", 0), reverse=True)
        ])
        st.dataframe(df_tabla, use_container_width=True, hide_index=True)

        excel_dash = backend_ia.exportar_reporte_excel(resultados)
        if excel_dash:
            st.download_button(
                label="📥 Descargar Excel Completo",
                data=excel_dash,
                file_name=f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
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
        st.markdown(
            "<div class='profile-card'><h4>📋 Datos Generales</h4><p>"
            "• Trayectoria: <b>17+ años</b> (constitución 2008)<br>"
            "• Proponente RUP vigente desde: <b>2016</b><br>"
            "• Contratos ejecutados: <b>+50</b><br>"
            "• Cobertura: <b>Nacional</b><br>"
            "• Participación en consorcios y U. Temporales: <b>Sí</b>"
            "</p></div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div class='profile-card'><h4>💰 Indicadores Financieros (RUP 2024)</h4><p>"
            "• Índice de Liquidez: <b>1.36</b> — Aceptable<br>"
            "• Índice de Endeudamiento: <b>0.59</b> — Aceptable (límite 0.60)<br>"
            "• Razón Ácida: No reportada explícitamente<br>"
            "• Estado financiero: <b>Vigente — sin alertas críticas</b>"
            "</p></div>",
            unsafe_allow_html=True,
        )

    with col_p2:
        st.markdown(
            "<div class='profile-card'><h4>🎯 Áreas de Alta Competencia</h4><p>"
            "• Educación superior y politécnicos (86121700)<br>"
            "• E-learning y aprendizaje a distancia (86111500)<br>"
            "• Capacitación vocacional científica/no científica<br>"
            "• Consultoría de negocios y gerencia de proyectos<br>"
            "• Ingeniería de software y metodología de sistemas<br>"
            "• Desarrollo de recursos humanos y formación docente<br>"
            "• Materiales y recursos educativos digitales"
            "</p></div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div class='profile-card'><h4>🚫 Fuera del Perfil (Rechazo automático)</h4><p>"
            "• Construcción civil y obras de infraestructura<br>"
            "• Suministro de alimentos y bienes físicos<br>"
            "• Aseo, limpieza y mantenimiento<br>"
            "• Vigilancia y seguridad física<br>"
            "• Transporte y manufactura"
            "</p></div>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("#### 🗂️ Códigos UNSPSC Acreditados en RUP (35 códigos)")

    UNSPSC_TABLE: dict[str, str] = {
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

    df_unspsc = pd.DataFrame([
        {"Código UNSPSC": k, "Descripción": v} for k, v in UNSPSC_TABLE.items()
    ])
    st.dataframe(df_unspsc, use_container_width=True, hide_index=True, height=500)

    st.caption(
        "⭐ Cuando un proceso de SECOP II coincide exactamente con uno de estos códigos, "
        "el motor IA le asigna un bonus de +15 puntos en el porcentaje de aplicabilidad "
        "y lo marca como **Match RUP Exacto**."
    )