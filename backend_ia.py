# =============================================================================
# backend_ia.py — Motor de análisis SECOP II con IA
# Versión 4.0 — Multi-modelo · Perfil real · Caché · Rate-limit seguro
# Mejoras: retry con backoff, logging robusto, validación de respuestas,
# Tipado completo, constantes centralizadas, manejo de errores mejorado
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
from dotenv import load_dotenv
from google import genai
from groq import Groq
from sodapy import Socrata

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

GROQ_API_KEY:   str | None = os.environ.get("GROQ_API_KEY")
GOOGLE_API_KEY: str | None = os.environ.get("API_KEY_GEMINI_MIA")
TOKEN:          str | None = os.environ.get("TOKEN")  # Socrata SECOP II

# =============================================================================
# CONSTANTES DE CONFIGURACIÓN
# =============================================================================
DATASET_ID        = "p6dx-8zbt"
DIAS_HISTORICO    = 90     # Ventana de búsqueda en días
BUFFER_MULTIPLIER = 10     # Factor de buffer al descargar ofertas
MAX_BUFFER        = 800    # Máximo de registros descargados por petición
MAX_RETRY         = 3      # Intentos máximos ante errores de API
RETRY_BASE_DELAY  = 2.0    # Delay base de backoff exponencial (segundos)
JSON_PARSE_MAXLEN = 300    # Caracteres de respuesta cruda en logs de error

# =============================================================================
# INICIALIZACIÓN DE CLIENTES
# =============================================================================
groq_client: Groq = Groq(api_key=GROQ_API_KEY)

gemini_client: genai.Client | None = None
if GOOGLE_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
        logger.info("Cliente Gemini inicializado correctamente.")
    except Exception as exc:
        logger.warning("No se pudo inicializar Gemini: %s", exc)

socrata_client: Socrata = Socrata("www.datos.gov.co", TOKEN)

# =============================================================================
# CACHÉ EN MEMORIA
# Clave: "{id_proceso}_{model_id}" → re-analiza al cambiar de modelo
# =============================================================================
_cache_analisis: dict[str, dict] = {}

# =============================================================================
# CATÁLOGO DE MODELOS DISPONIBLES
# =============================================================================
MODELOS_DISPONIBLES: dict[str, dict[str, Any]] = {
    "🦙 LLaMA 3.3 70B — Groq": {
        "proveedor"        : "groq",
        "model_id"         : "llama-3.3-70b-versatile",
        "descripcion"      : "Modelo base. Rápido, equilibrado y gratuito vía Groq.",
        "soporta_json_mode": True,
        "es_reasoning"     : False,
        "delay_recomendado": 2.0,
    },
    "🦙 LLaMA 4 Scout — Groq": {
        "proveedor"        : "groq",
        "model_id"         : "meta-llama/llama-4-scout-17b-16e-instruct",
        "descripcion"      : "Última generación de Meta. Multimodal y muy eficiente.",
        "soporta_json_mode": True,
        "es_reasoning"     : False,
        "delay_recomendado": 2.0,
    },
    "🐋 DeepSeek R1 — Groq": {
        "proveedor"        : "groq",
        "model_id"         : "deepseek-r1-distill-llama-70b",
        "descripcion"      : "Razonamiento profundo paso a paso. Más reflexivo pero lento.",
        "soporta_json_mode": False,  # Sus <think> tokens rompen el parser JSON de Groq
        "es_reasoning"     : True,
        "delay_recomendado": 2.0,
    },
    "❇️ Gemini 2.5 Flash — Google": {
        "proveedor"        : "gemini",
        "model_id"         : "gemini-2.5-flash",
        "descripcion"      : "Modelo multimodal equilibrado entre velocidad, razonamiento y costo",
        "soporta_json_mode": True,
        "es_reasoning"     : False,
        "delay_recomendado": 4.0,  # Free tier: 15 RPM → más conservador
    },
}

MODELO_DEFAULT_KEY = "🦙 LLaMA 3.3 70B — Groq"

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
| Indicador               | Valor registrado | Evaluación técnica                    |
|-------------------------|-----------------|---------------------------------------|
| Índice de Liquidez      | 1.36            | Aceptable — supera el mínimo de 1.0  |
| Índice de Endeudamiento | 0.59            | Aceptable — cerca del límite de 0.60 |
| Razón Ácida             | No reportada    | Verificar en estados financieros      |

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


# =============================================================================
# PRE-FILTRO INTELIGENTE (sin IA, sin red — O(n·k))
# =============================================================================
def es_oferta_relevante(oferta: dict) -> bool:
    """
    Determines whether a given offer is relevant based on its description, category code,
    and specified conditions such as positive and negative words, exact codes, and valid
    prefixes.

    :param oferta: A dictionary representing the details of an offer. Expected keys
        include `descripci_n_del_procedimiento` and `nombre_del_procedimiento`
        for textual evaluation, and `codigo_principal_de_categoria` for evaluating
        category-specific relevance.
    :type oferta: dict
    :return: True if the offer is deemed relevant based on the specified evaluation criteria,
        otherwise False.
    :rtype: bool
    """
    texto_completo = " ".join([
        (oferta.get("descripci_n_del_procedimiento") or "").lower(),
        (oferta.get("nombre_del_procedimiento") or "").lower(),
    ])

    # 1. Descarte duro por palabras negativas
    if any(neg in texto_completo for neg in PALABRAS_NEGATIVAS):
        return False

    codigo = str(oferta.get("codigo_principal_de_categoria") or "").strip()

    # 2. Código UNSPSC exacto → aprobación inmediata
    if codigo in UNSPSC_CODIGOS_EXACTOS:
        return True

    # 3. Prefijo de familia válido → aprobación
    if len(codigo) >= 2 and codigo[:2] in UNSPSC_PREFIJOS_VALIDOS:
        return True

    # 4. Sin código relevante → exigir al menos una palabra positiva
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
        - Prefijo de familia válido    : +20 pts
        - Palabras positivas           : hasta +30 pts (3 pts c/u, máx 10 matches)
        - Urgencia de cierre           : hasta +30 pts
    """
    score  = 0.0
    codigo = str(oferta.get("codigo_principal_de_categoria") or "").strip()
    texto  = " ".join([
        (oferta.get("descripci_n_del_procedimiento") or "").lower(),
        (oferta.get("nombre_del_procedimiento") or "").lower(),
    ])

    if codigo in UNSPSC_CODIGOS_EXACTOS:
        score += 40
    elif len(codigo) >= 2 and codigo[:2] in UNSPSC_PREFIJOS_VALIDOS:
        score += 20

    matches = sum(1 for p in PALABRAS_POSITIVAS if p in texto)
    score  += min(matches * 3, 30)

    fecha_raw = oferta.get("fecha_de_recepcion_de")
    if fecha_raw:
        try:
            fecha_obj = datetime.fromisoformat(str(fecha_raw).split(".")[0])
            dias      = (fecha_obj - datetime.now()).days
            if   0 <= dias <= 3:  score += 30
            elif 0 <= dias <= 7:  score += 20
            elif 0 <= dias <= 15: score += 10
        except (ValueError, TypeError):
            pass

    return round(score, 1)


# =============================================================================
# DIAGNÓSTICO DE CONEXIÓN SOCRATA
# =============================================================================
def diagnosticar_api() -> dict:
    """
    Prueba la conectividad con Socrata sin filtros para identificar si el
    problema es la conexión, el dataset o los filtros WHERE.

    Returns:
        Dict con claves: conexion_ok, total_sin_filtro, muestra_estados,
        muestra_ids, error.
    """
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
        resultado["muestra_estados"]  = list({
            r.get("estado_de_apertura_del_proceso", "N/A") for r in muestra
        })
        resultado["muestra_ids"] = [r.get("id_del_proceso", "?") for r in muestra]
        logger.info("Diagnóstico Socrata OK — %d registros de muestra.", len(muestra))
    except Exception as exc:
        resultado["error"] = str(exc)
        logger.error("Diagnóstico Socrata FALLIDO: %s", exc)
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

    - Estrategia 1 (óptima)  : UNSPSC + texto + fecha reciente
    - Estrategia 2 (fallback): UNSPSC + fecha reciente
    - Estrategia 3 (mínima)  : Solo fecha reciente
    - Estrategia 4 (emergencia): Sin filtros

    El filtro de `estado_de_apertura_del_proceso` se aplica LOCAL porque los
    valores varían en el dataset real y una comparación exacta en SoQL puede
    devolver 0 resultados silenciosamente.

    Returns:
        Lista de dicts con los mejores `limite` procesos, pre-ordenados por score.
    """
    buffer = min(limite * BUFFER_MULTIPLIER, MAX_BUFFER)
    fecha_corte = (datetime.now() - timedelta(days=DIAS_HISTORICO)).strftime(
        "%Y-%m-%dT00:00:00"
    )

    like_clauses: str | None = None
    if codigos_unspsc:
        like_clauses = " OR ".join(
            f"codigo_principal_de_categoria LIKE '{c}%'" for c in codigos_unspsc
        )

    base_where = f"fecha_de_publicacion_del >= '{fecha_corte}'"
    orden      = "fecha_de_publicacion_del DESC"

    estrategias = [
        # (descripción, params_extra)
        ("1 — UNSPSC+fecha+palabra",  {
            "where": base_where + (f" AND ({like_clauses})" if like_clauses else ""),
            **( {"q": palabra_clave.strip()} if palabra_clave and palabra_clave.strip() else {} ),
        }),
        ("2 — UNSPSC+fecha", {
            "where": base_where + (f" AND ({like_clauses})" if like_clauses else ""),
        }),
        ("3 — solo fecha", {
            "where": base_where,
            **( {"q": palabra_clave.strip()} if palabra_clave and palabra_clave.strip() else {} ),
        }),
        ("4 — sin filtros", {}),
    ]

    resultados_brutos: list[dict] = []
    estrategia_usada = "ninguna"

    for descripcion, params_extra in estrategias:
        try:
            resultados_brutos = socrata_client.get(
                DATASET_ID, order=orden, limit=buffer, **params_extra
            )
            estrategia_usada = descripcion
            logger.info("Socrata [%s] — %d registros descargados.", descripcion, len(resultados_brutos))
            if resultados_brutos:
                break
        except Exception as exc:
            logger.warning("Socrata estrategia %s falló: %s", descripcion, exc)

    if not resultados_brutos:
        logger.error("Todas las estrategias Socrata fallaron. Sin resultados.")
        return []

    # Pre-filtro local y ordenamiento por score
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
    """Elimina el bloque <think> de DeepSeek de forma segura."""
    # 1. Borrar el bloque si está cerrado correctamente
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL | re.IGNORECASE)
    
    # 2. Si el bloque quedó abierto (truncado), intentamos cortar en el último corchete de cierre }
    if "<think>" in texto.lower() and "</think>" not in texto.lower():
        # Busca el inicio de lo que parece ser el JSON (usualmente tras saltos de línea largos)
        partes = texto.split("```json")
        if len(partes) > 1:
            texto = partes[-1]
        else:
            # Si no hay bloque de código, borramos solo la etiqueta de apertura y rogamos que el parser JSON haga su magia
            texto = re.sub(r"<think>", "", texto, flags=re.IGNORECASE)

    # 3. Limpiar backticks de markdown
    texto = re.sub(r"```(?:json)?\s*", "", texto)
    texto = re.sub(r"```", "", texto)
    return texto.strip()


def _extraer_json_de_texto(texto: str) -> str:
    """
    Intenta extraer un objeto JSON válido de una cadena que puede tener texto
    libre alrededor. Útil como fallback cuando json.loads() falla directamente.

    Busca el primer '{' y el último '}' y retorna el fragmento entre ambos.
    """
    inicio = texto.find("{")
    fin    = texto.rfind("}")
    if inicio != -1 and fin != -1 and fin > inicio:
        return texto[inicio: fin + 1]
    return texto


def _validar_analisis(datos: dict) -> bool:
    """
    Verifica que el dict devuelto por la IA contenga todos los campos mínimos
    requeridos para renderizarse correctamente en la UI.
    """
    faltantes = _CAMPOS_REQUERIDOS_ANALISIS - datos.keys()
    if faltantes:
        logger.warning("Análisis IA incompleto — faltan campos: %s", faltantes)
        return False
    return True


def llamar_proveedor(
    prompt: str,
    modelo_cfg: dict,
    json_mode: bool = True,
) -> str:
    """
    Router central con retry y backoff exponencial. Dirige la llamada al
    proveedor correcto (Groq o Gemini) y retorna siempre un STRING.

    Args:
        prompt    : Texto del prompt.
        modelo_cfg: Config del modelo de MODELOS_DISPONIBLES.
        json_mode : True → análisis de oferta (JSON); False → resumen (texto).

    Returns:
        Contenido de la respuesta como string.

    Raises:
        RuntimeError: Si todos los reintentos fallan.
    """
    proveedor    = modelo_cfg["proveedor"]
    model_id     = modelo_cfg["model_id"]
    json_ok      = modelo_cfg.get("soporta_json_mode", True)
    es_reasoning = modelo_cfg.get("es_reasoning", False)

    ultimo_error: Exception | None = None

    for intento in range(1, MAX_RETRY + 1):
        try:
            # ── Groq (LLaMA 3.3, DeepSeek R1, LLaMA 4 Scout) ────────────────
            if proveedor == "groq":
                # Los modelos de razonamiento (DeepSeek R1) consumen miles de tokens
                # en el bloque <think> antes de emitir el JSON final.
                # Con 2048 se truncan en el razonamiento y nunca llegan al JSON.
                max_tok = 8192 if es_reasoning else 2048
                kwargs: dict[str, Any] = {
                    "model"      : model_id,
                    "messages"   : [{"role": "user", "content": prompt}],
                    "temperature": 0.4,   # Más bajo = más determinista para JSON
                    "max_tokens" : max_tok,
                }
                if json_mode and json_ok:
                    kwargs["response_format"] = {"type": "json_object"}

                response = groq_client.chat.completions.create(**kwargs)
                texto    = response.choices[0].message.content or ""

                if es_reasoning:
                    texto = _limpiar_respuesta_reasoning(texto)
                return texto

            # ── Gemini (Google AI Studio) ─────────────────────────────────────
            elif proveedor == "gemini":
                if gemini_client is None:
                    raise ValueError(
                        "GOOGLE_API_KEY no está configurada en .env. "
                        "Agrega: GOOGLE_API_KEY=tu_clave"
                    )
                config_gemini: dict[str, str] = {}
                if json_mode and json_ok:
                    config_gemini["response_mime_type"] = "application/json"

                response = gemini_client.models.generate_content(
                    model    = model_id,
                    contents = prompt,
                    config   = config_gemini or None,
                )
                return response.text or ""

            else:
                raise ValueError(f"Proveedor desconocido: '{proveedor}'")

        except Exception as exc:
            ultimo_error = exc
            wait = RETRY_BASE_DELAY * (2 ** (intento - 1))
            logger.warning(
                "Intento %d/%d fallido para %s — %s. Reintentando en %.1f s.",
                intento, MAX_RETRY, model_id, exc, wait,
            )
            if intento < MAX_RETRY:
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
    Soporta múltiples proveedores: Groq (LLaMA, DeepSeek R1) y Google (Gemini).

    Incluye:
    - Caché por modelo: no re-analiza el mismo proceso con el mismo modelo
    - Retry con backoff exponencial ante errores de API
    - Fallback de extracción JSON (busca primer '{' / último '}')
    - Validación de campos mínimos requeridos

    Args:
        oferta     : Dict con los datos del proceso de SECOP II.
        modelo_cfg : Config del modelo. Si es None usa el modelo default.

    Returns:
        Dict con el análisis completo, o None si hubo un error irrecuperable.
    """
    if modelo_cfg is None:
        modelo_cfg = MODELOS_DISPONIBLES[MODELO_DEFAULT_KEY]

    id_proceso = oferta.get("id_del_proceso", "Desconocido")
    cache_key  = f"{id_proceso}_{modelo_cfg['model_id']}"

    if cache_key in _cache_analisis:
        logger.debug("CACHÉ hit → %s (%s)", id_proceso, modelo_cfg["model_id"])
        return _cache_analisis[cache_key]

    # ── Extracción y normalización de campos ─────────────────────────────────
    entidad      = oferta.get("entidad") or "Entidad Desconocida"
    nombre_proc  = oferta.get("nombre_del_procedimiento") or "Sin nombre"
    descripcion  = oferta.get("descripci_n_del_procedimiento") or "Sin descripción"
    modalidad    = oferta.get("modalidad_de_contratacion") or "No especificada"
    tipo_contrato= oferta.get("tipo_de_contrato") or "No especificado"
    unspsc       = str(oferta.get("codigo_principal_de_categoria") or "").strip() or "No especificado"
    cats_adicionales = oferta.get("categorias_adicionales") or ""
    ciudad       = oferta.get("ciudad_entidad") or ""
    departamento = oferta.get("departamento_entidad") or ""
    estado_proc  = oferta.get("estado_del_procedimiento") or ""
    prov_invitados    = oferta.get("proveedores_invitados") or "N/D"
    respuestas_recib  = oferta.get("respuestas_al_procedimiento") or "N/D"
    prov_manifestaron = oferta.get("proveedores_que_manifestaron") or "N/D"

    # Cuantía formateada
    try:
        cuantia_num = f"{float(oferta.get('precio_base', 0)):,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        cuantia_num = str(oferta.get("precio_base") or "No especificado")

    # Duración
    duracion    = oferta.get("duracion") or ""
    unidad_dur  = oferta.get("unidad_de_duracion") or ""
    duracion_texto = f"{duracion} {unidad_dur}".strip() or "No especificada"

    # Enlace
    url_info = oferta.get("urlproceso", {})
    enlace   = (
        url_info.get("url", "Sin enlace")
        if isinstance(url_info, dict)
        else (url_info or "Sin enlace")
    )

    # Fecha de cierre
    fecha_raw = oferta.get("fecha_de_recepcion_de")
    if fecha_raw:
        try:
            fecha_obj    = datetime.fromisoformat(str(fecha_raw).split(".")[0])
            fecha_cierre = fecha_obj.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
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
- Si el objeto es construcción, aseo, vigilancia o manufactura → viabilidad = "NO VIABLE" y porcentaje ≤ 10.
- Si el código UNSPSC coincide exactamente con el RUP → bonus de +15 puntos en porcentaje.
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

        # Para modelos de razonamiento, limpiar bloques <think> antes de parsear
        # (llamar_proveedor ya lo hace, pero aqui garantizamos doble limpieza)
        es_reasoning = modelo_cfg.get("es_reasoning", False)
        if es_reasoning:
            texto_respuesta = _limpiar_respuesta_reasoning(texto_respuesta)

        # Intento 1: parseo directo
        try:
            analisis_dict = json.loads(texto_respuesta)
        except json.JSONDecodeError:
            # Intento 2: extraer el primer objeto JSON del texto
            # (texto libre antes/despues del JSON, frecuente en DeepSeek R1)
            logger.warning(
                "JSON directo falló para %s — intentando extracción por heurística.", id_proceso
            )
            texto_limpio  = _extraer_json_de_texto(texto_respuesta)
            analisis_dict = json.loads(texto_limpio)

        # Validar campos mínimos
        if not _validar_analisis(analisis_dict):
            logger.warning("Análisis de %s descartado por campos incompletos.", id_proceso)
            return None

        _cache_analisis[cache_key] = analisis_dict
        logger.info("OK — %s analizado con %s.", id_proceso, modelo_cfg["model_id"])
        return analisis_dict

    except json.JSONDecodeError as exc:
        logger.error(
            "JSON inválido para %s: %s | Respuesta (primeros %d chars): %s",
            id_proceso, exc, JSON_PARSE_MAXLEN, texto_respuesta[:JSON_PARSE_MAXLEN],
        )
        return None
    except RuntimeError as exc:
        # Todos los reintentos agotados
        logger.error("Sin respuesta IA para %s: %s", id_proceso, exc)
        return None
    except Exception as exc:
        logger.error("Error inesperado en %s (%s): %s", id_proceso, modelo_cfg["model_id"], exc)
        return None


# =============================================================================
# ANÁLISIS SECUENCIAL — Seguro para API gratuita
# =============================================================================
def analizar_ofertas_secuencial(
    ofertas: list[dict],
    delay_segundos: float = 2.0,
    callback_progreso: Callable | None = None,
    modelo_cfg: dict | None = None,
) -> list[dict]:
    """
    Analiza ofertas de forma secuencial con delay configurable entre llamadas.

    - Las ofertas en caché se saltan el delay (no consumen cuota).
    - El callback de progreso se llama antes de cada análisis y al finalizar.

    Args:
        ofertas          : Lista de dicts con datos de SECOP II.
        delay_segundos   : Pausa entre llamadas reales (no de caché).
        callback_progreso: fn(completados, total, id_proceso, desde_cache)
        modelo_cfg       : Config del modelo. None → usa el default.

    Returns:
        Lista de dicts con los análisis completados (sin Nones).
    """
    if modelo_cfg is None:
        modelo_cfg = MODELOS_DISPONIBLES[MODELO_DEFAULT_KEY]

    resultados: list[dict] = []
    total    = len(ofertas)
    model_id = modelo_cfg["model_id"]

    for i, oferta in enumerate(ofertas):
        id_proc   = oferta.get("id_del_proceso", "?")
        cache_key = f"{id_proc}_{model_id}"
        en_cache  = cache_key in _cache_analisis

        if callback_progreso:
            callback_progreso(i, total, id_proc, en_cache)

        resultado = analizar_oferta_ia(oferta, modelo_cfg=modelo_cfg)
        if resultado:
            resultados.append(resultado)

        # Delay solo en llamadas reales (no caché) y si no es la última
        if not en_cache and i < total - 1:
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

    Args:
        resultados : Lista de dicts con los análisis de cada oferta.
        modelo_cfg : Config del modelo. None → usa el default.

    Returns:
        String con el resumen ejecutivo narrativo.
    """
    if modelo_cfg is None:
        modelo_cfg = MODELOS_DISPONIBLES[MODELO_DEFAULT_KEY]

    if not resultados:
        return "No hay resultados para generar resumen."

    viables   = [r for r in resultados if r.get("viabilidad") == "VIABLE"]
    ajustes   = [r for r in resultados if r.get("viabilidad") == "REQUIERE AJUSTES"]
    no_viable = [r for r in resultados if r.get("viabilidad") == "NO VIABLE"]

    prom_aplicabilidad = (
        int(sum(r.get("porcentaje_aplicabilidad", 0) for r in resultados) / len(resultados))
        if resultados else 0
    )

    top_3 = sorted(viables, key=lambda x: x.get("porcentaje_aplicabilidad", 0), reverse=True)[:3]

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
- Responde en español colombiano formal.
"""

    try:
        texto_resumen = llamar_proveedor(
            prompt=prompt, modelo_cfg=modelo_cfg, json_mode=False,
        )
        return texto_resumen.strip()
    except Exception as exc:
        logger.error("Error al generar resumen ejecutivo (%s): %s", modelo_cfg["model_id"], exc)
        return "No se pudo generar el resumen ejecutivo automático."


# =============================================================================
# GESTIÓN DE CACHÉ
# =============================================================================
def limpiar_cache() -> None:
    """Limpia el caché de análisis en memoria."""
    global _cache_analisis
    _cache_analisis = {}
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

    Returns:
        Bytes del archivo .xlsx listo para st.download_button().
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
            "% Aplicabilidad"      : r.get("porcentaje_aplicabilidad", 0),
            "Score Financiero"     : r.get("score_financiero", 0),
            "Nivel de Competencia" : r.get("nivel_competencia", ""),
            "Valor Estimado (COP)" : r.get("valor_estimado", ""),
            "Duración del Contrato": r.get("duracion_contrato", ""),
            "Modalidad"            : r.get("modalidad", ""),
            "Fecha Cierre"         : r.get("fecha_cierre", ""),
            "Fortalezas"           : " | ".join(r.get("fortalezas", [])),
            "Riesgos"              : " | ".join(r.get("riesgos", [])),
            "Acciones de Mejora"   : " | ".join(r.get("acciones_mejora", [])),
            "Recomendación IA"     : r.get("recomendacion", ""),
            "Enlace SECOP"         : r.get("enlace_secop", ""),
        }
        for r in resultados
    ]

    df = pd.DataFrame(filas).sort_values("% Aplicabilidad", ascending=False)

    # Hoja 2: métricas resumidas
    viables    = sum(1 for r in resultados if r.get("viabilidad") == "VIABLE")
    ajustes    = sum(1 for r in resultados if r.get("viabilidad") == "REQUIERE AJUSTES")
    no_viables = len(resultados) - viables - ajustes
    prom_pct   = (
        int(sum(r.get("porcentaje_aplicabilidad", 0) for r in resultados) / len(resultados))
        if resultados else 0
    )

    df_resumen = pd.DataFrame([
        {"Métrica": "Total Procesos Analizados",  "Valor": len(resultados)},
        {"Métrica": "Procesos VIABLES",           "Valor": viables},
        {"Métrica": "Procesos REQUIEREN AJUSTES", "Valor": ajustes},
        {"Métrica": "Procesos NO VIABLES",        "Valor": no_viables},
        {"Métrica": "% Aplicabilidad Promedio",   "Valor": f"{prom_pct}%"},
        {"Métrica": "Fecha de Generación",        "Valor": datetime.now().strftime("%Y-%m-%d %H:%M")},
    ])

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Análisis Detallado")
        df_resumen.to_excel(writer, index=False, sheet_name="Resumen Ejecutivo")

        for sheet_name in writer.sheets:
            ws = writer.sheets[sheet_name]
            for col in ws.columns:
                max_len = max(
                    (len(str(cell.value or "")) for cell in col), default=10
                )
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 65)

    return buffer.getvalue()