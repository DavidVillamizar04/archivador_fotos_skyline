import zipfile
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS
from io import BytesIO
import os
import math

# Ruta del archivo ZIP
zip_path = "Archivado de fotografias automatico/Data/DJI_001_CACHIMBULO.zip"
carpeta_salida = "Archivado de fotografias automatico/Nodos"
carpeta_cenitales = "Archivado de fotografias automatico/Cenitales"

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
            if angulo <= -88.0:
                return True
        except ValueError:
            pass
            
    return False

# Crear carpeta de salida si no existe
if not os.path.exists(carpeta_salida):
    os.makedirs(carpeta_salida)

# Crear carpeta cenitales si no existe
if not os.path.exists(carpeta_cenitales):
    os.makedirs(carpeta_cenitales)

try:
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # Obtener la lista de información de archivos
        file_list = zip_ref.infolist()
        
        # Filtrar solo imágenes
        imagenes = [a for a in file_list if not a.is_dir() and a.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.dng'))]
        
        print("=" * 80)
        print(f"PROCESANDO TODAS LAS FOTOS")
        print("=" * 80)
        
        # Verificar si hay postes existentes (mismo circuito)
        ultimo_poste = obtener_ubicacion_ultimo_poste()
        offset_numeracion = 0
        
        if ultimo_poste:
            print(f"Último poste existente: #{ultimo_poste['numero_poste']} "
                  f"({ultimo_poste['cantidad_fotos']} fotos)")
            print(f"Ubicación: {ultimo_poste['lat']:.6f}° N, {ultimo_poste['lon']:.6f}° W")
            
            # Obtener coordenadas de la primera foto nueva
            primera_foto = imagenes[0]
            imagen_bytes = zip_ref.read(primera_foto.filename)
            exif_data = obtener_metadata_exif(imagen_bytes)
            del imagen_bytes
            
            if exif_data:
                gps_primera = extraer_gps(exif_data.get('GPSInfo'))
                if gps_primera:
                    distancia_circuito = calcular_distancia_gps(
                        ultimo_poste['lat'], ultimo_poste['lon'],
                        gps_primera['latitud'], gps_primera['longitud']
                    )
                    
                    print(f"Primera foto nueva: {gps_primera['latitud']:.6f}° N, {gps_primera['longitud']:.6f}° W")
                    print(f"Distancia al último poste: {distancia_circuito:.2f} metros")
                    
                    # Umbral: 100-250 metros (usamos 200m como promedio)
                    if distancia_circuito <= 200:
                        offset_numeracion = ultimo_poste['numero_poste']
                        print("✓ MISMO CIRCUITO - Continuando numeración")
                    else:
                        print("✗ CIRCUITO NUEVO - Iniciando numeración desde 1")
                else:
                    print("No se pudieron obtener coordenadas de la primera foto")
            else:
                print("No se pudieron leer metadatos de la primera foto")
        else:
            print("No hay postes existentes - Iniciando numeración desde 1")
        
        # Procesar todas las fotos
        fotos_procesadas = []
        postes = []  # Lista de postes, cada uno contiene sus fotos
        poste_actual = []
        umbral_distancia = 15  # metros
        
        for idx, archivo in enumerate(imagenes):
            print(f"\nFoto #{idx + 1}: {archivo.filename}")
            print("-" * 80)
            
            # Extraer imagen solo para obtener metadatos EXIF
            imagen_bytes = zip_ref.read(archivo.filename)
            exif_data = obtener_metadata_exif(imagen_bytes)
            
            # Liberar memoria inmediatamente
            del imagen_bytes
            
            if exif_data:
                gps = extraer_gps(exif_data.get('GPSInfo'))
                
                if gps:
                    lat = gps['latitud']
                    lon = gps['longitud']
                    alt = gps['altitud']
                    
                    print(f"Coordenadas: {lat:.6f}° N, {lon:.6f}° W")
                    print(f"Altitud: {alt} m" if alt else "Altitud: No disponible")
                    
                    # Lógica para agrupar fotos por poste
                    if not poste_actual:
                        # Primera foto
                        poste_actual = [{
                            'archivo': archivo.filename,
                            'lat': lat,
                            'lon': lon,
                            'alt': alt
                        }]
                        print("✓ Nuevo poste iniciado")
                    else:
                        # Comparar con la última foto del poste actual
                        ultima_foto = poste_actual[-1]
                        distancia = calcular_distancia_gps(ultima_foto['lat'], ultima_foto['lon'], lat, lon)
                        
                        if distancia < umbral_distancia:
                            # Misma poste
                            poste_actual.append({
                                'archivo': archivo.filename,
                                'lat': lat,
                                'lon': lon,
                                'alt': alt
                            })
                            print(f"✓ Agregada al poste actual (distancia: {distancia:.2f} m)")
                        else:
                            # Nuevo poste
                            postes.append(poste_actual)
                            poste_actual = [{
                                'archivo': archivo.filename,
                                'lat': lat,
                                'lon': lon,
                                'alt': alt
                            }]
                            print(f"✗ NUEVO POSTE (distancia anterior: {distancia:.2f} m)")
                    
                    fotos_procesadas.append({
                        'nombre': archivo.filename,
                        'lat': lat,
                        'lon': lon
                    })
        
        # Agregar el último poste
        if poste_actual:
            postes.append(poste_actual)
        
        # Guardar las fotos en carpetas
        print("\n" + "=" * 80)
        print("GUARDANDO FOTOS EN CARPETAS")
        print("=" * 80)
        
        for num_poste, poste in enumerate(postes, 1):
            numero_real = num_poste + offset_numeracion
            carpeta_poste = os.path.join(carpeta_salida, str(numero_real))
            os.makedirs(carpeta_poste, exist_ok=True)
            
# --- INICIO DEL CICLO MODIFICADO ---
            print(f"\nPoste #{numero_real}:")
            print(f"  Carpeta Nodo: {carpeta_poste}")
            print(f"  Carpeta Cenital: {os.path.join(carpeta_cenitales, str(numero_real))}")
            
            conteo_cenitales = 0
            for foto in poste:
                # Leer bytes de la foto
                imagen_bytes = zip_ref.read(foto['archivo'])
                nombre_archivo = os.path.basename(foto['archivo'])
                
                # Clasificar según el ángulo del Gimbal
                if es_foto_cenital(imagen_bytes):
                    # Definir ruta en carpeta de Cenitales
                    ruta_dir = os.path.join(carpeta_cenitales, str(numero_real))
                    os.makedirs(ruta_dir, exist_ok=True)
                    ruta_final = os.path.join(ruta_dir, nombre_archivo)
                    label = "[CENITAL]"
                    conteo_cenitales += 1
                else:
                    # Definir ruta en carpeta de Nodo normal
                    ruta_final = os.path.join(carpeta_poste, nombre_archivo)
                    label = "[NODO]"
                
                # Guardar el archivo en la ubicación decidida
                with open(ruta_final, 'wb') as f:
                    f.write(imagen_bytes)
                
                print(f"    ✓ {label} Guardada: {nombre_archivo}")

            if conteo_cenitales == 0:
                print("    ⚠ Nota: No se detectaron fotos cenitales por ángulo en este poste.")
            # --- FIN DEL CICLO MODIFICADO ---
        
        # Imprimir resumen por carpeta
        print("\n" + "=" * 80)
        print("RESUMEN DE POSTES IDENTIFICADOS")
        print("=" * 80)
        
        postes_coordenadas = []  # Guardar coordenadas promedio de cada poste
        
        for num_poste, poste in enumerate(postes, 1):
            numero_real = num_poste + offset_numeracion
            # Calcular coordenadas promedio
            lat_promedio = sum(foto['lat'] for foto in poste) / len(poste)
            lon_promedio = sum(foto['lon'] for foto in poste) / len(poste)
            postes_coordenadas.append((lat_promedio, lon_promedio))
            
            print(f"\nPoste #{numero_real}:")
            print(f"  Cantidad de fotos: {len(poste)}")
            print(f"  Ubicación promedio: {lat_promedio:.6f}° N, {lon_promedio:.6f}° W")
            
            # Mostrar distancia respecto al poste anterior
            if num_poste > 1:
                lat_anterior, lon_anterior = postes_coordenadas[num_poste - 2]
                distancia_anterior = calcular_distancia_gps(lat_anterior, lon_anterior, lat_promedio, lon_promedio)
                print(f"  Distancia del poste anterior: {distancia_anterior:.2f} metros")
            
            print(f"  Google Maps: https://maps.google.com/?q={lat_promedio},{lon_promedio}")
        
        print("\n" + "=" * 80)
        
        # Listado de postes con menos de 4 fotos para auditoría
        print("POSTES CON MENOS DE 4 FOTOS (REQUIEREN AUDITORÍA)")
        print("=" * 80)
        
        postes_auditoria = []
        for num_poste, poste in enumerate(postes, 1):
            numero_real = num_poste + offset_numeracion
            if len(poste) < 4:
                postes_auditoria.append(numero_real)
                print(f"Poste #{numero_real}: {len(poste)} fotos")
        
        if not postes_auditoria:
            print("Todos los postes tienen 4 o más fotos.")
        else:
            print(f"\nTotal de postes para auditoría: {len(postes_auditoria)}")
            
except FileNotFoundError:
    print(f"Error: No se encontró el archivo {zip_path}")
except zipfile.BadZipFile:
    print(f"Error: {zip_path} no es un archivo ZIP válido")
except Exception as e:
    print(f"Error inesperado: {e}")
    import traceback
    traceback.print_exc()
