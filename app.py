import streamlit as st
import pandas as pd
from datetime import datetime
import backend_ia 
import time

# --- CONFIGURACIÓN DE LA PÁGINA ---

st.set_page_config(page_title="UniCop Agent", page_icon="Agent_Principal.png", layout="wide")

# --- ESTILOS PERSONALIZADOS (UI "Agente" + Unicafam) ---
st.markdown("""
    <style>
    /* Tipografía Global */
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;800&display=swap');
    html, body, [class*="css"] { font-family: 'Montserrat', sans-serif !important; }

    /* Tarjeta Blanca Central ("Welcome Panel") */
    [data-testid="block-container"] {
        background-color: #FFFFFF;
        border-radius: 20px;
        padding: 40px !important;
        margin-top: 60px !important;
        margin-bottom: 40px !important;
        box-shadow: 0 10px 30px rgba(0, 42, 66, 0.08);
        max-width: 85% !important; /* Para que deje ver el fondo gris alrededor */
    }

    /* Barra Lateral (Sidebar Dark) */
    [data-testid="stSidebar"] {
        background-color: #002A42 !important; /* Azul Oscuro Unicafam */
    }
    /* Letra blanca en la barra lateral */
    [data-testid="stSidebar"] * { color: #FFFFFF !important; }
    
    /* Línea indicadora de ítem activo en la sidebar simulada */
    .sidebar-menu-active {
        border-left: 4px solid #A6DFFF;
        background-color: rgba(255,255,255,0.05);
        padding: 10px 15px;
        margin-left: -15px;
        font-weight: bold;
    }

    /* Botón Principal con Degradado (Estilo de la imagen) */
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
    .stButton > button:hover {
        transform: scale(1.02);
        box-shadow: 0 6px 20px rgba(0, 131, 191, 0.4);
    }

    /* Pill de Estado Superior Derecho */
    .status-pill {
        background-color: #D3F5ED;
        color: #0F7A6A;
        padding: 6px 15px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: bold;
        position: absolute;
        top: -40px;
        right: 0px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .status-dot {
        height: 8px; width: 8px;
        background-color: #1DD2C1;
        border-radius: 50%;
        display: inline-block;
    }
    
    /* Textos oscuros en el panel central */
    h1, h2, h3, h4, h5 { color: #002A42 !important; font-weight: 800 !important; }
    p { color: #333333; }
    </style>
    """, unsafe_allow_html=True)

def semaforo_tiempo(fecha_str):
    if fecha_str in ["Fecha inválida", "Sin fecha definida"]: return "⚪ Fecha no disponible"
    try:
        fecha_cierre = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M")
        dias_restantes = (fecha_cierre - datetime.now()).days
        if dias_restantes < 0: return "⚫ Cerrado"
        elif dias_restantes <= 3: return f"🔴 Crítico ({dias_restantes} días)"
        elif dias_restantes <= 7: return f"🟡 Precaución ({dias_restantes} días)"
        else: return f"🟢 Buen tiempo ({dias_restantes} días)"
    except: return "⚪ Error en fecha"

if 'resultados_analisis' not in st.session_state:
    st.session_state.resultados_analisis = []

# --- ESTRUCTURA VISUAL ---
# Indicador de estado (Esquina superior derecha)
st.markdown("""
    <div class="status-pill">
        <span class="status-dot"></span> En línea - IA SECOP II Activado &nbsp; 👤
    </div>
""", unsafe_allow_html=True)

# --- BARRA LATERAL ---
# Intentamos cargar el logo en la barra lateral
try:
    st.sidebar.image("Agent_lateral.png", width=100)
except:
    pass # Si falla, simplemente no lo muestra para no romper la app

#st.sidebar.markdown("## UniCop Agent")
st.sidebar.markdown("<div class='sidebar-menu-active'>⊞ Dashboard Panel</div>", unsafe_allow_html=True)
st.sidebar.markdown("<br>☷ **Filtros de Análisis**", unsafe_allow_html=True)

filtro_viabilidad = st.sidebar.multiselect(
    "Veredicto:", options=["VIABLE", "REQUIERE AJUSTES", "NO VIABLE"], default=["VIABLE", "REQUIERE AJUSTES", "NO VIABLE"]
)
filtro_porcentaje = st.sidebar.slider("Aplicabilidad Mínima:", min_value=0, max_value=100, value=0, step=10)
st.sidebar.divider()
st.sidebar.caption("💡 Ajusta los parámetros para que el agente filtre los contratos de forma inteligente.")


# --- CONTENIDO CENTRAL (WELCOME PANEL) ---
st.markdown("#### Welcome Panel")

# Centrado visual para título y buscador
col_vacia1, col_centro, col_vacia2 = st.columns([1, 4, 1])

with col_centro:
    
    # --- AQUÍ VA EL LOGO CENTRADO ---
    col_img1, col_img_centro, col_img3 = st.columns([1.5, 2, 1.5])
    with col_img_centro:
        try:
            st.image("Agent_Principal.png", use_container_width=True)
        except:
            st.warning("⚠️ No se encontró 'Agent_Principal.png'. Verifica que esté en la carpeta.")
    # --------------------------------
    
    # Quité el emoji del escudo porque ahora está tu logo oficial
    #st.markdown("<h1 style='text-align: center;'>Agente SECOP Unicafam</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align: center;'>Bienvenido a tu agente IA de contratación con el estado</h3>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Su interfaz de IA integral para una supervisión y postulación eficiente.</p><br>", unsafe_allow_html=True)
    
    # Cuadro de búsqueda central
    palabra_busqueda = st.text_input(
        "Palabra clave a evaluar:", 
        placeholder="Ej: Educación, Consultoría, TIC, Software..."
    )

    # Botón centrado
    st.markdown("<br>", unsafe_allow_html=True)
    col_btn_1, col_btn_2, col_btn_3 = st.columns([1, 2, 1])
    with col_btn_2:
        btn_analizar = st.button("Comenzar nueva sesión", type="primary", use_container_width=True)


# --- LÓGICA DE BÚSQUEDA ---
if btn_analizar:
    st.session_state.resultados_analisis = [] 
    
    with st.spinner(f"Consultando SECOP y evaluando viabilidad..."):
        # Asegúrate de que tu backend tenga el límite adecuado para no agotar la API
        ofertas_crudas = backend_ia.obtener_ofertas_secop(limite=10, palabra_clave=palabra_busqueda)
        
        if not ofertas_crudas:
            st.error("No se encontraron ofertas con esa palabra en este momento.")
        else:
            barra_progreso = st.progress(0)
            for i, oferta in enumerate(ofertas_crudas):
                # NOTA: Cambié "analizar_con_gemini" a "analizar_oferta_ia" que es como lo llamamos en el backend
                analisis = backend_ia.analizar_oferta_ia(oferta)
                if analisis: 
                    st.session_state.resultados_analisis.append(analisis)
                barra_progreso.progress((i + 1) / len(ofertas_crudas))
                time.sleep(3) 
            st.success("¡Análisis completado con éxito!")


# --- DIBUJAR RESULTADOS ---
if len(st.session_state.resultados_analisis) > 0:
    st.divider()
    
    resultados_filtrados = [
        oferta for oferta in st.session_state.resultados_analisis
        if oferta.get("viabilidad", "NO VIABLE") in filtro_viabilidad
        and oferta.get("porcentaje_aplicabilidad", 0) >= filtro_porcentaje
    ]
    
    total_filtrados = len(resultados_filtrados)
    
    if total_filtrados == 0:
        st.warning("⚠️ No hay resultados que coincidan con los filtros laterales.")
    else:
        # Métricas
        viables = sum(1 for r in resultados_filtrados if r.get("viabilidad") == "VIABLE")
        promedio = int(sum(r.get("porcentaje_aplicabilidad", 0) for r in resultados_filtrados) / total_filtrados)

        c1, c2, c3 = st.columns(3)
        c1.metric("Ofertas en Pantalla", total_filtrados)
        c2.metric("Procesos Viables", viables)
        c3.metric("Aplicabilidad Promedio", f"{promedio}%")

        st.subheader("📋 Detalle del Análisis")

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