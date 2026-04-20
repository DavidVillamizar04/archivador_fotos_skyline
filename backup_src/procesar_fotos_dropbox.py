from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS
from io import BytesIO
import os
import math
import dropbox
from dropbox.exceptions import ApiError
import os
import shutil

# Configura tu token
ACCESS_TOKEN = 'sl.u.AGb-ad1dCSvI3dduWivACHZrLFeYHa2Upp4-wMnKZLQmFZSfy541WiWrh5Ph-1kRwoV0eZZyCXh475eGcXsEx0JfV_4U6wsaBU-yhdwodVYvtzE0odZlVqd37j8BfcsjPrvcImRwlckPoMRvew8KXEAoTXTZAgQtSJmwJm1TwBY9gEqwckNVGB-UB41BOVbxA_SJspKvVKT9hjdmwqPP9Avj_k5gnRQvZNc6I9Nl8D2uEnHT0ubtNx0u6asiB6wglML0LSZ60p4wQ-posm2MUkwLxjSGUi9oNXeIv3nDE9aJ0hgKl_GgrehvGOI6JCZlKJPUsVe5UsXx88XgiaYLW5D_S9_-bthpT2Xc2Bd0Kx3J0BNJONdnXYT1tM1ngQrIO1_f1T1nkwrDvBMFANRhdRf9Kepn5Nn6kfMc_ThhrdkCylDUAaSiNWz9v30ZoT4OKfSk2GQJrWKr1lHsmPNV--ZfWrgCG2GWbYQNg1Wk02wIc7o5VX3GOn8tgFs4K46dyf_chyvushIYRpb0p8KP5bByina0NXNDnOrzmPaAJl4SMF2NMsvTAqB0W51ALbcbN7ksT5fXBFq4RVAKu7BUsERoSuiIEEuD4Y2O3q-hAC0xijdzX2CxaDbAkHzZWvvo95Wnb8QIK-9Lh7BmSSNoZBqot3GfOw1N-7NAKAYK6ijszB6gKuLZHipG5ziZlLejkw5GqqUq7B3nmCiLVkmNPThz3nu4BSPmgGffIIn2PjKgBGZPvfY15ViBPITPf7DUfX5I19J1bn9koSoL20CZNOQNE7iLXGYTxH5E4EBozitL8uufy0TXECM6JTRAOpdPWpTs5rj91X43ENbWa0m3LvVX1cOALBmbCNjWo4jnN8wyh74rH9nlsDW0QqmBMQMsot-Hvu1PgmXcKghuX9-7VG1pfWh14yLnmUcS3kPNsgBHoKEhk0IVc7tj2v4XbQ4Xqne5-eQFamRKuos-IZWfpw3x9XIl7HUBugVSWGsPBuoQWVe4kw-2tTj2uVvgfqvFi9TaKPfnsFurWsu1NCR-iGkS6nFBF0MLwI6UWFnIVXMsWwRrh5SJr7YGl9byjW9_fq5sjwNW1-leIx5SixzrLmhcrcjQTvn2xzKIDGkiJc7FWGZg2hPyNc-A56hVvAL6ZIqlLshPSnQbJrqrwU5FRyG_8lSpb7XDFasBeXVX66jiHbC5uoq8lWXZQDPtK_aGMUl3_w7N13mhi-diVcbPs_I__HE_DH131WA3-BhJFciZZpT38zqPM1z3J8JFTDyJIx6BzThAABX4u0xpt1GdepwX19auYSIiUv12u38JFL05gA'
dbx = dropbox.Dropbox(ACCESS_TOKEN)

def organizar_foto(ruta_actual, nueva_ruta):
    try:
        # Dropbox requiere que las rutas empiecen con "/"
        dbx.files_move_v2(ruta_actual, nueva_ruta)
        print(f"Movido: {ruta_actual} -> {nueva_ruta}")
    except ApiError as err:
        print(f"Error al mover el archivo: {err}")

# Ejemplo de uso:
# organizar_foto('/fotos_sueltas/foto01.jpg', '/fotos_organizadas/2024/foto01.jpg')

# Ruta del archivo ZIP
carpeta_entrada = "/2 ENEL CODENSA"
carpeta_salida = "/CARPETA DE PRUEBAS (NO TOCAR)"


def calcular_distancia_gps(lat1, lon1, lat2, lon2):
    """Calcula distancia aproximada entre dos coordenadas GPS en metros"""
    # Usando fórmula simple para distancias cortas
    lat_diff = (lat2 - lat1) * 111000  # 1 grado ≈ 111 km
    lon_diff = (lon2 - lon1) * 111000 * math.cos(math.radians(lat1))
    distancia = math.sqrt(lat_diff**2 + lon_diff**2)
    return distancia

def obtener_ubicacion_ultimo_poste():
    """Lee EXIF de las fotos del último poste existente y retorna ubicación promedio"""
    try:
        if not os.path.exists(carpeta_salida):
            return None
        
        # Obtener carpetas existentes ordenadas numéricamente
        carpetas = [d for d in os.listdir(carpeta_salida) if os.path.isdir(os.path.join(carpeta_salida, d)) and d.isdigit()]
        if not carpetas:
            return None
        
        # Obtener la última carpeta (número más alto)
        ultima_carpeta = max(carpetas, key=int)
        ruta_ultima_carpeta = os.path.join(carpeta_salida, ultima_carpeta)
        
        # Obtener todas las fotos de la última carpeta
        fotos_ultima_carpeta = [f for f in os.listdir(ruta_ultima_carpeta) 
                               if f.lower().endswith(('.jpg', '.jpeg', '.png', '.dng'))]
        
        if not fotos_ultima_carpeta:
            return None
        
        coordenadas = []
        
        # Leer EXIF de cada foto
        for foto in fotos_ultima_carpeta:
            ruta_foto = os.path.join(ruta_ultima_carpeta, foto)
            try:
                img = Image.open(ruta_foto)
                exif_data = img._getexif()
                if exif_data:
                    metadata = {}
                    for tag_id, value in exif_data.items():
                        tag_name = TAGS.get(tag_id, tag_id)
                        metadata[tag_name] = value
                    
                    gps = extraer_gps(metadata.get('GPSInfo'))
                    if gps:
                        coordenadas.append((gps['latitud'], gps['longitud']))
                
                img.close()
            except Exception as e:
                continue
        
        if not coordenadas:
            return None
        
        # Calcular promedio
        lat_promedio = sum(lat for lat, lon in coordenadas) / len(coordenadas)
        lon_promedio = sum(lon for lat, lon in coordenadas) / len(coordenadas)
        
        return {
            'lat': lat_promedio,
            'lon': lon_promedio,
            'numero_poste': int(ultima_carpeta),
            'cantidad_fotos': len(coordenadas)
        }
        
    except Exception as e:
        print(f"Error leyendo último poste: {e}")
        return None

def extraer_gps(gps_ifd):
    """Convierte datos GPS EXIF de (grados, minutos, segundos) a formato decimal"""
    try:
        if not gps_ifd:
            return None
        
        # Extraer componentes GPS
        lat = gps_ifd.get(2)  # Latitude
        lat_ref = gps_ifd.get(1)  # North/South
        lon = gps_ifd.get(4)  # Longitude
        lon_ref = gps_ifd.get(3)  # East/West
        
        if not (lat and lat_ref and lon and lon_ref):
            return None
        
        # Convertir de (grados, minutos, segundos) a decimal
        def convertir_a_decimal(valor):
            """Convierte (grados, minutos, segundos) a grados decimales"""
            grados = float(valor[0])
            minutos = float(valor[1])
            segundos = float(valor[2])
            return grados + (minutos / 60) + (segundos / 3600)
        
        # Calcular latitud y longitud
        latitud = convertir_a_decimal(lat)
        longitud = convertir_a_decimal(lon)
        
        # Aplicar referencia (N/S para latitud, E/W para longitud)
        if lat_ref == 'S':
            latitud = -latitud
        if lon_ref == 'W':
            longitud = -longitud
        
        return {
            'latitud': latitud,
            'longitud': longitud,
            'latitud_ref': lat_ref,
            'longitud_ref': lon_ref,
            'altitud': gps_ifd.get(6),  # Altitude if available
        }
    except Exception as e:
        return None

def obtener_metadata_exif(imagen_bytes):
    """Obtiene metadatos EXIF de una imagen"""
    try:
        img = Image.open(BytesIO(imagen_bytes))
        exif_data = img._getexif()
        if exif_data:
            metadata = {}
            for tag_id, value in exif_data.items():
                tag_name = TAGS.get(tag_id, tag_id)
                metadata[tag_name] = value
            return metadata
        return None
    except Exception as e:
        return None

def es_foto_cenital(img_bytes):
    """
    Analiza los bytes de una imagen para determinar si es cenital
    basándose en el ángulo del Gimbal (GimbalPitchDegree).
    """
    etiqueta = b'GimbalPitchDegree="'
    
    if etiqueta in img_bytes:
        # Encontrar la posición del dato
        idx = img_bytes.find(etiqueta)
        # Extraer el valor numérico (ej: "-90.00" o "-45.40")
        inicio = idx + len(etiqueta)
        fin = img_bytes.find(b'"', inicio)
        
        try:
            valor_texto = img_bytes[inicio:fin].decode('utf-8')
            angulo = float(valor_texto)
            
            # Filtro: Consideramos cenital si está entre -88 y -90 grados
            # (Damos un margen de 2 grados por posibles vibraciones del dron)
            if angulo <= -85.0:
                return True
        except ValueError:
            pass
            
    return False



try:
    print(f"Conectando a Dropbox para escanear: {carpeta_entrada}...")
    imagenes_metadata = []
    extensiones_validas = ('.jpg', '.jpeg', '.png', '.dng')

    # Usamos la API para listar archivos recursivamente
    res = dbx.files_list_folder(carpeta_entrada, recursive=True)
    
    def agregar_entradas(entries):
        for entry in entries:
            if isinstance(entry, dropbox.files.FileMetadata) and \
               entry.name.lower().endswith(extensiones_validas):
                imagenes_metadata.append(entry)

    agregar_entradas(res.entries)
    while res.has_more:
        res = dbx.files_list_folder_continue(res.cursor)
        agregar_entradas(res.entries)

    # Ordenar por nombre
    imagenes_metadata.sort(key=lambda x: x.path_display)

    print("=" * 80)
    print(f"PROCESANDO {len(imagenes_metadata)} FOTOS ENCONTRADAS EN DROPBOX")
    print("=" * 80)


    # --- REEMPLAZA TODA LA SECCIÓN DE PROCESAMIENTO POR ESTA ---

    # 1. Definir offset al inicio (usando tu función existente)
    ultimo_poste = obtener_ubicacion_ultimo_poste()
    offset_numeracion = ultimo_poste['numero_poste'] if ultimo_poste else 0

    postes = []
    poste_actual = []
    umbral_distancia = 30
    conteo_cenitales_poste = 0 # Contador para el poste que se está procesando actualmente

    print("\n" + "=" * 80)
    print("PROCESANDO Y SUBIENDO DIRECTAMENTE A DROPBOX")
    print("=" * 80)

    for idx, metadata in enumerate(imagenes_metadata):
        nombre_base = metadata.name
        ruta_dbx = metadata.path_display
        
        # A. DESCARGAR BYTES
        _, res_dl = dbx.files_download(ruta_dbx)
        imagen_bytes = res_dl.content
        
        # B. EXTRAER METADATOS
        exif_data = obtener_metadata_exif(imagen_bytes)
        gps = extraer_gps(exif_data.get('GPSInfo')) if exif_data else None
        
        if gps:
            lat, lon = gps['latitud'], gps['longitud']
            
            # C. LÓGICA DE AGRUPACIÓN (POSTES)
            # Si hay cambio de poste, imprimimos auditoría del anterior
            if poste_actual:
                distancia = calcular_distancia_gps(poste_actual[-1]['lat'], poste_actual[-1]['lon'], lat, lon)
                if distancia >= umbral_distancia:
                    # Antes de pasar al siguiente, avisamos si el anterior falló auditoría
                    if conteo_cenitales_poste == 0:
                        print(f"    ⚠ AUDITORÍA: El Poste #{len(postes) + 1 + offset_numeracion} NO tuvo cenitales.")
                    
                    postes.append(poste_actual)
                    poste_actual = []
                    conteo_cenitales_poste = 0 # Reset para el nuevo poste

            # D. CLASIFICAR CENITAL / NODO
            es_cenital = es_foto_cenital(imagen_bytes)
            if es_cenital:
                subfolder = "Cenitales"
                conteo_cenitales_poste += 1
            else:
                subfolder = "Nodos"

            # E. DETERMINAR RUTA DE SALIDA EN DROPBOX
            numero_real = (len(postes) + 1) + offset_numeracion
            ruta_relativa_dbx = os.path.dirname(ruta_dbx)
            # Limpiar ruta para Dropbox (estilo URL)
            estructura_relativa = os.path.relpath(ruta_relativa_dbx, carpeta_entrada).replace("\\", "/")
            if estructura_relativa == ".": estructura_relativa = ""
            
            ruta_final_dbx = f"{carpeta_salida}/{estructura_relativa}/{subfolder}/{numero_real}/{nombre_base}".replace("//", "/")

            # F. SUBIR INMEDIATAMENTE
            try:
                dbx.files_upload(imagen_bytes, ruta_final_dbx, mode=dropbox.files.WriteMode.overwrite)
                label = "[CENITAL]" if es_cenital else "[NODO]"
                print(f"#{idx + 1} ↑ {label} Subida: {ruta_final_dbx}")
            except Exception as e:
                print(f"    ✗ Error al subir {nombre_base}: {e}")

            # G. GUARDAR METADATOS (Solo texto, nada de bytes para evitar MemoryError)
            poste_actual.append({
                'nombre': nombre_base,
                'lat': lat,
                'lon': lon,
                'es_cenital': es_cenital
            })

        # H. LIMPIEZA ABSOLUTA DE MEMORIA RAM
        del imagen_bytes
        del res_dl

    # Manejo del último poste procesado
    if poste_actual:
        if conteo_cenitales_poste == 0:
            print(f"    ⚠ AUDITORÍA: El Poste #{len(postes) + 1 + offset_numeracion} NO tuvo cenitales.")
        postes.append(poste_actual)

    print("\n" + "=" * 80)
    print("SUBIDA Y CLASIFICACIÓN FINALIZADA")
    print("=" * 80)
            
except FileNotFoundError:
    print(f"Error: No se encontró la carpeta {carpeta_entrada}")
except Exception as e:
    print(f"Error inesperado: {e}")
    import traceback
    traceback.print_exc()
