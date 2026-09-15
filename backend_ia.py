# =============================================================================
# backend_ia.py — Motor de análisis SECOP II con IA
# Dos motores de análisis: 🖥️ IA Local (Ollama) · ❇️ Gemini (Google AI Studio)
# =============================================================================
from __future__ import annotations

import io
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Callable

import pandas as pd
import requests
from dotenv import load_dotenv
from sodapy import Socrata

# Import opcional: el módulo debe poder importarse aunque falte el SDK de Google.
try:
    from google import genai
except ImportError:  # pragma: no cover
    genai = None  # type: ignore[assignment]

# =============================================================================
# CONFIGURACIÓN DE LOGGING
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("secop_ia")

# =============================================================================
# VARIABLES DE ENTORNO
# =============================================================================
load_dotenv()

GOOGLE_API_KEY: str | None = os.environ.get("API_KEY_GEMINI_MIA") or os.environ.get("GOOGLE_API_KEY")
TOKEN:          str | None = os.environ.get("TOKEN")  # Socrata SECOP II

# Ollama — servidor local (por defecto el puerto estándar de instalación)
OLLAMA_HOST:          str = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL_DEFAULT: str = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")

# =============================================================================
# CONSTANTES DE CONFIGURACIÓN
# =============================================================================
DATASET_ID        = "p6dx-8zbt"
DIAS_HISTORICO    = 90     # Ventana de búsqueda en días
BUFFER_MULTIPLIER = 10     # Factor de buffer al descargar ofertas
MAX_BUFFER        = 800    # Máximo de registros descargados por petición
MAX_RETRY         = 3      # Intentos máximos ante errores de API
RETRY_BASE_DELAY  = 2.0    # Delay base de backoff exponencial (segundos)
RETRY_MAX_DELAY   = 30.0   # Techo del backoff para no congelar la UI
JSON_PARSE_MAXLEN = 300    # Caracteres de respuesta cruda en logs de error
SOCRATA_TIMEOUT   = 60     # Timeout de red en segundos

# Ollama: la inferencia local puede tardar bastante en CPU/iGPU.
OLLAMA_TIMEOUT      = int(os.environ.get("OLLAMA_TIMEOUT", "300"))       # seg por llamada
OLLAMA_PING_TIMEOUT = 4                                                  # seg para detectar servidor
OLLAMA_NUM_CTX      = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))      # ventana de contexto
OLLAMA_NUM_PREDICT  = int(os.environ.get("OLLAMA_NUM_PREDICT", "1536"))  # tokens de salida


class ErrorConfiguracion(Exception):
    """Error no recuperable (credenciales ausentes, servidor local caído, etc.)."""


# =============================================================================
# INICIALIZACIÓN DE CLIENTES — tolerante a credenciales ausentes
# =============================================================================
gemini_client: Any | None = None
if GOOGLE_API_KEY and genai is not None:
    try:
        gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
        logger.info("Cliente Gemini inicializado correctamente.")
    except Exception as exc:
        logger.warning("No se pudo inicializar Gemini: %s", exc)

socrata_client: Socrata = Socrata("www.datos.gov.co", TOKEN, timeout=SOCRATA_TIMEOUT)

# =============================================================================
# CACHÉ EN MEMORIA
# Clave: "{id_proceso}_{model_id}" → re-analiza al cambiar de modelo
# =============================================================================
_cache_analisis: dict[str, dict] = {}


# =============================================================================
# INTEGRACIÓN CON OLLAMA (IA LOCAL)
# =============================================================================
def ollama_disponible() -> bool:
    """True si el servidor de Ollama responde en OLLAMA_HOST."""
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=OLLAMA_PING_TIMEOUT)
        return r.ok
    except requests.RequestException:
        return False


def listar_modelos_ollama() -> list[str]:
    """ Lista los modelos descargados localmente (equivalente a `ollama list`). """

    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=OLLAMA_PING_TIMEOUT)
        r.raise_for_status()
        modelos = [m.get("name", "") for m in (r.json().get("models") or [])]
        modelos = sorted(n for n in modelos if n)
        logger.info("Ollama — %d modelo(s) local(es) detectado(s).", len(modelos))
        return modelos
    except requests.RequestException as exc:
        logger.warning("No se pudo consultar Ollama en %s: %s", OLLAMA_HOST, exc)
        return []
    except (ValueError, AttributeError) as exc:
        logger.warning("Respuesta inesperada de Ollama: %s", exc)
        return []


def detalle_modelos_ollama() -> list[dict[str, Any]]:
    """
    Lista los modelos locales con su tamaño en disco y metadatos.
    Útil para mostrar una tabla informativa en la UI.
    """
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=OLLAMA_PING_TIMEOUT)
        r.raise_for_status()
        salida: list[dict[str, Any]] = []
        for m in (r.json().get("models") or []):
            det = m.get("details") or {}
            salida.append({
                "nombre"      : m.get("name", ""),
                "tamano_gb"   : round((m.get("size") or 0) / 1_000_000_000, 2),
                "familia"     : det.get("family", "N/D"),
                "parametros"  : det.get("parameter_size", "N/D"),
                "cuantizacion": det.get("quantization_level", "N/D"),
            })
        return sorted(salida, key=lambda x: x["nombre"])
    except Exception as exc:
        logger.warning("No se pudo obtener el detalle de modelos: %s", exc)
        return []


def info_modelo_ollama(model_id: str) -> dict[str, Any]:
    """Metadatos básicos de un modelo local (familia, parámetros, cuantización)."""
    try:
        r = requests.post(
            f"{OLLAMA_HOST}/api/show", json={"model": model_id}, timeout=OLLAMA_PING_TIMEOUT
        )
        r.raise_for_status()
        detalles = r.json().get("details") or {}
        return {
            "familia"     : detalles.get("family", "N/D"),
            "parametros"  : detalles.get("parameter_size", "N/D"),
            "cuantizacion": detalles.get("quantization_level", "N/D"),
        }
    except Exception:
        return {"familia": "N/D", "parametros": "N/D", "cuantizacion": "N/D"}


def _llamar_ollama(prompt: str, model_id: str, json_mode: bool) -> str:
    """
    Llama al endpoint /api/chat de Ollama en modo no-streaming.
    `format: "json"` obliga al modelo a emitir JSON sintácticamente válido
    """
    payload: dict[str, Any] = {
        "model"   : model_id,
        "messages": [{"role": "user", "content": prompt}],
        "stream"  : False,
        "options" : {
            "temperature": 0.4,      # Más bajo = más determinista para JSON
            "num_ctx"    : OLLAMA_NUM_CTX,
            "num_predict": OLLAMA_NUM_PREDICT,
        },
    }
    if json_mode:
        payload["format"] = "json"

    try:
        respuesta = requests.post(
            f"{OLLAMA_HOST}/api/chat", json=payload, timeout=OLLAMA_TIMEOUT
        )
    except requests.ConnectionError as exc:
        # Servidor caído: no tiene sentido reintentar con backoff.
        raise ErrorConfiguracion(
            f"No hay conexión con Ollama en {OLLAMA_HOST}. "
            f"Ejecuta `ollama serve` y verifica el puerto. Detalle: {exc}"
        ) from exc
    except requests.Timeout as exc:
        raise RuntimeError(
            f"Ollama excedió {OLLAMA_TIMEOUT}s con '{model_id}'. "
            f"Prueba un modelo más pequeño o sube OLLAMA_TIMEOUT."
        ) from exc

    if respuesta.status_code == 404:
        raise ErrorConfiguracion(
            f"El modelo '{model_id}' no está instalado localmente. "
            f"Descárgalo con: ollama pull {model_id}"
        )

    respuesta.raise_for_status()
    datos = respuesta.json()

    if datos.get("error"):
        raise RuntimeError(f"Ollama devolvió un error: {datos['error']}")

    return (datos.get("message") or {}).get("content", "") or ""


# =============================================================================
# CATÁLOGO DE MODELOS DISPONIBLES — dos motores
# =============================================================================
def construir_cfg_ollama(model_id: str | None = None) -> dict[str, Any]:
    """
    Construye la configuración del motor local para CUALQUIER modelo instalado.
    Permite cambiar de modelo desde la UI sin tocar el catálogo.
    """
    model_id = model_id or OLLAMA_MODEL_DEFAULT
    # Los modelos de razonamiento locales emiten bloques <think> antes del JSON.
    es_reasoning = bool(re.search(r"(deepseek-r1|qwq|reason|think)", model_id, re.IGNORECASE))
    return {
        "proveedor"        : "ollama",
        "model_id"         : model_id,
        "descripcion"      : f"Ejecución 100% local vía Ollama ({model_id}). Sin rate limit ni cuota.",
        "soporta_json_mode": True,
        "es_reasoning"     : es_reasoning,
        "delay_recomendado": 0.0,   # Local: no hay límite de peticiones por minuto
    }


CLAVE_MOTOR_LOCAL  = "🖥️ IA Local — Ollama"
CLAVE_MOTOR_GEMINI = "❇️ Gemini 2.5 Flash — Google"

MODELOS_DISPONIBLES: dict[str, dict[str, Any]] = {
    CLAVE_MOTOR_LOCAL: construir_cfg_ollama(),
    CLAVE_MOTOR_GEMINI: {
        "proveedor"        : "gemini",
        "model_id"         : "gemini-2.5-flash",
        "descripcion"      : "Modelo en la nube, equilibrado entre velocidad, razonamiento y costo.",
        "soporta_json_mode": True,
        "es_reasoning"     : False,
        "delay_recomendado": 4.0,   # Free tier: 15 RPM → conservador
    },
}

MODELO_DEFAULT_KEY = CLAVE_MOTOR_LOCAL

# =============================================================================
# PERFIL INSTITUCIONAL
# Basado en documentos institucionales y RUP (corte 31/12/2024)
# =============================================================================
PERFIL_UNIVERSIDAD = """
## PERFIL INSTITUCIONAL
- Tipo: Empresa de consultoría y servicios educativos (persona jurídica privada)
- Trayectoria: Constituida en 2008 — más de 17 años de experiencia continua
- Registro como proponente en RUP: vigente desde 2016
- Estado RUP: Vigente y al día
- Cobertura: Nacional — con capacidad de ejecución en todos los departamentos

## INDICADORES FINANCIEROS (corte 31/12/2024 — datos RUP oficiales)
| Indicador               | Valor registrado | Evaluación técnica                   |
|-------------------------|------------------|--------------------------------------|
| Índice de Liquidez      | 1.36             | Aceptable — supera el mínimo de 1.0  |
| Índice de Endeudamiento | 0.59             | Aceptable — cerca del límite de 0.60 |
| Razón Ácida             | No reportada     | Verificar en estados financieros     |

## EXPERIENCIA CONTRACTUAL ACREDITADA
- Más de 50 contratos ejecutados con entidades públicas, privadas e internacionales
- Participación en consorcios y uniones temporales
- Contratos con entidades de cooperación internacional y ONG
- Historial limpio sin antecedentes disciplinarios ni contractuales negativos

## ÁREAS DE ALTA COMPETENCIA — PRIORIZAR SIEMPRE
1. Educación superior, programas académicos universitarios y politécnicos
2. Formación docente y desarrollo curricular
3. Educación de adultos y programas de educación continua
4. Aprendizaje a distancia y e-learning (plataformas y contenidos virtuales)
5. Materiales y recursos educativos digitales y físicos
6. Consultoría de negocios, administración corporativa y gerencia de proyectos
7. Gerencia industrial y desarrollo de recursos humanos
8. Ingeniería de software — metodología, análisis y administración de accesos
9. Asistencia técnica para el desarrollo y fortalecimiento organizacional
10. Capacitación vocacional científica y no científica
11. Servicios de educación y capacitación en administración

## ÁREAS DE COMPETENCIA MEDIA — EVALUAR CASO A CASO
1. Investigación de mercados, análisis y ventas
2. Diseño artístico y producción de contenidos creativos
3. Equipos de presentación de video y sonido (AV)
4. Turismo educativo y eventos académicos y culturales
5. Desarrollo social, poblacional y cultural
6. Desarrollo urbano, regional y territorial
7. Servicios a organizaciones no gubernamentales (ONG)

## ÁREAS FUERA DEL PERFIL — RECHAZO AUTOMÁTICO
1. Construcción civil, obras de infraestructura física
2. Suministro de alimentos, víveres o bienes físicos de consumo
3. Servicios de aseo, limpieza y mantenimiento general
4. Vigilancia y seguridad física
5. Transporte de carga o pasajeros
6. Fabricación, manufactura o ensamble de productos
7. Explotación de recursos naturales o servicios ambientales de campo
8. Servicios de salud clínica o asistencia médica directa

## CÓDIGOS UNSPSC CON EXPERIENCIA ACREDITADA EN RUP
- 45111800 – Equipos de presentación de video y sonido
- 60101100 – Materiales educativos (general)
- 60105200 – Materiales de aprendizaje interactivo
- 60105300 – Materiales educativos de ciencias
- 60105400 – Materiales educativos de arte
- 60105600 – Materiales educativos de tecnología
- 80101500 – Servicios de consultoría de negocios y administración corporativa
- 80101600 – Gerencia de proyectos
- 80101700 – Gerencia industrial
- 80111500 – Desarrollo de recursos humanos
- 80141500 – Investigación de mercados
- 80141600 – Ventas y promoción de negocios
- 80141900 – Asistencia técnica organizacional
- 81111500 – Ingeniería de software
- 81131500 – Metodología y análisis de sistemas
- 81161500 – Administración de accesos y seguridad lógica
- 82141500 – Servicios de diseño artístico
- 84101500 – Asistencia para el desarrollo
- 86101500 – Capacitación vocacional científica
- 86101700 – Capacitación vocacional no científica
- 86101800 – Educación y formación especializada
- 86111500 – Servicios de aprendizaje a distancia
- 86111600 – Educación de adultos
- 86121700 – Universidades y politécnicos
- 86132000 – Educación y capacitación en administración
- 86141500 – Servicios de guía educacional
- 86141700 – Tecnología educacional
- 90121500 – Actividades turísticas
- 90151800 – Eventos culturales
- 93141500 – Desarrollo social
- 93141600 – Desarrollo poblacional
- 93141700 – Desarrollo cultural
- 93142000 – Desarrollo urbano
- 93142100 – Desarrollo regional
- 94131500 – Organizaciones no gubernamentales
"""

# =============================================================================
# CATÁLOGOS UNSPSC
# =============================================================================
UNSPSC_PERFIL: dict[str, str] = {
    "86": "Educación y Formación",
    "80": "Consultoría y Gestión Empresarial",
    "81": "Ingeniería, Investigación y Tecnología",
    "60": "Materiales y Recursos Educativos",
    "45": "Equipos AV y Presentación",
    "82": "Diseño y Servicios Creativos",
    "84": "Asistencia para el Desarrollo",
    "93": "Desarrollo Social, Urbano y Regional",
    "90": "Turismo y Cultura",
    "94": "Organizaciones No Gubernamentales",
    "43": "TIC — Software e Infraestructura",
    "55": "Publicaciones y Medios",
}

UNSPSC_PREFIJOS_VALIDOS: list[str] = list(UNSPSC_PERFIL.keys())

UNSPSC_CODIGOS_EXACTOS: set[str] = {
    "45111800", "60101100", "60105200", "60105300", "60105400", "60105600",
    "80101500", "80101600", "80101700", "80111500", "80141500", "80141600",
    "80141900", "81111500", "81131500", "81161500", "82141500", "84101500",
    "86101500", "86101700", "86101800", "86111500", "86111600", "86121700",
    "86132000", "86141500", "86141700", "90121500", "90151800", "93141500",
    "93141600", "93141700", "93142000", "93142100", "94131500",
}

# Términos que causan descarte inmediato
PALABRAS_NEGATIVAS: list[str] = [
    "construcci", "paviment", "alcantarill", "acueduct", "vial",
    "suministro de alimento", "dotaci", "aseo y limpieza", "vigilancia y seguridad",
    "transporte de carga", "fabricaci", "manufactura", "obra civil",
    "material de ferretería", "mantenimiento locativo", "mobiliario",
    "excavaci", "demolici", "impermeabiliz", "carpintería",
]

# Términos que confirman alineación con el perfil
PALABRAS_POSITIVAS: list[str] = [
    "educaci", "formaci", "capacitaci", "consultor", "tecnolog", "software",
    "sistema de informaci", "interventor", "investigaci", "docente", "académic",
    "virtual", "e-learning", "plataforma", "tic", "digital", "curricular",
    "competencias", "certificaci", "entrenamiento", "aprendizaje", "bienestar",
    "posgrado", "pregrado", "extensi", "innovaci", "transferencia",
    "pedagogía", "pedagóg", "didáct", "escolaridad", "alfabetizaci",
    "administraci", "gerencia", "gestión", "proyecto", "recurso humano",
    "fortalecimiento institucional", "desarrollo organizacional",
    "social", "territorial", "cultural", "comunitario", "poblacional",
    "diseño artístic", "contenido", "material educativo",
]

# Campos requeridos en la respuesta JSON del análisis
_CAMPOS_REQUERIDOS_ANALISIS = {
    "viabilidad", "porcentaje_aplicabilidad", "score_financiero",
    "nivel_competencia", "fortalezas", "riesgos", "recomendacion",
}

_VIABILIDADES_VALIDAS = {"VIABLE", "REQUIERE AJUSTES", "NO VIABLE"}
_COMPETENCIAS_VALIDAS = {"BAJO", "MEDIO", "ALTO"}

# Datos duros del proceso: SIEMPRE se sobrescriben con los valores reales de
# SECOP II. Los modelos locales pequeños tienden a reescribir o inventar estos
# campos aunque el prompt se los entregue literalmente.
_CAMPOS_FACTUALES = (
    "id_oferta", "entidad", "codigo_unspsc", "valor_estimado",
    "duracion_contrato", "modalidad", "fecha_cierre", "enlace_secop", "motor_ia",
)


# =============================================================================
# HELPERS DE NORMALIZACIÓN
# =============================================================================
def _texto_oferta(oferta: dict) -> str:
    """Concatena en minúsculas los campos textuales relevantes de una oferta."""
    return " ".join([
        str(oferta.get("descripci_n_del_procedimiento") or "").lower(),
        str(oferta.get("nombre_del_procedimiento") or "").lower(),
    ])


def _parsear_fecha(valor: Any) -> datetime | None:
    """Parsea fechas de Socrata (ISO, con 'Z', con milisegundos) de forma segura."""
    if not valor:
        return None
    texto = str(valor).strip().replace("Z", "+00:00").split(".")[0]
    for fmt in (None, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            fecha = datetime.fromisoformat(texto) if fmt is None else datetime.strptime(texto, fmt)
            return fecha.replace(tzinfo=None)
        except (ValueError, TypeError):
            continue
    return None


def _a_entero(valor: Any, defecto: int = 0, minimo: int = 0, maximo: int = 100) -> int:
    """Convierte a int acotado. La IA a veces devuelve '85%', '85.0' o None."""
    try:
        if isinstance(valor, str):
            valor = re.sub(r"[^\d.\-]", "", valor) or defecto
        numero = int(round(float(valor)))
    except (ValueError, TypeError):
        numero = defecto
    return max(minimo, min(maximo, numero))


def _a_lista(valor: Any) -> list[str]:
    """Garantiza una lista de strings (la IA a veces devuelve un string suelto)."""
    if isinstance(valor, list):
        return [str(x).strip() for x in valor if str(x).strip()]
    if isinstance(valor, str) and valor.strip():
        return [valor.strip()]
    return []


# =============================================================================
# PRE-FILTRO INTELIGENTE (sin IA, sin red — O(n·k))
# =============================================================================
def es_oferta_relevante(oferta: dict) -> bool:
    """
    Determina si una oferta es relevante según su texto y su código UNSPSC.

    Orden de evaluación:
      1. Palabra negativa  → descarte inmediato.
      2. Código UNSPSC exacto del RUP → aprobación inmediata.
      3. Prefijo de familia válido → aprobación.
      4. Sin código relevante → exigir al menos una palabra positiva.
    """
    texto_completo = _texto_oferta(oferta)

    if any(neg in texto_completo for neg in PALABRAS_NEGATIVAS):
        return False

    codigo = str(oferta.get("codigo_principal_de_categoria") or "").strip()

    if codigo in UNSPSC_CODIGOS_EXACTOS:
        return True

    if len(codigo) >= 2 and codigo[:2] in UNSPSC_PREFIJOS_VALIDOS:
        return True

    return any(p in texto_completo for p in PALABRAS_POSITIVAS)


# =============================================================================
# SCORE DE PRIORIDAD PRE-IA (metadatos únicamente)
# =============================================================================
def calcular_score_previo(oferta: dict) -> float:
    """
    Score compuesto (0–100) para priorizar qué ofertas analizar primero
    sin consumir llamadas a la IA.

    Factores:
        - Código UNSPSC exacto en RUP : +40 pts
        - Prefijo de familia válido   : +20 pts
        - Palabras positivas          : hasta +30 pts (3 pts c/u, máx 10 matches)
        - Urgencia de cierre          : hasta +30 pts
    """
    score  = 0.0
    codigo = str(oferta.get("codigo_principal_de_categoria") or "").strip()
    texto  = _texto_oferta(oferta)

    if codigo in UNSPSC_CODIGOS_EXACTOS:
        score += 40
    elif len(codigo) >= 2 and codigo[:2] in UNSPSC_PREFIJOS_VALIDOS:
        score += 20

    matches = sum(1 for p in PALABRAS_POSITIVAS if p in texto)
    score  += min(matches * 3, 30)

    fecha_obj = _parsear_fecha(oferta.get("fecha_de_recepcion_de"))
    if fecha_obj:
        dias = (fecha_obj - datetime.now()).days
        if   0 <= dias <= 3:  score += 30
        elif 0 <= dias <= 7:  score += 20
        elif 0 <= dias <= 15: score += 10

    return round(score, 1)


# =============================================================================
# DIAGNÓSTICO DE CONEXIONES
# =============================================================================
def diagnosticar_api() -> dict:
    """Prueba la conectividad con Socrata sin filtros."""
    resultado: dict[str, Any] = {
        "conexion_ok"     : False,
        "total_sin_filtro": 0,
        "muestra_estados" : [],
        "muestra_ids"     : [],
        "error"           : None,
    }
    try:
        muestra = socrata_client.get(
            DATASET_ID, limit=5, order="fecha_de_publicacion_del DESC"
        )
        resultado["conexion_ok"]      = True
        resultado["total_sin_filtro"] = len(muestra)
        resultado["muestra_estados"]  = sorted({
            str(r.get("estado_de_apertura_del_proceso", "N/A")) for r in muestra
        })
        resultado["muestra_ids"] = [r.get("id_del_proceso", "?") for r in muestra]
        logger.info("Diagnóstico Socrata OK — %d registros de muestra.", len(muestra))
    except Exception as exc:
        resultado["error"] = str(exc)
        logger.error("Diagnóstico Socrata FALLIDO: %s", exc)
    return resultado


def diagnosticar_ollama() -> dict:
    """
    Verifica el estado del motor local: servidor activo, modelos instalados
    y latencia de la consulta.
    """
    resultado: dict[str, Any] = {
        "servidor_ok": False,
        "host"       : OLLAMA_HOST,
        "modelos"    : [],
        "latencia_ms": None,
        "error"      : None,
    }
    try:
        inicio = time.perf_counter()
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=OLLAMA_PING_TIMEOUT)
        r.raise_for_status()
        resultado["latencia_ms"] = int((time.perf_counter() - inicio) * 1000)
        resultado["servidor_ok"] = True
        resultado["modelos"]     = sorted(
            m.get("name", "") for m in (r.json().get("models") or []) if m.get("name")
        )
        logger.info("Diagnóstico Ollama OK — %d modelos.", len(resultado["modelos"]))
    except requests.RequestException as exc:
        resultado["error"] = f"No hay respuesta de {OLLAMA_HOST}. ¿Ejecutaste `ollama serve`? ({exc})"
        logger.error("Diagnóstico Ollama FALLIDO: %s", exc)
    except Exception as exc:
        resultado["error"] = str(exc)
        logger.error("Diagnóstico Ollama FALLIDO: %s", exc)
    return resultado


# =============================================================================
# OBTENER OFERTAS DE SECOP II — Estrategia en cascada
# =============================================================================
def obtener_ofertas_secop(
    limite: int = 10,
    palabra_clave: str | None = None,
    codigos_unspsc: list[str] | None = None,
) -> list[dict]:
    """
    Descarga ofertas del SECOP II con estrategia de consulta en cascada:
    - Estrategia 1 (óptima)    : UNSPSC + texto + fecha reciente
    - Estrategia 2 (fallback)  : UNSPSC + fecha reciente
    - Estrategia 3 (mínima)    : Fecha reciente (+ texto si lo hay)
    - Estrategia 4 (emergencia): Sin filtros

    El filtro de `estado_de_apertura_del_proceso` se aplica LOCAL porque los
    valores varían en el dataset real y una comparación exacta en SoQL puede
    devolver 0 resultados silenciosamente.
    """
    limite = max(1, int(limite))
    buffer = min(limite * BUFFER_MULTIPLIER, MAX_BUFFER)

    fecha_corte = (datetime.now() - timedelta(days=DIAS_HISTORICO)).strftime(
        "%Y-%m-%dT00:00:00"
    )

    # Solo códigos numéricos: evita inyección en la cláusula SoQL.
    codigos_validos = [c for c in (codigos_unspsc or []) if str(c).strip().isdigit()]
    like_clauses: str | None = None
    if codigos_validos:
        like_clauses = " OR ".join(
            f"codigo_principal_de_categoria LIKE '{c}%'" for c in codigos_validos
        )

    texto = (palabra_clave or "").strip()
    q_param: dict[str, str] = {"q": texto} if texto else {}

    base_where   = f"fecha_de_publicacion_del >= '{fecha_corte}'"
    where_unspsc = base_where + (f" AND ({like_clauses})" if like_clauses else "")
    orden = "fecha_de_publicacion_del DESC"

    estrategias: list[tuple[str, dict[str, Any]]] = [
        ("1 — UNSPSC+fecha+palabra", {"where": where_unspsc, **q_param}),
        ("2 — UNSPSC+fecha",         {"where": where_unspsc}),
        ("3 — solo fecha",           {"where": base_where, **q_param}),
        ("4 — sin filtros",          {}),
    ]

    # Evita repetir consultas idénticas (p. ej. sin palabra clave, 1 == 2).
    estrategias_unicas: list[tuple[str, dict[str, Any]]] = []
    vistas: set[str] = set()
    for descripcion, params in estrategias:
        firma = json.dumps(params, sort_keys=True, ensure_ascii=False)
        if firma not in vistas:
            vistas.add(firma)
            estrategias_unicas.append((descripcion, params))

    resultados_brutos: list[dict] = []
    estrategia_usada = "ninguna"

    for descripcion, params_extra in estrategias_unicas:
        try:
            respuesta = socrata_client.get(
                DATASET_ID, order=orden, limit=buffer, **params_extra
            )
            logger.info("Socrata [%s] — %d registros descargados.", descripcion, len(respuesta))
            if respuesta:
                resultados_brutos = list(respuesta)
                estrategia_usada  = descripcion
                break
        except Exception as exc:
            logger.warning("Socrata estrategia %s falló: %s", descripcion, exc)

    if not resultados_brutos:
        logger.error("Todas las estrategias Socrata fallaron o no hubo resultados.")
        return []

    limpios   = [r for r in resultados_brutos if es_oferta_relevante(r)]
    ordenados = sorted(limpios, key=calcular_score_previo, reverse=True)

    logger.info(
        "Pipeline Socrata → estrategia: %s | descargados: %d | "
        "post-filtro: %d | enviando a IA: %d",
        estrategia_usada, len(resultados_brutos), len(limpios), min(len(ordenados), limite),
    )
    return ordenados[:limite]


# =============================================================================
# HELPERS MULTI-MODELO
# =============================================================================
def _limpiar_respuesta_reasoning(texto: str) -> str:
    """Elimina bloques <think> de modelos de razonamiento y backticks markdown."""
    if not texto:
        return ""

    # 1. Borrar el bloque si está cerrado correctamente
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL | re.IGNORECASE)

    # 2. Si el bloque quedó abierto (truncado), intentar recuperar el JSON final
    if "<think>" in texto.lower() and "</think>" not in texto.lower():
        partes = texto.split("```json")
        texto = partes[-1] if len(partes) > 1 else re.sub(r"<think>", "", texto, flags=re.IGNORECASE)

    # 3. Limpiar backticks de markdown
    texto = re.sub(r"```(?:json)?\s*", "", texto)
    texto = texto.replace("```", "")
    return texto.strip()


def _extraer_json_de_texto(texto: str) -> str:
    """
    Extrae un objeto JSON de una cadena con texto libre alrededor.
    Busca el primer '{' y el último '}' y retorna el fragmento entre ambos.
    """
    inicio = texto.find("{")
    fin    = texto.rfind("}")
    if inicio != -1 and fin != -1 and fin > inicio:
        return texto[inicio: fin + 1]
    return texto


def _validar_analisis(datos: Any) -> bool:
    """Verifica que la IA devolvió un dict con los campos mínimos requeridos."""
    if not isinstance(datos, dict):
        logger.warning("La IA no devolvió un objeto JSON (tipo: %s).", type(datos).__name__)
        return False
    faltantes = _CAMPOS_REQUERIDOS_ANALISIS - datos.keys()
    if faltantes:
        logger.warning("Análisis IA incompleto — faltan campos: %s", sorted(faltantes))
        return False
    return True


def _normalizar_analisis(datos: dict, defaults: dict) -> dict:
    """
    Normaliza tipos y fuerza los datos factuales reales del proceso.
    Especialmente importante con modelos locales pequeños, que son más laxos
    respetando el esquema y tienden a reescribir IDs y nombres de entidad.
    """
    normalizado = dict(datos)

    viabilidad = str(normalizado.get("viabilidad", "")).strip().upper()
    normalizado["viabilidad"] = viabilidad if viabilidad in _VIABILIDADES_VALIDAS else "NO VIABLE"

    competencia = str(normalizado.get("nivel_competencia", "")).strip().upper()
    normalizado["nivel_competencia"] = competencia if competencia in _COMPETENCIAS_VALIDAS else "MEDIO"

    normalizado["porcentaje_aplicabilidad"] = _a_entero(normalizado.get("porcentaje_aplicabilidad"))
    normalizado["score_financiero"]         = _a_entero(normalizado.get("score_financiero"))

    for campo in ("fortalezas", "riesgos", "acciones_mejora"):
        normalizado[campo] = _a_lista(normalizado.get(campo))

    normalizado["recomendacion"] = str(normalizado.get("recomendacion") or "").strip()
    normalizado["match_unspsc_rup"] = bool(defaults.get("match_unspsc_rup"))

    # Datos duros → siempre los reales de SECOP II (anti-alucinación).
    for campo in _CAMPOS_FACTUALES:
        if campo in defaults:
            normalizado[campo] = defaults[campo]

    # Campos redactados por la IA → solo se rellenan si vinieron vacíos.
    for campo, valor in defaults.items():
        if campo in _CAMPOS_FACTUALES or campo == "match_unspsc_rup":
            continue
        if not str(normalizado.get(campo) or "").strip():
            normalizado[campo] = valor

    return normalizado


def llamar_proveedor(
    prompt: str,
    modelo_cfg: dict,
    json_mode: bool = True,
) -> str:
    """
    Router central con retry y backoff exponencial. Dirige la llamada al
    motor correcto (Ollama local o Gemini) y retorna siempre un STRING.

    Raises:
        ErrorConfiguracion: Credenciales ausentes, servidor local caído, modelo
                            no instalado o proveedor desconocido (sin retry).
        RuntimeError      : Si todos los reintentos fallan.
    """
    proveedor    = modelo_cfg["proveedor"]
    model_id     = modelo_cfg["model_id"]
    json_ok      = modelo_cfg.get("soporta_json_mode", True)
    es_reasoning = modelo_cfg.get("es_reasoning", False)

    if proveedor == "gemini" and gemini_client is None:
        raise ErrorConfiguracion(
            "GOOGLE_API_KEY (API_KEY_GEMINI_MIA) no está configurada o falta el SDK de Google. "
            "Usa el motor local de Ollama o agrega la clave en tu .env"
        )
    if proveedor not in ("ollama", "gemini"):
        raise ErrorConfiguracion(f"Proveedor desconocido: '{proveedor}'")

    ultimo_error: Exception | None = None

    for intento in range(1, MAX_RETRY + 1):
        try:
            # ── Ollama (IA local) ─────────────────────────────────────────────
            if proveedor == "ollama":
                texto = _llamar_ollama(prompt, model_id, json_mode and json_ok)
                return _limpiar_respuesta_reasoning(texto) if es_reasoning else texto

            # ── Gemini (Google AI Studio) ─────────────────────────────────────
            config_gemini: dict[str, Any] = {}
            if json_mode and json_ok:
                config_gemini["response_mime_type"] = "application/json"

            response = gemini_client.models.generate_content(
                model    = model_id,
                contents = prompt,
                config   = config_gemini or None,
            )
            return getattr(response, "text", "") or ""

        except ErrorConfiguracion:
            raise
        except Exception as exc:
            ultimo_error = exc
            logger.warning(
                "Intento %d/%d fallido para %s — %s.", intento, MAX_RETRY, model_id, exc
            )
            if intento < MAX_RETRY:
                # Local: el fallo no es por cuota, no hace falta esperar tanto.
                base = 0.5 if proveedor == "ollama" else RETRY_BASE_DELAY
                wait = min(base * (2 ** (intento - 1)), RETRY_MAX_DELAY)
                logger.warning("Reintentando en %.1f s.", wait)
                time.sleep(wait)

    raise RuntimeError(
        f"Todos los {MAX_RETRY} intentos fallaron para {model_id}. "
        f"Último error: {ultimo_error}"
    )


# =============================================================================
# ANÁLISIS IA — PROMPT ENRIQUECIDO CON PERFIL REAL
# =============================================================================
def analizar_oferta_ia(
    oferta: dict,
    modelo_cfg: dict | None = None,
) -> dict | None:
    """
    Evalúa una oferta con IA usando el perfil institucional real.

    Incluye:
    - Caché por modelo: no re-analiza el mismo proceso con el mismo modelo
    - Retry con backoff (corto en local, conservador en la nube)
    - Fallback de extracción JSON (busca primer '{' / último '}')
    - Validación y normalización de los campos devueltos
    """
    if modelo_cfg is None:
        modelo_cfg = MODELOS_DISPONIBLES[MODELO_DEFAULT_KEY]

    id_proceso = oferta.get("id_del_proceso") or "Desconocido"
    cache_key  = construir_cache_key(id_proceso, modelo_cfg)

    if cache_key in _cache_analisis:
        logger.debug("CACHÉ hit → %s (%s)", id_proceso, modelo_cfg["model_id"])
        return _cache_analisis[cache_key]

    # ── Extracción y normalización de campos ─────────────────────────────────
    entidad       = oferta.get("entidad") or "Entidad Desconocida"
    nombre_proc   = oferta.get("nombre_del_procedimiento") or "Sin nombre"
    descripcion   = oferta.get("descripci_n_del_procedimiento") or "Sin descripción"
    modalidad     = oferta.get("modalidad_de_contratacion") or "No especificada"
    tipo_contrato = oferta.get("tipo_de_contrato") or "No especificado"
    unspsc        = str(oferta.get("codigo_principal_de_categoria") or "").strip() or "No especificado"

    cats_adicionales = oferta.get("categorias_adicionales") or ""
    ciudad           = oferta.get("ciudad_entidad") or ""
    departamento     = oferta.get("departamento_entidad") or ""
    estado_proc      = oferta.get("estado_del_procedimiento") or ""

    prov_invitados    = oferta.get("proveedores_invitados") or "N/D"
    respuestas_recib  = oferta.get("respuestas_al_procedimiento") or "N/D"
    prov_manifestaron = oferta.get("proveedores_que_manifestaron") or "N/D"

    # Cuantía formateada
    try:
        cuantia_num = f"{float(oferta.get('precio_base') or 0):,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        cuantia_num = str(oferta.get("precio_base") or "No especificado")

    # Duración
    duracion       = oferta.get("duracion") or ""
    unidad_dur     = oferta.get("unidad_de_duracion") or ""
    duracion_texto = f"{duracion} {unidad_dur}".strip() or "No especificada"

    # Enlace
    url_info = oferta.get("urlproceso") or {}
    enlace   = (
        url_info.get("url", "Sin enlace")
        if isinstance(url_info, dict)
        else (str(url_info) or "Sin enlace")
    )

    # Fecha de cierre
    fecha_obj = _parsear_fecha(oferta.get("fecha_de_recepcion_de"))
    if fecha_obj:
        fecha_cierre = fecha_obj.strftime("%Y-%m-%d %H:%M")
    elif oferta.get("fecha_de_recepcion_de"):
        fecha_cierre = "Fecha inválida"
    else:
        fecha_cierre = "Sin fecha definida"

    # Contexto UNSPSC
    match_exacto  = unspsc in UNSPSC_CODIGOS_EXACTOS
    match_prefijo = len(unspsc) >= 2 and unspsc[:2] in UNSPSC_PREFIJOS_VALIDOS

    if match_exacto:
        contexto_unspsc = "COINCIDENCIA EXACTA CON RUP — experiencia directamente acreditada"
    elif match_prefijo:
        contexto_unspsc = "COINCIDENCIA POR FAMILIA — experiencia relacionada pero no exacta"
    else:
        contexto_unspsc = "SIN COINCIDENCIA DIRECTA EN RUP — evaluar capacidades transferibles"

    match_exacto_json = "true" if match_exacto else "false"

    # Valores de contexto que no deben depender de lo que invente la IA.
    defaults_contexto = {
        "id_oferta"        : str(id_proceso),
        "entidad"          : str(entidad),
        "codigo_unspsc"    : unspsc,
        "valor_estimado"   : cuantia_num,
        "duracion_contrato": duracion_texto,
        "modalidad"        : str(modalidad),
        "fecha_cierre"     : fecha_cierre,
        "enlace_secop"     : enlace,
        "objeto_contrato"  : str(nombre_proc)[:160],
        "categoria_unspsc" : UNSPSC_PERFIL.get(unspsc[:2], "No clasificada"),
        "match_unspsc_rup" : match_exacto,
        "motor_ia"         : f"{modelo_cfg['proveedor']}:{modelo_cfg['model_id']}",
    }

    prompt = f"""
Eres un analista senior de contratación estatal colombiana con expertise en SECOP II,
evaluación de capacidad institucional y análisis estratégico de propuestas públicas.

Tu misión: evaluar con criterio técnico, financiero y estratégico si el proponente
debe participar en este proceso contractual, dada su trayectoria real de 17 años y
más de 50 contratos ejecutados.

=====================================
PERFIL COMPLETO DEL PROPONENTE
=====================================
{PERFIL_UNIVERSIDAD}

=====================================
DATOS DEL PROCESO SECOP II
=====================================
- ID del Proceso           : {id_proceso}
- Nombre del Proceso       : {nombre_proc}
- Entidad Contratante      : {entidad}
- Ciudad / Departamento    : {ciudad}, {departamento}
- Objeto del Contrato      : {descripcion}
- Tipo de Contrato         : {tipo_contrato}
- Modalidad                : {modalidad}
- Valor Estimado           : ${cuantia_num} COP
- Duración                 : {duracion_texto}
- Código UNSPSC Principal  : {unspsc}
- Contexto UNSPSC          : {contexto_unspsc}
- Categorías Adicionales   : {cats_adicionales or "Ninguna"}
- Estado del Proceso       : {estado_proc}

INTELIGENCIA COMPETITIVA:
- Proveedores invitados    : {prov_invitados}
- Manifestaron interés     : {prov_manifestaron}
- Respuestas recibidas     : {respuestas_recib}

=====================================
INSTRUCCIONES DE ANÁLISIS
=====================================
Evalúa con criterio crítico y objetivo:

1. Alineación del objeto con capacidades ACREDITADAS EN RUP.
2. Viabilidad financiera: ¿el valor es coherente con el tamaño operativo?
   (Liquidez 1.36 y endeudamiento 0.59 — perfil financiero aceptable pero ajustado).
3. Competencia técnica: ¿tienen experiencia demostrable en >50 contratos para ganar?
4. Inteligencia competitiva: ¿es un proceso muy disputado o una oportunidad abierta?
5. Riesgos concretos (reputacionales, técnicos, financieros, cumplimiento).
6. Acciones ejecutables y específicas para preparar la propuesta.
7. score_financiero: 0-100 evaluando si el valor del contrato es apropiado para
   el tamaño financiero del proponente (muy bajo = subutilización; muy alto = riesgo).

REGLAS:
- Si el objeto es construcción, aseo, vigilancia o manufactura → viabilidad = "NO VIABLE" y porcentaje <= 10.
- Si el código UNSPSC coincide exactamente con el RUP → bonus de +15 puntos en porcentaje.
- porcentaje_aplicabilidad y score_financiero deben ser números enteros entre 0 y 100, sin símbolos.
- "viabilidad" debe ser exactamente uno de: VIABLE, REQUIERE AJUSTES, NO VIABLE.
- "nivel_competencia" debe ser exactamente uno de: BAJO, MEDIO, ALTO.
- "fortalezas", "riesgos" y "acciones_mejora" deben ser arreglos de strings.
- Sé específico. No uses frases genéricas. Cada fortaleza/riesgo debe mencionar
  elementos concretos del proceso evaluado.

RESPONDE ÚNICA Y ESTRICTAMENTE EN JSON. Sin texto antes ni después. Sin backticks.
{{
    "id_oferta"               : "{id_proceso}",
    "entidad"                 : "{entidad}",
    "objeto_contrato"         : "Resumen ejecutivo del objeto en máximo 15 palabras",
    "codigo_unspsc"           : "{unspsc}",
    "categoria_unspsc"        : "Nombre de la categoría UNSPSC en español",
    "viabilidad"              : "VIABLE | REQUIERE AJUSTES | NO VIABLE",
    "porcentaje_aplicabilidad": 0,
    "score_financiero"        : 0,
    "nivel_competencia"       : "BAJO | MEDIO | ALTO",
    "fortalezas"              : ["Fortaleza concreta 1 referenciando el proceso", "Fortaleza 2", "Fortaleza 3"],
    "riesgos"                 : ["Riesgo concreto 1", "Riesgo 2"],
    "acciones_mejora"         : ["Acción ejecutable específica 1", "Acción 2", "Acción 3"],
    "recomendacion"           : "Párrafo ejecutivo máximo 3 líneas: veredicto + justificación estratégica + próximo paso.",
    "valor_estimado"          : "{cuantia_num}",
    "duracion_contrato"       : "{duracion_texto}",
    "modalidad"               : "{modalidad}",
    "fecha_cierre"            : "{fecha_cierre}",
    "enlace_secop"            : "{enlace}",
    "match_unspsc_rup"        : {match_exacto_json}
}}
"""

    texto_respuesta = ""
    try:
        texto_respuesta = llamar_proveedor(
            prompt=prompt, modelo_cfg=modelo_cfg, json_mode=True,
        )

        if modelo_cfg.get("es_reasoning", False):
            texto_respuesta = _limpiar_respuesta_reasoning(texto_respuesta)

        # Intento 1: parseo directo
        try:
            analisis_dict = json.loads(texto_respuesta)
        except json.JSONDecodeError:
            # Intento 2: extraer el primer objeto JSON del texto
            logger.warning(
                "JSON directo falló para %s — intentando extracción por heurística.", id_proceso
            )
            analisis_dict = json.loads(_extraer_json_de_texto(texto_respuesta))

        if not _validar_analisis(analisis_dict):
            logger.warning("Análisis de %s descartado por campos incompletos.", id_proceso)
            return None

        analisis_dict = _normalizar_analisis(analisis_dict, defaults_contexto)

        _cache_analisis[cache_key] = analisis_dict
        logger.info("OK — %s analizado con %s.", id_proceso, modelo_cfg["model_id"])
        return analisis_dict

    except json.JSONDecodeError as exc:
        logger.error(
            "JSON inválido para %s: %s | Respuesta (primeros %d chars): %s",
            id_proceso, exc, JSON_PARSE_MAXLEN, texto_respuesta[:JSON_PARSE_MAXLEN],
        )
        return None
    except ErrorConfiguracion as exc:
        logger.error("Configuración inválida al analizar %s: %s", id_proceso, exc)
        raise
    except RuntimeError as exc:
        logger.error("Sin respuesta IA para %s: %s", id_proceso, exc)
        return None
    except Exception as exc:
        logger.error("Error inesperado en %s (%s): %s", id_proceso, modelo_cfg["model_id"], exc)
        return None


# =============================================================================
# ANÁLISIS SECUENCIAL
# =============================================================================
def analizar_ofertas_secuencial(
    ofertas: list[dict],
    delay_segundos: float = 0.0,
    callback_progreso: Callable | None = None,
    modelo_cfg: dict | None = None,
) -> list[dict]:
    """
    Analiza ofertas de forma secuencial con delay configurable entre llamadas.

    - Con el motor local el delay puede ser 0: no hay cuota que respetar.
    - Las ofertas en caché se saltan el delay.
    - Un error de configuración (servidor caído, API key ausente) corta el lote.
    """
    if modelo_cfg is None:
        modelo_cfg = MODELOS_DISPONIBLES[MODELO_DEFAULT_KEY]

    resultados: list[dict] = []
    total    = len(ofertas)
    model_id = modelo_cfg["model_id"]

    for i, oferta in enumerate(ofertas):
        id_proc  = oferta.get("id_del_proceso") or "?"
        en_cache = construir_cache_key(id_proc, modelo_cfg) in _cache_analisis

        if callback_progreso:
            callback_progreso(i, total, id_proc, en_cache)

        try:
            resultado = analizar_oferta_ia(oferta, modelo_cfg=modelo_cfg)
        except ErrorConfiguracion as exc:
            logger.error("Lote interrumpido — %s", exc)
            break

        if resultado:
            resultados.append(resultado)

        # Delay solo en llamadas reales (no caché) y si no es la última
        if not en_cache and i < total - 1 and delay_segundos > 0:
            time.sleep(delay_segundos)

    if callback_progreso:
        callback_progreso(total, total, "✓ Completado", False)

    logger.info(
        "Análisis batch completado — %d/%d exitosos con %s.",
        len(resultados), total, model_id,
    )
    return resultados


# =============================================================================
# RESUMEN EJECUTIVO IA
# =============================================================================
def generar_resumen_ejecutivo(
    resultados: list[dict],
    modelo_cfg: dict | None = None,
) -> str:
    """
    Genera un resumen ejecutivo estratégico (150-250 palabras) de todas las
    ofertas analizadas, con recomendaciones de priorización.
    """
    if modelo_cfg is None:
        modelo_cfg = MODELOS_DISPONIBLES[MODELO_DEFAULT_KEY]

    if not resultados:
        return "No hay resultados para generar resumen."

    viables   = [r for r in resultados if r.get("viabilidad") == "VIABLE"]
    ajustes   = [r for r in resultados if r.get("viabilidad") == "REQUIERE AJUSTES"]
    no_viable = [r for r in resultados if r.get("viabilidad") == "NO VIABLE"]

    prom_aplicabilidad = int(
        sum(_a_entero(r.get("porcentaje_aplicabilidad")) for r in resultados) / len(resultados)
    )

    top_3 = sorted(
        viables, key=lambda x: _a_entero(x.get("porcentaje_aplicabilidad")), reverse=True
    )[:3]

    resumen_data = {
        "total_analizados"      : len(resultados),
        "viables"               : len(viables),
        "requieren_ajustes"     : len(ajustes),
        "no_viables"            : len(no_viable),
        "promedio_aplicabilidad": prom_aplicabilidad,
        "top_3_oportunidades"   : [
            {
                "id"        : r.get("id_oferta"),
                "entidad"   : r.get("entidad"),
                "objeto"    : r.get("objeto_contrato"),
                "pct"       : r.get("porcentaje_aplicabilidad"),
                "valor"     : r.get("valor_estimado"),
                "fecha_cie" : r.get("fecha_cierre"),
            }
            for r in top_3
        ],
    }

    prompt = f"""
Eres el director de gestión contractual de una organización con 17 años de experiencia
y más de 50 contratos en educación, consultoría y tecnología.

Acabas de recibir los resultados de un análisis automático de oportunidades SECOP II.
Tu tarea: redactar un resumen ejecutivo claro y accionable para el equipo directivo.

DATOS DEL ANÁLISIS:
{json.dumps(resumen_data, ensure_ascii=False, indent=2)}

INSTRUCCIONES:
- Redacta entre 150 y 250 palabras.
- Inicia con la situación actual del mercado según los resultados.
- Destaca las 3 mejores oportunidades y por qué.
- Incluye una recomendación estratégica de priorización.
- Cierra con el próximo paso operativo concreto.
- Usa un tono ejecutivo, sin tecnicismos innecesarios.
- Responde en español colombiano formal, en texto plano (no JSON).
"""

    try:
        texto_resumen = llamar_proveedor(
            prompt=prompt, modelo_cfg=modelo_cfg, json_mode=False,
        )
        return texto_resumen.strip() or "No se pudo generar el resumen ejecutivo automático."
    except Exception as exc:
        logger.error("Error al generar resumen ejecutivo (%s): %s", modelo_cfg["model_id"], exc)
        return "No se pudo generar el resumen ejecutivo automático."


# =============================================================================
# GESTIÓN DE CACHÉ
# =============================================================================
def construir_cache_key(id_proceso: Any, modelo_cfg: dict | None = None) -> str:
    """Clave de caché pública: evita que la UI dependa de `_cache_analisis`."""
    if modelo_cfg is None:
        modelo_cfg = MODELOS_DISPONIBLES[MODELO_DEFAULT_KEY]
    return f"{id_proceso}_{modelo_cfg['model_id']}"


def esta_en_cache(id_proceso: Any, modelo_cfg: dict | None = None) -> bool:
    """Indica si un proceso ya fue analizado con el modelo indicado."""
    return construir_cache_key(id_proceso, modelo_cfg) in _cache_analisis


def limpiar_cache() -> None:
    """Limpia el caché de análisis en memoria (in-place, sin romper referencias)."""
    _cache_analisis.clear()
    logger.info("Caché de análisis limpiado.")


def obtener_stats_cache() -> dict[str, int]:
    """Retorna estadísticas básicas del caché actual."""
    return {"total_entradas": len(_cache_analisis)}


# =============================================================================
# EXPORTAR REPORTE A EXCEL (dos hojas: detalle + resumen)
# =============================================================================
def exportar_reporte_excel(resultados: list[dict]) -> bytes:
    """
    Convierte la lista de análisis a un archivo Excel con dos hojas:
    1. Análisis Detallado — una fila por proceso con todos los campos
    2. Resumen Ejecutivo  — métricas agregadas del batch
    """
    if not resultados:
        return b""

    def prioridad_icon(r: dict) -> str:
        v = r.get("viabilidad", "")
        return "⭐" if v == "VIABLE" else ("🔶" if v == "REQUIERE AJUSTES" else "❌")

    filas = [
        {
            "Prioridad"            : prioridad_icon(r),
            "ID Proceso"           : r.get("id_oferta", ""),
            "Entidad"              : r.get("entidad", ""),
            "Objeto del Contrato"  : r.get("objeto_contrato", ""),
            "Código UNSPSC"        : r.get("codigo_unspsc", ""),
            "Categoría UNSPSC"     : r.get("categoria_unspsc", ""),
            "¿Match RUP Exacto?"   : "Sí" if r.get("match_unspsc_rup") else "No",
            "Viabilidad"           : r.get("viabilidad", ""),
            "% Aplicabilidad"      : _a_entero(r.get("porcentaje_aplicabilidad")),
            "Score Financiero"     : _a_entero(r.get("score_financiero")),
            "Nivel de Competencia" : r.get("nivel_competencia", ""),
            "Valor Estimado (COP)" : r.get("valor_estimado", ""),
            "Duración del Contrato": r.get("duracion_contrato", ""),
            "Modalidad"            : r.get("modalidad", ""),
            "Fecha Cierre"         : r.get("fecha_cierre", ""),
            "Fortalezas"           : " | ".join(_a_lista(r.get("fortalezas"))),
            "Riesgos"              : " | ".join(_a_lista(r.get("riesgos"))),
            "Acciones de Mejora"   : " | ".join(_a_lista(r.get("acciones_mejora"))),
            "Recomendación IA"     : r.get("recomendacion", ""),
            "Motor IA"             : r.get("motor_ia", ""),
            "Enlace SECOP"         : r.get("enlace_secop", ""),
        }
        for r in resultados
    ]

    df = pd.DataFrame(filas).sort_values("% Aplicabilidad", ascending=False)

    viables    = sum(1 for r in resultados if r.get("viabilidad") == "VIABLE")
    ajustes    = sum(1 for r in resultados if r.get("viabilidad") == "REQUIERE AJUSTES")
    no_viables = len(resultados) - viables - ajustes
    prom_pct   = int(
        sum(_a_entero(r.get("porcentaje_aplicabilidad")) for r in resultados) / len(resultados)
    )
    motores = sorted({str(r.get("motor_ia") or "") for r in resultados} - {""})

    df_resumen = pd.DataFrame([
        {"Métrica": "Total Procesos Analizados",  "Valor": len(resultados)},
        {"Métrica": "Procesos VIABLES",           "Valor": viables},
        {"Métrica": "Procesos REQUIEREN AJUSTES", "Valor": ajustes},
        {"Métrica": "Procesos NO VIABLES",        "Valor": no_viables},
        {"Métrica": "% Aplicabilidad Promedio",   "Valor": f"{prom_pct}%"},
        {"Métrica": "Motor(es) de IA",            "Valor": ", ".join(motores) or "N/D"},
        {"Métrica": "Fecha de Generación",        "Valor": datetime.now().strftime("%Y-%m-%d %H:%M")},
    ])

    buffer = io.BytesIO()
    try:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Análisis Detallado")
            df_resumen.to_excel(writer, index=False, sheet_name="Resumen Ejecutivo")

            for sheet_name in writer.sheets:
                ws = writer.sheets[sheet_name]
                for col in ws.columns:
                    celdas = list(col)
                    if not celdas:
                        continue
                    max_len = max((len(str(c.value or "")) for c in celdas), default=10)
                    ws.column_dimensions[celdas[0].column_letter].width = min(max_len + 4, 65)
    except Exception as exc:
        logger.error("Error al exportar Excel: %s", exc)
        return b""

    return buffer.getvalue()