import streamlit as st
import pandas as pd
from datetime import datetime
import backend_ia 

# ---  CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="IA SECOP - Universidad", page_icon="🎓", layout="wide")

def semaforo_tiempo(fecha_str):
    """Calcula los días restantes y devuelve un estado visual."""
    if fecha_str in ["Fecha inválida", "Sin fecha definida"]:
        return "⚪ Fecha no disponible"
    try:
        fecha_cierre = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M")
        dias_restantes = (fecha_cierre - datetime.now()).days
        if dias_restantes < 0: return "⚫ Cerrado"
        elif dias_restantes <= 3: return f"🔴 Crítico ({dias_restantes} días)"
        elif dias_restantes <= 7: return f"🟡 Precaución ({dias_restantes} días)"
        else: return f"🟢 Buen tiempo ({dias_restantes} días)"
    except: return "⚪ Error en fecha"

# ---  MEMORIA DEL ESTADO ---
if 'resultados_analisis' not in st.session_state:
    st.session_state.resultados_analisis = []

# ---  BARRA LATERAL (FILTROS) ---
st.sidebar.title("⚙️ Filtros Inteligentes")
st.sidebar.markdown("Usa estos filtros para organizar los resultados analizados por la IA.")

filtro_viabilidad = st.sidebar.multiselect(
    "1. Filtrar por Veredicto:",
    options=["VIABLE", "REQUIERE AJUSTES", "NO VIABLE"],
    default=["VIABLE", "REQUIERE AJUSTES", "NO VIABLE"] # Por defecto muestra todos
)

filtro_porcentaje = st.sidebar.slider(
    "2. Porcentaje Mínimo de Aplicabilidad:",
    min_value=0, max_value=100, value=0, step=10
)

st.sidebar.divider()
st.sidebar.info("💡 **Tip:** Ajusta el slider a 70% o más para ver solo las ofertas con alta probabilidad de éxito para la Universidad.")

# ---  INTERFAZ GRÁFICA PRINCIPAL ---
st.title("🎓 Agente IA - Análisis de Viabilidad SECOP II")

# Controles de Búsqueda
st.markdown("### 🔍 Nueva Búsqueda")
col_input, col_btn = st.columns([3, 1])

with col_input:
    # Cuadro de texto para la palabra clave
    palabra_busqueda = st.text_input(
        "Palabra clave del sector:", 
        placeholder="Ej: Educación, Software, Consultoría, TIC... (Deja en blanco para ver recientes generales)"
    )

with col_btn:
    st.markdown("<br>", unsafe_allow_html=True) # Pequeño truco para alinear el botón con el input
    if st.button("🚀 Buscar y Analizar", type="primary", use_container_width=True):
        st.session_state.resultados_analisis = [] 
        
        with st.spinner(f"Consultando SECOP y evaluando viabilidad..."):
            # Llamamos a la función con la palabra clave que escribió el usuario
            ofertas_crudas = backend_ia.obtener_ofertas_secop(limite=3, palabra_clave=palabra_busqueda)
            
            if not ofertas_crudas:
                st.error("No se encontraron ofertas con esa palabra en este momento.")
            else:
                barra_progreso = st.progress(0)
                for i, oferta in enumerate(ofertas_crudas):
                    analisis = backend_ia.analizar_con_gemini(oferta)
                    if analisis: st.session_state.resultados_analisis.append(analisis)
                    barra_progreso.progress((i + 1) / len(ofertas_crudas))
                st.success("¡Análisis completado!")

# ---  DIBUJAR DASHBOARD CON FILTROS APLICADOS ---
if len(st.session_state.resultados_analisis) > 0:
    st.divider()
    
    # ¡AQUÍ ESTÁ LA MAGIA! Filtramos la lista en memoria según lo que diga la barra lateral
    resultados_filtrados = [
        oferta for oferta in st.session_state.resultados_analisis
        if oferta.get("viabilidad", "NO VIABLE") in filtro_viabilidad
        and oferta.get("porcentaje_aplicabilidad", 0) >= filtro_porcentaje
    ]
    
    total_filtrados = len(resultados_filtrados)
    
    if total_filtrados == 0:
        st.warning("⚠️ No hay resultados que coincidan con los filtros de la barra lateral. Intenta bajando el porcentaje o marcando más veredictos.")
    else:
        # Métricas actualizadas según el filtro
        viables = sum(1 for r in resultados_filtrados if r.get("viabilidad") == "VIABLE")
        promedio = int(sum(r.get("porcentaje_aplicabilidad", 0) for r in resultados_filtrados) / total_filtrados)

        c1, c2, c3 = st.columns(3)
        c1.metric("Ofertas en Pantalla", total_filtrados)
        c2.metric("Procesos Viables", viables)
        c3.metric("Aplicabilidad Promedio", f"{promedio}%")

        st.subheader("📋 Detalle de Evaluaciones IA")

        # Dibujamos solo las ofertas que pasaron el filtro
        for oferta in resultados_filtrados:
            viabilidad = oferta.get('viabilidad', 'DESCONOCIDO')
            icono = "✅" if viabilidad == "VIABLE" else "⚠️" if viabilidad == "REQUIERE AJUSTES" else "❌"
            porcentaje = oferta.get('porcentaje_aplicabilidad', 0)
            
            with st.expander(f"{icono} {oferta.get('id_oferta', 'Sin ID')} - {oferta.get('entidad', 'Sin Entidad')} ({porcentaje}% Aplicable)"):
                col_info, col_estado = st.columns([2, 1])
                
                with col_info:
                    st.markdown(f"**Veredicto:** `{viabilidad}`")
                    st.info(f"**Recomendación IA:** {oferta.get('recomendacion', '')}")
                    st.progress(porcentaje / 100.0)
                
                with col_estado:
                    st.markdown("**Tiempo para cierre:**")
                    st.markdown(f"*{semaforo_tiempo(oferta.get('fecha_cierre', ''))}*")
                    enlace = oferta.get('enlace_secop', '#')
                    if enlace != "Sin enlace": st.link_button("🌐 Ver en SECOP", enlace)