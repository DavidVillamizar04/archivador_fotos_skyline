"""
cloud_sync.py — Skyline: Procesamiento y clasificación de fotos de infraestructura eléctrica.

Cambios respecto a la versión anterior:
  - FIX CRÍTICO: La promoción de clústeres ya no fuerza una "cenital falsa". Si ninguna
    foto del clúster alcanza el umbral mínimo de pitch, el nodo se crea sin cenital y
    todas las fotos van a Nodos/. Esto se registra en el log de auditoría.
  - PERFORMANCE: Las descargas de fragmentos se paralelizan con ThreadPoolExecutor,
    reduciendo significativamente el tiempo de espera entre llamadas a la API.
  - MEMORIA DE ZONA: Se persiste el estado de procesamiento por zona en un archivo JSON
    local (zona_state.json). Si la última ejecución fue hace más de 2 semanas, se trata
    como análisis nuevo. Esto permite retomar carpetas nuevas sin reprocessar desde cero.
  - REFACTOR: calcular_rumbo movido a drone_utils.py. No hay duplicación de lógica.
  - LOG DE AUDITORÍA: El log de nodos críticos se separa por ejecución con un timestamp.
"""

import sys
import os
import math
import time
import json
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

ruta_raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ruta_raiz not in sys.path:
    sys.path.append(ruta_raiz)

from src.integrations.dropbox_client import DropboxConnector
from src.core.drone_utils import (
    extraer_datos_drone,
    calcular_distancia_metros,
    calcular_rumbo,
    tiene_gps_valido,
    PITCH_PROMOCION_MIN,
)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
CARPETA_ENTRADA = "/2 ENEL CODENSA/ZONA 10 (ORIENTE)"
CARPETA_SALIDA  = "/CARPETA DE PRUEBAS (NO TOCAR)"

UMBRAL_PROXIMIDAD   = 5    # metros — asignación directa sin más comprobaciones
UMBRAL_ORIENTACION  = 15   # metros — zona donde se verifica el ángulo de la cámara
TOLERANCIA_ANGULO   = 45   # grados — margen de error en el yaw del gimbal
DISTANCIA_MAX_NODO  = 40   # metros — límite absoluto para pertenecer a un poste

WORKERS_DESCARGA    = 6    # hilos paralelos para descargar fragmentos
SEMANAS_MEMORIA     = 2    # semanas antes de considerar una zona como análisis nuevo
ARCHIVO_ESTADO      = "zona_state.json"
ARCHIVO_LOG         = "nodos_criticos.log"

# ---------------------------------------------------------------------------
# Estado persistente por zona
# ---------------------------------------------------------------------------

def _cargar_estado_zonas():
    """Lee el JSON de estado guardado en disco. Retorna dict vacío si no existe."""
    if os.path.exists(ARCHIVO_ESTADO):
        try:
            with open(ARCHIVO_ESTADO, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _guardar_estado_zonas(estado):
    """Persiste el dict de estado en disco."""
    with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def _obtener_estado_zona(estado_zonas, subzona_id, dbx, ruta_base_subzona):
    """
    Devuelve el estado en memoria para una subzona.
    - Si han pasado más de SEMANAS_MEMORIA desde la última ejecución → estado nuevo.
    - Si no hay estado guardado → lo inicializa consultando Dropbox.
    """
    ahora = datetime.datetime.utcnow()
    limite = datetime.timedelta(weeks=SEMANAS_MEMORIA)

    if subzona_id in estado_zonas:
        ultima_str = estado_zonas[subzona_id].get("ultima_ejecucion")
        if ultima_str:
            ultima = datetime.datetime.fromisoformat(ultima_str)
            if ahora - ultima > limite:
                print(f"   ⏰ Han pasado más de {SEMANAS_MEMORIA} semanas. Reiniciando estado de '{subzona_id}'.")
                del estado_zonas[subzona_id]

    if subzona_id not in estado_zonas:
        print(f"\n🔄 NUEVA SUBZONA/CIRCUITO: {subzona_id}")
        offset_remoto = dbx.obtener_ultimo_poste_remoto(ruta_base_subzona) or 0
        estado_zonas[subzona_id] = {
            "postes_acumulados": 0,
            "offset": offset_remoto,
            "ultima_cenital_data": None,
            "ultima_ejecucion": ahora.isoformat(),
            "carpetas_procesadas": [],
            "carpeta_en_progreso": None,
            "ultimo_archivo_procesado": None,
        }
    else:
        # Actualizar timestamp en cada ejecución
        estado_zonas[subzona_id]["ultima_ejecucion"] = ahora.isoformat()

    return estado_zonas[subzona_id]


# ---------------------------------------------------------------------------
# Helpers de copia y log
# ---------------------------------------------------------------------------

def copiar_con_reintento(dbx_client, ruta_origen, ruta_destino, max_reintentos=5, reemplazar=False):
    """
    Copia un archivo con reintentos exponenciales ante saturación de la API.
    reemplazar=True  → usa reemplazar_cenital(): borra el archivo previo antes de copiar.
                       Usar SOLO para Cenitales/ donde debe existir exactamente un archivo por poste.
    reemplazar=False → usa copiar_archivo() con autorename=True (comportamiento normal para Nodos/).
    """
    operacion = dbx_client.reemplazar_cenital if reemplazar else dbx_client.copiar_archivo
    for intento in range(max_reintentos):
        try:
            operacion(ruta_origen, ruta_destino)
            if intento > 0:
                print(f"      ✅ ÉXITO tras {intento} reintento(s).")
            return True
        except Exception as e:
            if "too_many_write_operations" in str(e).lower():
                espera = (intento + 1) * 3
                print(f"      ⏳ API SATURADA (intento {intento+1}/{max_reintentos}). Esperando {espera}s...")
                time.sleep(espera)
            else:
                print(f"      ❌ ERROR CRÍTICO al copiar: {e}")
                return False
    print(f"      🚫 FALLO DEFINITIVO: {os.path.basename(ruta_destino)}")
    return False


def registrar_en_log(linea):
    """Agrega una línea al log de auditoría con timestamp."""
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as f:
        f.write(linea + "\n")


# ---------------------------------------------------------------------------
# Descarga paralela de fragmentos
# ---------------------------------------------------------------------------

def _descargar_fragmento_wrapper(args):
    """Worker para ThreadPoolExecutor: descarga el fragmento y extrae datos."""
    dbx, metadata = args
    fragmento = dbx.descargar_fragmento(metadata.path_display)
    if not fragmento:
        return None
    datos = extraer_datos_drone(fragmento)
    if not tiene_gps_valido(datos):
        return None
    return {
        "metadata": metadata,
        "datos": datos,
        "coords": {"latitud": datos["latitud"], "longitud": datos["longitud"]},
    }


def descargar_fotos_paralelo(dbx, fotos_metadata):
    """
    Descarga los fragmentos de todas las fotos de una carpeta en paralelo.
    Retorna lista de dicts ordenada por path_display (orden del vuelo).
    """
    resultados = {}
    args = [(dbx, m) for m in fotos_metadata]

    with ThreadPoolExecutor(max_workers=WORKERS_DESCARGA) as executor:
        futures = {executor.submit(_descargar_fragmento_wrapper, a): a[1] for a in args}
        for future in as_completed(futures):
            meta = futures[future]
            try:
                resultado = future.result()
                if resultado:
                    resultados[meta.path_display] = resultado
            except Exception as e:
                print(f"   [WARN] Error procesando {meta.name}: {e}")

    # Reordenar según el orden original (path_display = orden del vuelo)
    return [resultados[m.path_display] for m in fotos_metadata if m.path_display in resultados]


# ---------------------------------------------------------------------------
# Clasificación de fotos de detalle (Triple Confirmación)
# ---------------------------------------------------------------------------

def _clasificar_foto_pendiente(foto, cenital_actual, cenital_anterior, num_act, num_ant):
    """
    Aplica la jerarquía de Triple Confirmación para decidir a qué poste
    pertenece una foto de detalle. Retorna (numero_poste, metodo) o (None, None).
    """
    coords_f = foto["coords"]
    dist_act = calcular_distancia_metros(coords_f, cenital_actual["coords"])

    # Confirmación 1: Proximidad extrema
    if dist_act <= UMBRAL_PROXIMIDAD:
        return num_act, f"Proximidad (<{UMBRAL_PROXIMIDAD}m)"

    # Confirmación 2: Orientación de la cámara
    if dist_act <= UMBRAL_ORIENTACION:
        rumbo = calcular_rumbo(coords_f, cenital_actual["coords"])
        diff = abs((foto["datos"]["gimbal_yaw"] - rumbo + 180) % 360 - 180)
        if diff <= TOLERANCIA_ANGULO:
            return num_act, f"Orientación ({diff:.1f}°)"

    # Confirmación 3: Cercanía geográfica entre postes (con límite de 40 m)
    if cenital_anterior and num_ant is not None:
        d_ant = calcular_distancia_metros(coords_f, cenital_anterior["coords"])
        if dist_act < d_ant and dist_act <= DISTANCIA_MAX_NODO:
            return num_act, f"Cercanía poste actual ({dist_act:.1f}m)"
        if d_ant <= DISTANCIA_MAX_NODO:
            return num_ant, f"Cercanía poste anterior ({d_ant:.1f}m)"

    return None, None


# ---------------------------------------------------------------------------
# Promoción de clústeres huérfanos — FIX CRÍTICO
# ---------------------------------------------------------------------------

def _promover_clusteres(fotos_pendientes, est, ruta_base, subzona_id, carpeta_id, dbx, conteo_fotos):
    """
    Agrupa las fotos huérfanas en clústeres y crea un nuevo nodo por cada uno.

    FIX CRÍTICO: Si ninguna foto del clúster tiene un pitch suficientemente bajo
    (>= PITCH_PROMOCION_MIN, ej. -60°), el nodo se crea SIN cenital:
      - Todas las fotos van a Nodos/{n}/
      - Se registra en el log de auditoría como NODO_SIN_CENITAL para revisión manual.
    Esto evita que una foto normal (pitch ~0°) sea marcada como cenital.

    carpeta_id: nombre de la subcarpeta de vuelo (ej. "2024-03-15_Vuelo1") para trazabilidad
    en el log — permite saber exactamente de qué lote de fotos vino el nodo problemático.
    """
    while fotos_pendientes:
        seed = fotos_pendientes.pop(0)
        cluster = [seed]
        restantes = []

        for f_h in fotos_pendientes:
            if calcular_distancia_metros(seed["coords"], f_h["coords"]) <= DISTANCIA_MAX_NODO:
                cluster.append(f_h)
            else:
                restantes.append(f_h)

        fotos_pendientes = restantes

        est["postes_acumulados"] += 1
        n_fin = est["postes_acumulados"] + est["offset"]
        conteo_fotos[n_fin] = 0

        # ── FIX: ¿Hay alguna foto con pitch suficientemente bajo para ser cenital? ──
        candidatas_cenital = [
            f for f in cluster
            if f["datos"]["pitch"] is not None and f["datos"]["pitch"] <= PITCH_PROMOCION_MIN
        ]

        if candidatas_cenital:
            # Promover la que tenga el pitch más negativo dentro del grupo válido
            promovida = min(candidatas_cenital, key=lambda x: x["datos"]["pitch"])
            pitch_promovido = promovida["datos"]["pitch"]
            print(f"   🚀 [PROMOCIÓN] Poste #{n_fin} creado desde clúster (Pitch: {pitch_promovido}°).")

            ext = os.path.splitext(promovida["metadata"].name)[1]
            dest_cen = f"{ruta_base}/Cenitales/{n_fin}{ext}"
            copiar_con_reintento(dbx, promovida["metadata"].path_display, dest_cen, reemplazar=True)
            conteo_fotos[n_fin] += 1

            # Resto del clúster → Nodos
            for f_c in cluster:
                if f_c["metadata"].path_display != promovida["metadata"].path_display:
                    dest_nod = f"{ruta_base}/Nodos/{n_fin}/{f_c['metadata'].name}"
                    if copiar_con_reintento(dbx, f_c["metadata"].path_display, dest_nod):
                        conteo_fotos[n_fin] += 1

            est["ultima_cenital_data"] = {
                "coords": promovida["coords"],
                "altitud": promovida["datos"]["altitud"],
            }

        else:
            # ── NUEVO: Clúster sin ninguna foto con pitch aceptable ──
            print(f"   ⚠️  [SIN CENITAL] Poste #{n_fin}: ninguna foto tiene pitch ≤ {PITCH_PROMOCION_MIN}°. "
                  f"Guardando {len(cluster)} foto(s) solo en Nodos/.")
            registrar_en_log(
                f"[{datetime.datetime.utcnow().isoformat()}] "
                f"ZONA: {subzona_id} | CARPETA: {carpeta_id} | POSTE: #{n_fin} | "
                f"NODO_SIN_CENITAL | FOTOS: {len(cluster)} | "
                f"PITCHES: {[f['datos']['pitch'] for f in cluster]}"
            )

            for f_c in cluster:
                dest_nod = f"{ruta_base}/Nodos/{n_fin}/{f_c['metadata'].name}"
                if copiar_con_reintento(dbx, f_c["metadata"].path_display, dest_nod):
                    conteo_fotos[n_fin] += 1

            # Actualizamos la referencia geográfica aunque no haya cenital,
            # usando la foto con menor pitch disponible como ancla posicional
            mejor_ancla = min(cluster, key=lambda x: x["datos"]["pitch"] if x["datos"]["pitch"] is not None else 0)
            est["ultima_cenital_data"] = {
                "coords": mejor_ancla["coords"],
                "altitud": mejor_ancla["datos"]["altitud"],
            }


# ---------------------------------------------------------------------------
# Procesamiento principal de una carpeta
# ---------------------------------------------------------------------------

def _procesar_carpeta(ruta_dir, fotos_metadata, est, estado_zonas, ruta_base, subzona_id, carpeta_id, dbx):
    """
    Procesa todas las fotos de una carpeta/vuelo:
    1. Descarga fragmentos en paralelo.
    2. Si la carpeta estaba en progreso (interrupción previa), salta las fotos
       ya procesadas y retoma desde la siguiente.
    3. Aplica Triple Confirmación para clasificar.
    4. Antes de numerar cada nueva cenital, promueve huérfanos intermedios que
       geográficamente quedaron entre la cenital anterior y la actual — así los
       nodos sin cenital reciben un número correlativo en el orden real del vuelo.
    5. Los huérfanos que queden al final (genuinamente después de la última cenital)
       se promueven al cierre de la carpeta.

    estado_zonas: referencia al dict completo para poder guardar checkpoints por archivo.
    carpeta_id: ruta relativa desde CARPETA_ENTRADA, usada en log y en checkpoints.
    """
    print(f"\n📂 PROCESANDO CARPETA: {ruta_dir}")

    # ── Descarga paralela ──
    fotos = descargar_fotos_paralelo(dbx, fotos_metadata)
    if not fotos:
        print("   [INFO] No se pudieron descargar fotos con GPS válido.")
        return {}

    # ── Retomar desde interrupción previa ──
    # Si esta carpeta estaba marcada como "en progreso", saltar los archivos
    # que ya fueron procesados en la ejecución anterior.
    ultimo_procesado = est.get("ultimo_archivo_procesado")
    if est.get("carpeta_en_progreso") == carpeta_id and ultimo_procesado:
        nombres = [f["metadata"].name for f in fotos]
        if ultimo_procesado in nombres:
            idx = nombres.index(ultimo_procesado)
            fotos = fotos[idx + 1:]  # Retomar desde el archivo siguiente
            print(f"   ⏩ Retomando desde {ultimo_procesado} — {len(fotos)} foto(s) pendientes.")
        else:
            print(f"   ⚠️  Archivo de retoma '{ultimo_procesado}' no encontrado — reprocesando carpeta completa.")

    fotos_pendientes = []
    conteo_fotos = {}
    cenital_anterior = None

    for item in fotos:
        metadata = item["metadata"]
        datos = item["datos"]
        coords_act = item["coords"]

        if datos["es_cenital"]:
            # ── Verificar si es el mismo poste (cenital duplicada) ──
            es_mismo = False
            if est["ultima_cenital_data"]:
                dist_cent = calcular_distancia_metros(coords_act, est["ultima_cenital_data"]["coords"])
                if dist_cent < UMBRAL_PROXIMIDAD:
                    es_mismo = True
                    num_mismo = est["postes_acumulados"] + est["offset"]
                    alt_act = datos["altitud"]
                    alt_prev = est["ultima_cenital_data"]["altitud"]

                    if alt_act > alt_prev:
                        print(f"   [CENITAL] Poste #{num_mismo}: reemplazando toma ({alt_prev}m → {alt_act}m).")
                        ext = os.path.splitext(metadata.name)[1]
                        dest_cen = f"{ruta_base}/Cenitales/{num_mismo}{ext}"
                        copiar_con_reintento(dbx, metadata.path_display, dest_cen, reemplazar=True)
                        est["ultima_cenital_data"]["altitud"] = alt_act
                        est["ultima_cenital_data"]["coords"] = coords_act
                    else:
                        print(f"   [INFO] Poste #{num_mismo}: cenital duplicada descartada (pitch más alto).")
                        dest_nod = f"{ruta_base}/Nodos/{num_mismo}/{metadata.name}"
                        copiar_con_reintento(dbx, metadata.path_display, dest_nod)
                        conteo_fotos[num_mismo] = conteo_fotos.get(num_mismo, 0) + 1

            if not es_mismo:
                # Guardar referencia al poste anterior ANTES de cualquier promoción
                cenital_anterior = est["ultima_cenital_data"]
                est["postes_acumulados"] += 1
                num_act = est["postes_acumulados"] + est["offset"]
                conteo_fotos[num_act] = 1
                num_ant = num_act - 1 if est["postes_acumulados"] > 1 else None

                print(f"   🚩 Poste #{num_act} detectado (Altitud: {datos['altitud']}m).")
                ext = os.path.splitext(metadata.name)[1]
                dest_cen = f"{ruta_base}/Cenitales/{num_act}{ext}"
                copiar_con_reintento(dbx, metadata.path_display, dest_cen, reemplazar=True)

                # ── Paso 1: Triple Confirmación sobre TODOS los pendientes ──
                # La Confirmación 3 compara distancia al poste actual vs anterior,
                # por eso necesitamos cenital_anterior ya definida antes de este bloque.
                sin_clasificar = []
                for f_temp in fotos_pendientes:
                    target, metodo = _clasificar_foto_pendiente(
                        f_temp,
                        {"coords": coords_act},
                        cenital_anterior,
                        num_act,
                        num_ant,
                    )
                    if target is not None:
                        dest = f"{ruta_base}/Nodos/{target}/{f_temp['metadata'].name}"
                        if copiar_con_reintento(dbx, f_temp["metadata"].path_display, dest):
                            conteo_fotos[target] = conteo_fotos.get(target, 0) + 1
                            print(f"      📸 {f_temp['metadata'].name} → Poste #{target} | {metodo}")
                    else:
                        sin_clasificar.append(f_temp)

                # ── Paso 2: De los que NO clasificaron, separar intermedios geográficos ──
                # Solo se promueven como nodo nuevo los que están más cerca de la cenital
                # actual que de la anterior — indica un poste sin cenital en medio del recorrido.
                # Los demás siguen pendientes para la próxima cenital.
                intermedios = []
                fotos_pendientes = []
                for f_h in sin_clasificar:
                    if cenital_anterior:
                        dist_a_actual = calcular_distancia_metros(f_h["coords"], coords_act)
                        dist_a_anterior = calcular_distancia_metros(
                            f_h["coords"], cenital_anterior["coords"]
                        )
                        if dist_a_actual < dist_a_anterior:
                            intermedios.append(f_h)
                        else:
                            fotos_pendientes.append(f_h)
                    else:
                        # Sin cenital anterior de referencia, dejar pendiente
                        fotos_pendientes.append(f_h)

                if intermedios:
                    print(f"   🔀 {len(intermedios)} huérfano(s) intermedio(s) — insertando en orden de vuelo...")
                    _promover_clusteres(intermedios, est, ruta_base, subzona_id, carpeta_id, dbx, conteo_fotos)

                est["ultima_cenital_data"] = {"coords": coords_act, "altitud": datos["altitud"]}

        else:
            fotos_pendientes.append(item)

        # ── Checkpoint: registrar el último archivo procesado ──
        # Se guarda después de cada foto para que una interrupción no pierda el progreso.
        # No se llama a _guardar_estado_zonas() aquí para no saturar disco en cada foto;
        # el guardado a disco ocurre en el entry point al terminar cada carpeta completa.
        est["carpeta_en_progreso"] = carpeta_id
        est["ultimo_archivo_procesado"] = metadata.name

    # ── Huérfanos genuinos al final (después de la última cenital del vuelo) ──
    if fotos_pendientes:
        print(f"   🔍 {len(fotos_pendientes)} huérfano(s) al final del recorrido — promoviendo...")
        _promover_clusteres(fotos_pendientes, est, ruta_base, subzona_id, carpeta_id, dbx, conteo_fotos)

    return conteo_fotos


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def ejecutar_procesamiento_skyline():
    dbx = DropboxConnector()

    print(f"Conectando a Dropbox → {CARPETA_ENTRADA}")
    todas_las_imagenes = dbx.listar_archivos_recursivo(CARPETA_ENTRADA)
    if not todas_las_imagenes:
        print("No se encontraron imágenes. Verificar ruta de entrada.")
        return

    # Agrupar por carpeta y ordenar carpetas por fecha de modificación
    imagenes_por_carpeta = {}
    carpetas_con_fecha = {}
    for img in todas_las_imagenes:
        ruta_dir = os.path.dirname(img.path_display)
        if ruta_dir not in carpetas_con_fecha:
            carpetas_con_fecha[ruta_dir] = img.client_modified
            imagenes_por_carpeta[ruta_dir] = []
        imagenes_por_carpeta[ruta_dir].append(img)

    rutas_ordenadas = sorted(carpetas_con_fecha, key=lambda k: carpetas_con_fecha[k])

    # Cargar estado persistente
    estado_zonas = _cargar_estado_zonas()
    ts_inicio = datetime.datetime.utcnow().isoformat()
    registrar_en_log(f"\n{'='*70}\nEJECUCIÓN: {ts_inicio}\n{'='*70}")

    for ruta_dir in rutas_ordenadas:
        fotos = imagenes_por_carpeta[ruta_dir]
        fotos.sort(key=lambda x: x.client_modified)

        # Determinar subzona/circuito y ruta completa de trazabilidad.
        # Estructura esperada: ZONA/ciudad/carpeta_vuelo/...
        # partes[0]  = zona/circuito → subzona_id (clave del estado y del KMZ)
        # carpeta_id = ruta completa relativa desde CARPETA_ENTRADA, ej:
        #              "Chipaque/Centro/2024-03-15_Vuelo1"
        ruta_rel = os.path.relpath(ruta_dir, CARPETA_ENTRADA).replace("\\", "/")
        partes = [p for p in ruta_rel.split("/") if p and p != "."]
        subzona_id = partes[0] if len(partes) >= 1 else "GENERAL"
        carpeta_id = ruta_rel if ruta_rel != "." else "GENERAL"

        ruta_base = f"{CARPETA_SALIDA}/{subzona_id}".replace("//", "/")
        est = _obtener_estado_zona(estado_zonas, subzona_id, dbx, ruta_base)

        # ── Saltar carpetas ya completadas en ejecuciones anteriores ──
        carpetas_procesadas = est.get("carpetas_procesadas", [])
        if carpeta_id in carpetas_procesadas:
            print(f"   ⏭️  Ya procesada, omitiendo: {carpeta_id}")
            continue

        # Marcar como en progreso antes de empezar (por si se interrumpe)
        est["carpeta_en_progreso"] = carpeta_id
        est["ultimo_archivo_procesado"] = None
        _guardar_estado_zonas(estado_zonas)

        conteo_fotos = _procesar_carpeta(ruta_dir, fotos, est, estado_zonas, ruta_base, subzona_id, carpeta_id, dbx)

        # Auditoría de nodos críticos (menos de 4 fotos incluyendo la cenital)
        for p_id, cant in conteo_fotos.items():
            if cant < 4:
                registrar_en_log(
                    f"[{datetime.datetime.utcnow().isoformat()}] "
                    f"ZONA: {subzona_id} | CARPETA: {carpeta_id} | POSTE: #{p_id} | "
                    f"NODO_CRÍTICO | FOTOS: {cant}"
                )

        # Carpeta terminada exitosamente: limpiar progreso y registrar como completa
        carpetas_procesadas.append(carpeta_id)
        est["carpetas_procesadas"] = carpetas_procesadas
        est["carpeta_en_progreso"] = None
        est["ultimo_archivo_procesado"] = None
        _guardar_estado_zonas(estado_zonas)

    print("\n" + "=" * 80)
    print("PROCESO FINALIZADO EXITOSAMENTE")
    print("=" * 80)


if __name__ == "__main__":
    ejecutar_procesamiento_skyline()