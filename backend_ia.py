# Importación de las librerias necesarias
from google import genai
from sodapy import Socrata
from dotenv import load_dotenv
import time
import os
import json
from datetime import datetime, timedelta

# Carga de variables de entorno
load_dotenv()
API_KEY = os.environ.get("API_KEY_GEMINI_PROFE")
TOKEN = os.environ.get("TOKEN")

# Configuración de clientes api Apikey y Socrata
gemini_client = genai.Client(api_key=API_KEY)
socrata_client = Socrata("www.datos.gov.co",TOKEN)

# --- DATOS SIMULADOS DE LA UNIVERSIDAD ---
DATOS_UNIVERSIDAD = """
- Índice de Liquidez: 2.1 (Excelente)
- Índice de Endeudamiento: 0.4 (Bajo)
- Razón de Cobertura de Intereses: 3.5 (Alta)
- Experiencia Principal: Educación superior, consultoría en tecnología (TIC), interventoría en proyectos educativos, capacitación docente.
- Experiencia no relevante: Construcción civil, suministro de alimentos, servicios de aseo.
"""

# Extraer las ofertas del SECOP II
def obtener_ofertas_secop(limite=10, palabra_clave=None):
    """Descarga las ofertas del SECOP II, opcionalmente filtradas por palabra clave."""
    try:
        # Si el usuario escribió una palabra clave, usamos el parámetro 'q' de Socrata (Full text search)
        if palabra_clave:
            resultados = socrata_client.get(
                "p6dx-8zbt",
                q=palabra_clave, # Busca en todo el documento de la oferta
                order="fecha_de_publicacion_del DESC",
                limit=limite
            )
        else:
            # Si no hay palabra clave, trae las últimas generales
            resultados = socrata_client.get(
                "p6dx-8zbt",
                order="fecha_de_publicacion_del DESC",
                limit=limite
            )
        return resultados
    except Exception as e:
        print(f"Error al conectar con Socrata: {e}")
        return []

# Análisis de los datos del SECOP II con los de la Universidad
def analizar_oferta_ia(oferta):
    # Extraccion de informacion para darsela a la IA
    entidad = oferta.get('entidad', 'Entidad Desconocida')
    descripcion = oferta.get('descripci_n_del_procedimiento', 'Sin descripción')
    cuantia = oferta.get('precio_base', 'No especificado')
    modalidad = oferta.get('modalidad_de_contratacion', 'No especificada')

    # Manejo seguro de la URL
    url_info = oferta.get('urlproceso', {})
    enlace = url_info.get('url', 'Sin enlace') if isinstance(url_info, dict) else url_info
    
    # Manejo de la fecha real de cierre para el semáforo
    fecha_cierre_str = oferta.get('fecha_de_recepcion_de')
    if fecha_cierre_str:
        # Esto porque Socrata envía fechas tipo '2023-10-25T15:00:00.000'
        try:
            fecha_obj = datetime.fromisoformat(fecha_cierre_str.split('.')[0])
            fecha_cierre = fecha_obj.strftime("%Y-%m-%d %H:%M")
        except:
            fecha_cierre = "Fecha inválida"
    else:
        fecha_cierre = "Sin fecha definida"

    # Prompt Optimizado
    prompt = f"""
    Eres un analista experto en contratación estatal colombiana y SECOP II.
    Evalúa si nuestra universidad cumple para participar en este proceso.

    DATOS DE LA UNIVERSIDAD (RUP y Experiencia):
    {DATOS_UNIVERSIDAD}

    DATOS DE LA OFERTA (SECOP II):
    - Entidad: {entidad}
    - Objeto: {descripcion}
    - Valor Estimado: ${cuantia}
    - Modalidad: {modalidad}

    Genera un análisis estructurado.
    DEBES RESPONDER ÚNICA Y ESTRICTAMENTE EN FORMATO JSON. NO incluyas texto antes ni después del JSON.
    
    Estructura requerida:
    {{
        "id_oferta": "{oferta.get('id_del_proceso', 'Desconocido')}",
        "entidad": "{entidad}",
        "viabilidad": "VIABLE, NO VIABLE, o REQUIERE AJUSTES",
        "porcentaje_aplicabilidad": [Número del 0 al 100],
        "recomendacion": "Un párrafo corto (máximo 3 líneas) justificando el veredicto.",
        "fecha_cierre": "{fecha_cierre}",
        "enlace_secop": "{enlace}"
    }}
    """

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt
        )
        
        texto_limpio = response.text.replace("```json", "").replace("```", "").strip()
        analisis_dict = json.loads(texto_limpio)
        return analisis_dict

    except Exception as e:
        print(f"Error procesando oferta de {entidad}: {e}")
        return None