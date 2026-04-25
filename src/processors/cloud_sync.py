import sys
import os
import math
import time

# Agrega la carpeta raíz del proyecto al camino de búsqueda de Python
ruta_raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ruta_raiz not in sys.path:
    sys.path.append(ruta_raiz)

from src.integrations.dropbox_client import DropboxConnector
from src.core.drone_utils import extraer_datos_drone, calcular_distancia_metros

def calcular_rumbo(punto1, punto2):
    """Calcula el azimut/rumbo entre dos puntos GPS para validación de orientación."""
    lat1, lon1 = math.radians(punto1['latitud']), math.radians(punto1['longitud'])
    lat2, lon2 = math.radians(punto2['latitud']), math.radians(punto2['longitud'])
    d_lon = lon2 - lon1
    y = math.sin(d_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def copiar_con_reintento(dbx_client, ruta_origen, ruta_destino, max_reintentos=5):
    """Copia archivos manejando errores de saturación de API con confirmación visual."""
    for intento in range(max_reintentos):
        try:
            dbx_client.copiar_archivo(ruta_origen, ruta_destino)
            if intento > 0:
                print(f"      ✅ ÉXITO: Guardado tras {intento} reintento(s).")
            return True
        except Exception as e:
            if "too_many_write_operations" in str(e).lower():
                espera = (intento + 1) * 3 
                print(f"      ⏳ API SATURADA (Intento {intento+1}/{max_reintentos}). Reintentando en {espera}s...")
                time.sleep(espera)
            else:
                print(f"      ❌ ERROR CRÍTICO: {e}")
                return False
    print(f"      🚫 FALLO DEFINITIVO: No se pudo copiar {os.path.basename(ruta_destino)}.")
    return False

def registrar_nodo_critico(zona, poste, cantidad):
    """Registra postes con menos de 4 fotos para auditoría."""
    with open("nodos_criticos.log", "a", encoding="utf-8") as f:
        f.write(f"ZONA/SUBZONA: {zona} | POSTE: #{poste} | CANTIDAD FOTOS: {cantidad} (Crítico)\n")

def ejecutar_procesamiento_skyline():
    dbx = DropboxConnector()
    carpeta_entrada = "/2 ENEL CODENSA/ZONA 10 (ORIENTE)"
    carpeta_salida = "/CARPETA DE PRUEBAS (NO TOCAR)"
    
    # Parámetros de Triple Confirmación
    umbral_proximidad = 5
    umbral_orientacion = 15
    tolerancia_angulo = 45 
    distancia_max_nodo = 40 # NUEVO: Límite estricto para pertenecer a un poste

    print(f"Conectando a Dropbox para escanear: {carpeta_entrada}...")
    todas_las_imagenes = dbx.listar_archivos_recursivo(carpeta_entrada)
    if not todas_las_imagenes: return

    # Agrupamiento y ordenamiento
    imagenes_por_carpeta = {} 
    carpetas_con_fecha = {}
    for img in todas_las_imagenes:
        ruta_dir = os.path.dirname(img.path_display)
        if ruta_dir not in carpetas_con_fecha:
            carpetas_con_fecha[ruta_dir] = img.client_modified
            imagenes_por_carpeta[ruta_dir] = []
        imagenes_por_carpeta[ruta_dir].append(img)

    rutas_ordenadas = sorted(carpetas_con_fecha.keys(), key=lambda k: carpetas_con_fecha[k])
    
    # --- LÓGICA NUEVA: ESTADO GLOBAL POR SUBZONA ---
    estado_subzonas = {} 

    for ruta_dir in rutas_ordenadas:
        fotos = imagenes_por_carpeta[ruta_dir]
        fotos.sort(key=lambda x: x.client_modified)
        
        # Identificación de Subzona/Circuito
        ruta_rel = os.path.relpath(ruta_dir, carpeta_entrada).replace("\\", "/")
        partes = [p for p in ruta_rel.split('/') if p and p != "."]
        subzona_id = "/".join(partes[:1]) if len(partes) >= 2 else (partes[0] if partes else "GENERAL")
        
        # Inicializar o recuperar estado de la subzona
        if subzona_id not in estado_subzonas:
            print(f"\n🔄 NUEVA SUBZONA/CIRCUITO DETECTADO: {subzona_id}")
            ruta_base_subzona = f"{carpeta_salida}/{subzona_id}".replace("//", "/")
            offset_remoto = dbx.obtener_ultimo_poste_remoto(ruta_base_subzona) or 0
            estado_subzonas[subzona_id] = {
                'postes_acumulados': 0,
                'offset': offset_remoto,
                'ultima_cenital_data': None
            }
        
        # Referencia al estado actual para no perder el hilo
        est = estado_subzonas[subzona_id]
        ruta_base = f"{carpeta_salida}/{subzona_id}".replace("//", "/")
        fotos_pendientes = []
        conteo_fotos = {}

        print(f"\n📂 PROCESANDO CARPETA: {ruta_dir}")

        for metadata in fotos:
            fragmento = dbx.descargar_fragmento(metadata.path_display)
            if not fragmento: continue
            datos = extraer_datos_drone(fragmento)
            
            if datos['latitud'] and datos['longitud']:
                coords_act = {'latitud': datos['latitud'], 'longitud': datos['longitud']}
                altitud_act = datos.get('altitud', 0)
                yaw_act = datos.get('gimbal_yaw', 0)
                pitch_act = datos.get('pitch', 0) # Recuperamos el pitch para posible promoción

                if datos['es_cenital']:
                    es_mismo = False
                    if est['ultima_cenital_data']:
                        dist_cent = calcular_distancia_metros(coords_act, est['ultima_cenital_data']['coords'])
                        if dist_cent < umbral_proximidad:
                            es_mismo = True
                            num_mismo = est['postes_acumulados'] + est['offset']
                            
                            if altitud_act > est['ultima_cenital_data']['altitud']:
                                print(f"   [CENITAL] Poste #{num_mismo}: Reemplazando por toma a {altitud_act}m (era {est['ultima_cenital_data']['altitud']}m).")
                                dest_cen = f"{ruta_base}/Cenitales/{num_mismo}{os.path.splitext(metadata.name)[1]}"
                                copiar_con_reintento(dbx, metadata.path_display, dest_cen)
                                est['ultima_cenital_data']['altitud'] = altitud_act
                                est['ultima_cenital_data']['coords'] = coords_act
                            else:
                                print(f"   [INFO] Poste #{num_mismo}: Cenital actual más baja, se guarda en Nodos.")
                                dest_nod = f"{ruta_base}/Nodos/{num_mismo}/{metadata.name}"
                                copiar_con_reintento(dbx, metadata.path_display, dest_nod)
                                conteo_fotos[num_mismo] = conteo_fotos.get(num_mismo, 0) + 1

                    if not es_mismo:
                        est['postes_acumulados'] += 1
                        num_act = est['postes_acumulados'] + est['offset']
                        conteo_fotos[num_act] = 1
                        print(f"   🚩 Poste #{num_act} detectado (Altitud: {altitud_act}m).")
                        dest_cen = f"{ruta_base}/Cenitales/{num_act}{os.path.splitext(metadata.name)[1]}"
                        copiar_con_reintento(dbx, metadata.path_display, dest_cen)

                        restantes = []
                        num_ant = num_act - 1 if est['postes_acumulados'] > 1 else None
                        for f_temp in fotos_pendientes:
                            dist_a_este = calcular_distancia_metros(f_temp['coords'], coords_act)
                            rumbo_este = calcular_rumbo(f_temp['coords'], coords_act)
                            diff_este = abs((f_temp['yaw'] - rumbo_este + 180) % 360 - 180)
                            
                            target = None
                            metodo = ""
                            if dist_a_este <= umbral_proximidad: 
                                target, metodo = num_act, "Proximidad (<5m)"
                            elif dist_a_este <= umbral_orientacion and diff_este <= tolerancia_angulo: 
                                target, metodo = num_act, f"Orientación ({diff_este:.1f}°)"
                            elif est['ultima_cenital_data'] and num_ant:
                                d_ant = calcular_distancia_metros(f_temp['coords'], est['ultima_cenital_data']['coords'])
                                # MODIFICACIÓN: Aplicación del límite de 40 metros
                                if dist_a_este < d_ant and dist_a_este <= distancia_max_nodo:
                                    target, metodo = num_act, f"Cercanía Poste Actual ({dist_a_este:.1f}m)"
                                elif d_ant <= distancia_max_nodo:
                                    target, metodo = num_ant, f"Cercanía Poste Anterior ({d_ant:.1f}m)"
                            
                            if target:
                                dest = f"{ruta_base}/Nodos/{target}/{f_temp['nombre']}"
                                if copiar_con_reintento(dbx, f_temp['ruta'], dest):
                                    conteo_fotos[target] = conteo_fotos.get(target, 0) + 1
                                    print(f"      📸 {f_temp['nombre']} -> Poste #{target} | {metodo}")
                            else: restantes.append(f_temp)
                        fotos_pendientes = restantes
                        est['ultima_cenital_data'] = {'coords': coords_act, 'altitud': altitud_act}
                else:
                    # Guardamos también el pitch y la altitud para una posible promoción a cenital
                    fotos_pendientes.append({
                        'ruta': metadata.path_display, 
                        'nombre': metadata.name, 
                        'coords': coords_act, 
                        'yaw': yaw_act,
                        'pitch': pitch_act,
                        'altitud': altitud_act
                    })

        # MODIFICACIÓN: Evaluación y Promoción de Clústeres Huérfanos
        if fotos_pendientes:
            print(f"   🔍 Analizando {len(fotos_pendientes)} fotos huérfanas en busca de nodos perdidos...")
            while fotos_pendientes:
                # Tomamos la primera foto huérfana como "semilla" para buscar su clúster
                seed = fotos_pendientes.pop(0)
                cluster = [seed]
                restantes = []
                
                for f_h in fotos_pendientes:
                    # Si está a menos de la distancia máxima de la semilla, es del mismo nodo
                    if calcular_distancia_metros(seed['coords'], f_h['coords']) <= distancia_max_nodo:
                        cluster.append(f_h)
                    else:
                        restantes.append(f_h)
                
                fotos_pendientes = restantes # Las que sobraron se evalúan en el siguiente ciclo
                
                # Promover la foto con el pitch más negativo (buscamos el valor más bajo, ej. -78°)
                promovida = min(cluster, key=lambda x: x['pitch'] if x['pitch'] is not None else 0)
                
                est['postes_acumulados'] += 1
                n_fin = est['postes_acumulados'] + est['offset']
                conteo_fotos[n_fin] = 1
                
                print(f"   🚀 [PROMOCIÓN] Poste #{n_fin} creado desde clúster (Pitch: {promovida['pitch']}°).")
                dest_cen = f"{ruta_base}/Cenitales/{n_fin}{os.path.splitext(promovida['nombre'])[1]}"
                copiar_con_reintento(dbx, promovida['ruta'], dest_cen)
                
                # Guardar el resto del clúster como nodos de este nuevo poste
                for f_c in cluster:
                    if f_c['ruta'] != promovida['ruta']:
                        dest_nod = f"{ruta_base}/Nodos/{n_fin}/{f_c['nombre']}"
                        if copiar_con_reintento(dbx, f_c['ruta'], dest_nod):
                            conteo_fotos[n_fin] = conteo_fotos.get(n_fin, 0) + 1
                
                # Actualizar la referencia global para que el siguiente nodo tenga de donde agarrarse
                est['ultima_cenital_data'] = {'coords': promovida['coords'], 'altitud': promovida['altitud']}

        for p_id, cant in conteo_fotos.items():
            if cant < 4: registrar_nodo_critico(subzona_id, p_id, cant)

    print("\n" + "=" * 80 + "\nPROCESO FINALIZADO EXITOSAMENTE\n" + "=" * 80)

if __name__ == "__main__":
    ejecutar_procesamiento_skyline()