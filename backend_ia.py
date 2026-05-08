# =============================================================================
# backend_ia.py — Motor de análisis SECOP II con IA
# Versión 2.1 — Perfil real · Caché · Rate-limit seguro para API gratuita
# =============================================================================
from google import genai
from sodapy import Socrata
from dotenv import load_dotenv
import os
import json
import pandas as pd
import io
import time
from datetime import datetime, timedelta

# --- Carga de variables de entorno ---
load_dotenv()
API_KEY = os.environ.get("API_KEY_GEMINI_MIA")
TOKEN   = os.environ.get("TOKEN")

# --- Clientes ---
gemini_client  = genai.Client(api_key=API_KEY)
socrata_client = Socrata("www.datos.gov.co", TOKEN)

# --- Caché en memoria: evita re-analizar el mismo proceso en la misma sesión ---
# La app.py administra un dict de caché via session_state; este dict es el
# repositorio en el nivel del módulo (persistente entre reruns de Streamlit).
_cache_analisis: dict[str, dict] = {}


# =============================================================================
# PERFIL INSTITUCIONAL REAL ANONIMIZADO
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
# CATÁLOGO UNSPSC — PERFIL COMPLETO (2 dígitos = familia)
# =============================================================================
UNSPSC_PERFIL = {
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

UNSPSC_PREFIJOS_VALIDOS = list(UNSPSC_PERFIL.keys())

# Códigos UNSPSC completos (8 dígitos) con experiencia directa en RUP
UNSPSC_CODIGOS_EXACTOS = {
    "45111800", "60101100", "60105200", "60105300", "60105400", "60105600",
    "80101500", "80101600", "80101700", "80111500", "80141500", "80141600",
    "80141900", "81111500", "81131500", "81161500", "82141500", "84101500",
    "86101500", "86101700", "86101800", "86111500", "86111600", "86121700",
    "86132000", "86141500", "86141700", "90121500", "90151800", "93141500",
    "93141600", "93141700", "93142000", "93142100", "94131500",
}

# Palabras que causan descarte inmediato (fuera de perfil)
PALABRAS_NEGATIVAS = [
    "construcci", "paviment", "alcantarill", "acueduct", "vial",
    "suministro de alimento", "dotaci", "aseo y limpieza", "vigilancia y seguridad",
    "transporte de carga", "fabricaci", "manufactura", "obra civil",
    "material de ferretería", "mantenimiento locativo", "mobiliario",
    "excavaci", "demolici", "impermeabiliz", "carpintería",
]

# Palabras que confirman alineación con el perfil institucional
PALABRAS_POSITIVAS = [
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


# =============================================================================
# PRE-FILTRO INTELIGENTE (O(1) — sin IA, sin red)
# =============================================================================
def es_oferta_relevante(oferta: dict) -> bool:
    """
    Descarta ofertas que no tienen sentido para el perfil institucional ANTES
    de hacer cualquier llamada costosa a la IA.
    Prioridad: código UNSPSC exacto > prefijo > palabras clave.
    Retorna True si la oferta merece análisis.
    """
    descripcion    = (oferta.get("descripci_n_del_procedimiento", "") or "").lower()
    nombre_proceso = (oferta.get("nombre_del_procedimiento", "") or "").lower()
    texto_completo = descripcion + " " + nombre_proceso

    # 1) Descarte duro por palabras negativas
    for neg in PALABRAS_NEGATIVAS:
        if neg in texto_completo:
            return False

    codigo_unspsc = str(oferta.get("codigo_principal_de_categoria", "") or "").strip()

    # 2) Coincidencia exacta con código RUP — aprobación inmediata
    if codigo_unspsc in UNSPSC_CODIGOS_EXACTOS:
        return True

    # 3) Coincidencia por prefijo de familia (2 dígitos)
    if len(codigo_unspsc) >= 2:
        prefijo = codigo_unspsc[:2]
        if prefijo in UNSPSC_PREFIJOS_VALIDOS:
            return True
        else:
            # Código no relevante — verificar si el texto tiene palabras positivas
            return any(p in texto_completo for p in PALABRAS_POSITIVAS)

    # 4) Sin código UNSPSC — exigir al menos una palabra positiva
    return any(p in texto_completo for p in PALABRAS_POSITIVAS)


# =============================================================================
# SCORE DE PRIORIDAD (sin IA — solo metadatos)
# Para pre-ordenar antes de enviar a IA y para UI de urgencia.
# =============================================================================
def calcular_score_previo(oferta: dict) -> float:
    """
    Score compuesto pre-IA (0–100) para priorizar qué ofertas analizar primero.
    Factores: UNSPSC exacto, palabras clave, urgencia por fecha.
    """
    score = 0.0
    codigo = str(oferta.get("codigo_principal_de_categoria", "") or "").strip()
    texto  = (
        (oferta.get("descripci_n_del_procedimiento", "") or "").lower() + " " +
        (oferta.get("nombre_del_procedimiento", "") or "").lower()
    )

    # Código UNSPSC exacto: +40 puntos
    if codigo in UNSPSC_CODIGOS_EXACTOS:
        score += 40
    elif len(codigo) >= 2 and codigo[:2] in UNSPSC_PREFIJOS_VALIDOS:
        score += 20

    # Palabras positivas: hasta +30 puntos
    matches = sum(1 for p in PALABRAS_POSITIVAS if p in texto)
    score += min(matches * 3, 30)

    # Urgencia por fecha de cierre: hasta +30 puntos
    fecha_raw = oferta.get("fecha_de_recepcion_de")
    if fecha_raw:
        try:
            fecha_obj = datetime.fromisoformat(str(fecha_raw).split(".")[0])
            dias = (fecha_obj - datetime.now()).days
            if 0 <= dias <= 3:
                score += 30
            elif 0 <= dias <= 7:
                score += 20
            elif 0 <= dias <= 15:
                score += 10
        except Exception:
            pass

    return round(score, 1)


# =============================================================================
# DIAGNÓSTICO DE CONEXIÓN — Útil para debugging en producción
# =============================================================================
def diagnosticar_api() -> dict:
    """
    Prueba la conectividad con Socrata sin filtros para identificar
    si el problema es la conexión, el dataset o los filtros WHERE.
    Retorna un dict con el diagnóstico.
    """
    resultado = {
        "conexion_ok"     : False,
        "total_sin_filtro": 0,
        "muestra_estados" : [],
        "muestra_ids"     : [],
        "error"           : None,
    }
    try:
        # Consulta sin ningún filtro — solo trae 5 registros para ver la estructura
        muestra = socrata_client.get("p6dx-8zbt", limit=5, order="fecha_de_publicacion_del DESC")
        resultado["conexion_ok"]      = True
        resultado["total_sin_filtro"] = len(muestra)
        # Ver qué valores tiene el campo de estado
        resultado["muestra_estados"] = list({
            r.get("estado_de_apertura_del_proceso", "N/A") for r in muestra
        })
        resultado["muestra_ids"] = [
            r.get("id_del_proceso", "?") for r in muestra
        ]
    except Exception as e:
        resultado["error"] = str(e)
    return resultado


# =============================================================================
# OBTENER OFERTAS DEL SECOP II — Versión robusta sin depender del filtro de estado
# =============================================================================
def obtener_ofertas_secop(
    limite: int = 10,
    palabra_clave: str = None,
    codigos_unspsc: list = None,
) -> list:
    """
    Descarga ofertas del SECOP II con estrategia de consulta en cascada:

    Estrategia 1 (óptima): UNSPSC + búsqueda por texto + fecha reciente
    Estrategia 2 (fallback): Solo UNSPSC + fecha reciente
    Estrategia 3 (mínima): Solo fecha reciente — pre-filtro local lo depura todo

    El filtro de `estado_de_apertura_del_proceso` se aplica LOCAL porque
    los valores del campo varían en el dataset real ("Activo", "Publicado", etc.)
    y una comparación exacta en SoQL puede devolver 0 resultados silenciosamente.
    """
    buffer_descarga = min(limite * 10, 800)

    # Fecha de corte: solo procesos publicados en los últimos 90 días
    fecha_corte = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00")

    # Construir cláusula UNSPSC si hay filtros específicos
    like_clauses = None
    if codigos_unspsc:
        like_clauses = " OR ".join(
            [f"codigo_principal_de_categoria LIKE '{c}%'" for c in codigos_unspsc]
        )

    # ── Estrategia 1: UNSPSC + palabra clave + fecha ─────────────────────────
    params_s1 = {
        "order": "fecha_de_publicacion_del DESC",
        "limit": buffer_descarga,
    }
    where_s1 = [f"fecha_de_publicacion_del >= '{fecha_corte}'"]
    if like_clauses:
        where_s1.append(f"({like_clauses})")
    params_s1["where"] = " AND ".join(where_s1)
    if palabra_clave and palabra_clave.strip():
        params_s1["q"] = palabra_clave.strip()

    resultados_brutos = []
    estrategia_usada  = "ninguna"

    try:
        resultados_brutos = socrata_client.get("p6dx-8zbt", **params_s1)
        estrategia_usada  = "1 (UNSPSC + fecha + palabra)"
        print(f"[Socrata S1] Descargados: {len(resultados_brutos)}")
    except Exception as e1:
        print(f"[Socrata S1 error] {e1}")

        # ── Estrategia 2: Solo UNSPSC + fecha ────────────────────────────────
        params_s2 = {
            "order": "fecha_de_publicacion_del DESC",
            "limit": buffer_descarga,
            "where": f"fecha_de_publicacion_del >= '{fecha_corte}'"
                     + (f" AND ({like_clauses})" if like_clauses else ""),
        }
        try:
            resultados_brutos = socrata_client.get("p6dx-8zbt", **params_s2)
            estrategia_usada  = "2 (UNSPSC + fecha)"
            print(f"[Socrata S2] Descargados: {len(resultados_brutos)}")
        except Exception as e2:
            print(f"[Socrata S2 error] {e2}")

            # ── Estrategia 3: Solo fecha reciente ────────────────────────────
            params_s3 = {
                "order": "fecha_de_publicacion_del DESC",
                "limit": buffer_descarga,
            }
            if palabra_clave and palabra_clave.strip():
                params_s3["q"] = palabra_clave.strip()
            try:
                resultados_brutos = socrata_client.get("p6dx-8zbt", **params_s3)
                estrategia_usada  = "3 (solo fecha reciente)"
                print(f"[Socrata S3] Descargados: {len(resultados_brutos)}")
            except Exception as e3:
                print(f"[Socrata S3 error — sin resultados] {e3}")
                return []

    if not resultados_brutos:
        # Último recurso: sin ningún filtro
        try:
            resultados_brutos = socrata_client.get(
                "p6dx-8zbt",
                limit=buffer_descarga,
                order="fecha_de_publicacion_del DESC",
            )
            estrategia_usada = "4 (sin filtros — emergencia)"
            print(f"[Socrata S4] Descargados: {len(resultados_brutos)}")
        except Exception as e4:
            print(f"[Socrata S4 fatal] {e4}")
            return []

    # ── Pre-filtro local: palabras negativas/positivas + UNSPSC local ─────────
    resultados_limpios = [r for r in resultados_brutos if es_oferta_relevante(r)]

    # Ordenar por score previo descendente
    resultados_ordenados = sorted(
        resultados_limpios,
        key=calcular_score_previo,
        reverse=True,
    )

    print(
        f"[INFO] Estrategia: {estrategia_usada} | "
        f"Descargados: {len(resultados_brutos)} | "
        f"Pre-filtro local: {len(resultados_limpios)} | "
        f"Enviando a IA: {min(len(resultados_ordenados), limite)}"
    )

    return resultados_ordenados[:limite]


# =============================================================================
# ANÁLISIS IA — PROMPT ENRIQUECIDO CON PERFIL REAL
# =============================================================================
def analizar_oferta_ia(oferta: dict) -> dict | None:
    """
    Evalúa una oferta con Gemini usando el perfil institucional real.
    Incluye caché en memoria: no re-analiza el mismo ID de proceso.
    """
    id_proceso = oferta.get("id_del_proceso", "Desconocido")

    # --- Caché: retornar si ya fue analizado ---
    if id_proceso in _cache_analisis:
        print(f"[CACHÉ] Oferta {id_proceso} recuperada del caché.")
        return _cache_analisis[id_proceso]

    # --- Extracción de campos ---
    entidad      = oferta.get("entidad", "Entidad Desconocida")
    nombre_proc  = oferta.get("nombre_del_procedimiento", "Sin nombre")
    descripcion  = oferta.get("descripci_n_del_procedimiento", "Sin descripción")
    cuantia      = oferta.get("precio_base", "No especificado")
    modalidad    = oferta.get("modalidad_de_contratacion", "No especificada")
    tipo_contrato= oferta.get("tipo_de_contrato", "No especificado")
    unspsc       = oferta.get("codigo_principal_de_categoria", "No especificado")
    cats_adicionales = oferta.get("categorias_adicionales", "")
    duracion     = oferta.get("duracion", "")
    unidad_dur   = oferta.get("unidad_de_duracion", "")
    ciudad       = oferta.get("ciudad_entidad", "")
    departamento = oferta.get("departamento_entidad", "")
    estado_proc  = oferta.get("estado_del_procedimiento", "")
    prov_invitados     = oferta.get("proveedores_invitados", "N/D")
    respuestas_recib   = oferta.get("respuestas_al_procedimiento", "N/D")
    prov_manifestaron  = oferta.get("proveedores_que_manifestaron", "N/D")

    url_info = oferta.get("urlproceso", {})
    enlace   = url_info.get("url", "Sin enlace") if isinstance(url_info, dict) else (url_info or "Sin enlace")

    fecha_cierre_raw = oferta.get("fecha_de_recepcion_de")
    if fecha_cierre_raw:
        try:
            fecha_obj    = datetime.fromisoformat(str(fecha_cierre_raw).split(".")[0])
            fecha_cierre = fecha_obj.strftime("%Y-%m-%d %H:%M")
        except Exception:
            fecha_cierre = "Fecha inválida"
    else:
        fecha_cierre = "Sin fecha definida"

    duracion_texto = f"{duracion} {unidad_dur}".strip() if duracion else "No especificada"

    # Indicar si el código UNSPSC coincide exactamente con el RUP
    match_exacto = unspsc in UNSPSC_CODIGOS_EXACTOS
    match_prefijo = len(unspsc) >= 2 and unspsc[:2] in UNSPSC_PREFIJOS_VALIDOS
    contexto_unspsc = (
        "COINCIDENCIA EXACTA CON RUP — experiencia directamente acreditada en este código"
        if match_exacto else
        "COINCIDENCIA POR FAMILIA — experiencia relacionada pero no acreditada en este código exacto"
        if match_prefijo else
        "SIN COINCIDENCIA DIRECTA EN RUP — evaluar capacidades transferibles"
    )

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
- Valor Estimado           : ${cuantia} COP
- Duración                 : {duracion_texto}
- Código UNSPSC Principal  : {unspsc}
- Contexto UNSPSC          : {contexto_unspsc}
- Categorías Adicionales   : {cats_adicionales if cats_adicionales else "Ninguna"}
- Estado del Proceso       : {estado_proc}

INTELIGENCIA COMPETITIVA:
- Proveedores invitados    : {prov_invitados}
- Manifestaron interés     : {prov_manifestaron}
- Respuestas recibidas     : {respuestas_recib}

=====================================
INSTRUCCIONES DE ANÁLISIS
=====================================
Evalúa con criterio crítico y objetivo:
1. Alineación del objeto con las capacidades ACREDITADAS EN RUP.
2. Viabilidad financiera: ¿el valor es coherente con el tamaño operativo?
   (Liquidez 1.36 y endeudamiento 0.59 — perfil financiero aceptable pero ajustado).
3. Competencia técnica: ¿tienen experiencia demostrable en >50 contratos para ganar?
4. Inteligencia competitiva: ¿es un proceso muy disputado o una oportunidad abierta?
5. Riesgos concretos (reputacionales, técnicos, financieros, cumplimiento).
6. Acciones ejecutables y específicas para preparar la propuesta.
7. score_financiero: 0-100 evaluando si el valor del contrato es apropiado para
   el tamaño financiero del proponente (muy bajo = subutilización; muy alto = riesgo).

REGLAS:
- Si el objeto es de construcción, aseo, vigilancia o manufactura → viabilidad = "NO VIABLE" y porcentaje ≤ 10.
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
    "valor_estimado"          : "{cuantia}",
    "duracion_contrato"       : "{duracion_texto}",
    "modalidad"               : "{modalidad}",
    "fecha_cierre"            : "{fecha_cierre}",
    "enlace_secop"            : "{enlace}",
    "match_unspsc_rup"        : {"true" if match_exacto else "false"}
}}
"""

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )
        texto_limpio  = response.text.replace("```json", "").replace("```", "").strip()
        analisis_dict = json.loads(texto_limpio)

        # Guardar en caché
        _cache_analisis[id_proceso] = analisis_dict
        return analisis_dict

    except Exception as e:
        print(f"[ERROR IA] Oferta {id_proceso} — {entidad}: {e}")
        return None


# =============================================================================
# ANÁLISIS SECUENCIAL — Seguro para API gratuita de Gemini
# =============================================================================
def analizar_ofertas_secuencial(
    ofertas: list,
    delay_segundos: float = 4.0,
    callback_progreso=None,
) -> list:
    """
    Analiza ofertas de forma secuencial con delay configurable.
    - delay_segundos=4.0 es seguro para el free tier de Gemini (15 RPM).
    - Las que están en caché se saltan el delay (son instantáneas).
    - callback_progreso(i, total, id_proceso, desde_cache): función opcional de UI.
    """
    resultados = []
    total = len(ofertas)

    for i, oferta in enumerate(ofertas):
        id_proc    = oferta.get("id_del_proceso", "?")
        en_cache   = id_proc in _cache_analisis

        if callback_progreso:
            callback_progreso(i, total, id_proc, en_cache)

        resultado = analizar_oferta_ia(oferta)
        if resultado:
            resultados.append(resultado)

        # Solo esperar si la llamada fue real (no desde caché)
        if not en_cache and i < total - 1:
            time.sleep(delay_segundos)

    if callback_progreso:
        callback_progreso(total, total, "✓ Completado", False)

    return resultados


# Alias para compatibilidad con versión anterior de app.py
def analizar_ofertas_paralelo(ofertas, max_workers=4, callback_progreso=None):
    """Alias que redirige al procesamiento secuencial seguro."""
    return analizar_ofertas_secuencial(
        ofertas,
        delay_segundos=4.0,
        callback_progreso=lambda i, t, id_, cache: (
            callback_progreso(i, t, id_) if callback_progreso else None
        ),
    )


# =============================================================================
# RESUMEN EJECUTIVO IA — Post-análisis de todas las ofertas
# =============================================================================
def generar_resumen_ejecutivo(resultados: list) -> str:
    """
    Genera un resumen ejecutivo estratégico de todas las ofertas analizadas,
    con recomendaciones de priorización para el equipo de gestión contractual.
    """
    if not resultados:
        return "No hay resultados para generar resumen."

    viables   = [r for r in resultados if r.get("viabilidad") == "VIABLE"]
    ajustes   = [r for r in resultados if r.get("viabilidad") == "REQUIERE AJUSTES"]
    no_viable = [r for r in resultados if r.get("viabilidad") == "NO VIABLE"]

    resumen_data = {
        "total_analizados"  : len(resultados),
        "viables"           : len(viables),
        "requieren_ajustes" : len(ajustes),
        "no_viables"        : len(no_viable),
        "promedio_aplicabilidad": (
            int(sum(r.get("porcentaje_aplicabilidad", 0) for r in resultados) / len(resultados))
        ),
        "top_3_oportunidades": [
            {
                "id"        : r.get("id_oferta"),
                "entidad"   : r.get("entidad"),
                "objeto"    : r.get("objeto_contrato"),
                "pct"       : r.get("porcentaje_aplicabilidad"),
                "valor"     : r.get("valor_estimado"),
                "fecha_cie" : r.get("fecha_cierre"),
            }
            for r in sorted(
                viables,
                key=lambda x: x.get("porcentaje_aplicabilidad", 0),
                reverse=True,
            )[:3]
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
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        print(f"[ERROR Resumen Ejecutivo] {e}")
        return "No se pudo generar el resumen ejecutivo automático."


# =============================================================================
# LIMPIAR CACHÉ (para uso desde la UI)
# =============================================================================
def limpiar_cache():
    """Limpia el caché de análisis en memoria."""
    global _cache_analisis
    _cache_analisis = {}
    print("[CACHÉ] Caché limpiado.")


# =============================================================================
# EXPORTAR REPORTE A EXCEL (mejorado con hoja de resumen)
# =============================================================================
def exportar_reporte_excel(resultados: list) -> bytes:
    """
    Convierte la lista de análisis a un archivo Excel con dos hojas:
    1. Reporte completo detallado
    2. Resumen ejecutivo con métricas
    """
    if not resultados:
        return b""

    # --- Hoja 1: Reporte completo ---
    filas = []
    for r in resultados:
        filas.append({
            "Prioridad"              : "⭐" if r.get("viabilidad") == "VIABLE" else (
                                       "🔶" if r.get("viabilidad") == "REQUIERE AJUSTES" else "❌"),
            "ID Proceso"             : r.get("id_oferta", ""),
            "Entidad"                : r.get("entidad", ""),
            "Objeto del Contrato"    : r.get("objeto_contrato", ""),
            "Código UNSPSC"          : r.get("codigo_unspsc", ""),
            "Categoría UNSPSC"       : r.get("categoria_unspsc", ""),
            "¿Match RUP Exacto?"     : "Sí" if r.get("match_unspsc_rup") else "No",
            "Viabilidad"             : r.get("viabilidad", ""),
            "% Aplicabilidad"        : r.get("porcentaje_aplicabilidad", 0),
            "Score Financiero"       : r.get("score_financiero", 0),
            "Nivel de Competencia"   : r.get("nivel_competencia", ""),
            "Valor Estimado (COP)"   : r.get("valor_estimado", ""),
            "Duración del Contrato"  : r.get("duracion_contrato", ""),
            "Modalidad"              : r.get("modalidad", ""),
            "Fecha Cierre"           : r.get("fecha_cierre", ""),
            "Fortalezas"             : " | ".join(r.get("fortalezas", [])),
            "Riesgos"                : " | ".join(r.get("riesgos", [])),
            "Acciones de Mejora"     : " | ".join(r.get("acciones_mejora", [])),
            "Recomendación IA"       : r.get("recomendacion", ""),
            "Enlace SECOP"           : r.get("enlace_secop", ""),
        })

    df = pd.DataFrame(filas)
    df = df.sort_values(by=["% Aplicabilidad"], ascending=False)

    # --- Hoja 2: Resumen ---
    viables = sum(1 for r in resultados if r.get("viabilidad") == "VIABLE")
    ajustes = sum(1 for r in resultados if r.get("viabilidad") == "REQUIERE AJUSTES")
    no_viables = len(resultados) - viables - ajustes
    prom_pct = (
        int(sum(r.get("porcentaje_aplicabilidad", 0) for r in resultados) / len(resultados))
        if resultados else 0
    )

    df_resumen = pd.DataFrame([
        {"Métrica": "Total Procesos Analizados",    "Valor": len(resultados)},
        {"Métrica": "Procesos VIABLES",             "Valor": viables},
        {"Métrica": "Procesos REQUIEREN AJUSTES",   "Valor": ajustes},
        {"Métrica": "Procesos NO VIABLES",          "Valor": no_viables},
        {"Métrica": "% Aplicabilidad Promedio",     "Valor": f"{prom_pct}%"},
        {"Métrica": "Fecha de Generación",          "Valor": datetime.now().strftime("%Y-%m-%d %H:%M")},
    ])

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Análisis Detallado")
        df_resumen.to_excel(writer, index=False, sheet_name="Resumen Ejecutivo")

        # Ajuste de anchos
        for sheet_name in ["Análisis Detallado", "Resumen Ejecutivo"]:
            ws = writer.sheets[sheet_name]
            for col in ws.columns:
                max_len = max((len(str(cell.value or "")) for cell in col), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 65)

    return buffer.getvalue()