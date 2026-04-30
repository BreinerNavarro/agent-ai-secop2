# Importación de las librerias necesarias
from google import genai
from sodapy import Socrata
from dotenv import load_dotenv
import os

# Carga de variables de entorno
load_dotenv()
API_KEY = os.environ.get("API_KEY_GEMINI_PROFE")
TOKEN = os.environ.get("TOKEN")

# Configuración del cliente api Apikey
client = genai.Client(api_key=API_KEY)

# Extraer las ofertas del SECOP II
def obtener_ofertas_secop():
    try:

        client = Socrata("www.datos.gov.co",TOKEN)
        results = client.get("jbjy-vk9h", order="fecha_de_firma DESC",
                             limit=5,where="fecha_de_firma between '2025-01-01' and '2025-12-31'")

        return results
    except Exception as e:
        print(f"Ocurrió un error SECOP II: {e}")

def analizar_con_gemini(data_oferta):
    """Envía los datos de la oferta a Gemini para análisis."""
    prompt = f"""
    Eres un analista experto en contratación estatal colombiana y SECOP II.
    Tu objetivo es evaluar de forma rápida si nuestra institución cumple financieramente para participar en este proceso.

    DATOS FINANCIEROS DE NUESTRA INSTITUCIÓN (RUP):
    - Índice de Liquidez: 2.1 (Excelente)
    - Índice de Endeudamiento: 0.4 (Bajo)
    - Razón de Cobertura de Intereses: 3.5 (Alta)

    DATOS TÉCNICOS DE LA OFERTA (SECOP II):
    {data_oferta}

    Por favor, genera un análisis estructurado con lo siguiente:
    1. Entidad y Objeto del contrato (Muy breve).
    2. Valor Estimado.
    3. VEREDICTO DE VIABILIDAD: Analiza los datos de la oferta. Si la oferta menciona requisitos financieros, compáralos con nuestros datos. Responde en mayúsculas: "VIABLE", "NO VIABLE", o "REQUIERE LEER PLIEGO COMPLETO" (si los datos de Socrata no traen los indicadores requeridos).
    4. Justificación del veredicto (1 párrafo).
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt
    )

    return response.text

# --- EJECUCIÓN ---
try:
    print("Obteniendo datos del SECOP II...")
    ofertas = obtener_ofertas_secop()
    print(ofertas)

    if len(ofertas) == 0:
        print(f"No se encontraron ofertas.")

    for oferta in ofertas:
        # Tomamos la primera oferta para la prueba
        primera_oferta = oferta
        print(f"Analizando oferta: {primera_oferta.get('descripcion_del_proceso', 'Sin nombre')}")

        analisis = analizar_con_gemini(primera_oferta)
        print("\n--- RESUMEN DE GEMINI ---")
        print(analisis)


except Exception as e:
    print(f"Ocurrió un error: {e}")