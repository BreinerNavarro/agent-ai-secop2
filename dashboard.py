import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# 1. Configuración principal de la página
st.set_page_config(page_title="Analista SECOP IA", page_icon="🤖", layout="wide")

st.title("🤖 Agente IA - Análisis de Viabilidad SECOP II")
st.markdown("Evaluación automática de ofertas contra el RUP e historial de la Universidad.")

# --- DATOS SIMULADOS (Luego los traeremos de tu función Gemini y Socrata) ---
# Simulamos una lista de ofertas ya analizadas
datos_ofertas = [
    {"id": "Proceso 001", "entidad": "MinTIC", "viabilidad": "VIABLE", "porcentaje": 95, "cierre": datetime.now() + timedelta(days=2)},
    {"id": "Proceso 002", "entidad": "SENA", "viabilidad": "REQUIERE AJUSTES", "porcentaje": 60, "cierre": datetime.now() + timedelta(days=10)},
    {"id": "Proceso 003", "entidad": "Alcaldía de Bogotá", "viabilidad": "NO VIABLE", "porcentaje": 20, "cierre": datetime.now() + timedelta(days=5)},
]

# 2. Función para el Semáforo de Tiempo
def semaforo_tiempo(fecha_cierre):
    """Devuelve un color dependiendo de los días faltantes para el cierre."""
    dias_restantes = (fecha_cierre - datetime.now()).days
    if dias_restantes <= 3:
        return "🔴 Crítico (<= 3 días)"
    elif dias_restantes <= 7:
        return "🟡 Precaución (4 - 7 días)"
    else:
        return "🟢 Buen tiempo (> 7 días)"

# 3. Construcción del Dashboard
col1, col2, col3 = st.columns(3)

# Mostrar un resumen rápido en tarjetas
ofertas_viables = sum(1 for o in datos_ofertas if o["viabilidad"] == "VIABLE")
col1.metric(label="Ofertas Analizadas", value=len(datos_ofertas))
col2.metric(label="Total Viables", value=ofertas_viables)
col3.metric(label="Tasa de Éxito Promedio", value="58%")

st.divider()
st.subheader("📋 Detalle de Ofertas Evaluadas")

# 4. Mostrar las ofertas iterando sobre los datos
for oferta in datos_ofertas:
    with st.expander(f"{oferta['id']} - {oferta['entidad']} ({oferta['porcentaje']}% Aplicabilidad)"):
        c1, c2, c3 = st.columns(3)
        
        # Muestra la viabilidad
        c1.markdown(f"**Veredicto:** {oferta['viabilidad']}")
        
        # Barra de progreso para el porcentaje
        c2.markdown("**Porcentaje de Aplicabilidad:**")
        c2.progress(oferta['porcentaje'] / 100.0)
        
        # Muestra el semáforo
        estado_tiempo = semaforo_tiempo(oferta['cierre'])
        c3.markdown(f"**Tiempo de Cierre:** {estado_tiempo}")
        
        # Espacio para las recomendaciones de la IA
        st.info("💡 **Feedback de la IA:** Para llegar al 100%, la universidad necesita demostrar 2 proyectos más con experiencia específica en esta área. Financieramente, cumple todos los requisitos.")