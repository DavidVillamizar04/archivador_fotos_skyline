import math

def extraer_datos_drone(fragmento_bytes):
    """
    Analiza un fragmento de bytes para extraer GPS, Pitch, Altitud y Yaw sin usar Pillow.
    Evita errores de memoria al no cargar la imagen completa.
    """
    resultado = {
        'latitud': None,
        'longitud': None,
        'altitud': 0.0,    # Se añade altitud
        'pitch': None,
        'gimbal_yaw': 0.0, # Se añade yaw para la triple confirmación
        'es_cenital': False
    }

    # 1. Extracción de Metadatos XMP (DJI utiliza etiquetas estandarizadas en texto)
    # Definimos los tags que queremos buscar en el fragmento de bytes
    tags_xmp = {
        'pitch': b'GimbalPitchDegree="',
        'latitud': b'GpsLatitude="',
        'longitud': b'GpsLongitude="',
        'altitud': b'AbsoluteAltitude="', # O 'RelativeAltitude="' según tu necesidad
        'gimbal_yaw': b'GimbalYawDegree="'
    }

    for clave, tag in tags_xmp.items():
        if tag in fragmento_bytes:
            try:
                inicio = fragmento_bytes.find(tag) + len(tag)
                fin = fragmento_bytes.find(b'"', inicio)
                valor = float(fragmento_bytes[inicio:fin].decode('utf-8'))
                resultado[clave] = valor
                
                # Definición de cenital basada en el Pitch
                if clave == 'pitch':
                    resultado['es_cenital'] = valor <= -80.0
            except (ValueError, UnicodeDecodeError):
                pass

    # Nota: Si AbsoluteAltitude no existe en tus fotos, puedes intentar buscar 
    # también 'RelativeAltitude="' como respaldo si el resultado sigue siendo 0.0
    if resultado['altitud'] == 0.0:
        tag_alt_rel = b'RelativeAltitude="'
        if tag_alt_rel in fragmento_bytes:
            try:
                inicio = fragmento_bytes.find(tag_alt_rel) + len(tag_alt_rel)
                fin = fragmento_bytes.find(b'"', inicio)
                resultado['altitud'] = float(fragmento_bytes[inicio:fin].decode('utf-8'))
            except:
                pass

    return resultado
def calcular_distancia_metros(p1, p2):
    """
    Calcula la distancia entre dos puntos usando Haversine.
    p1 y p2: diccionarios con {'latitud': float, 'longitud': float}
    """
    if None in [p1['latitud'], p1['longitud'], p2['latitud'], p2['longitud']]:
        return float('inf')

    # Radio de la Tierra en metros
    R = 6371000 
    
    phi1 = math.radians(p1['latitud'])
    phi2 = math.radians(p2['latitud'])
    delta_phi = math.radians(p2['latitud'] - p1['latitud'])
    delta_lambda = math.radians(p2['longitud'] - p1['longitud'])

    a = math.sin(delta_phi/2)**2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda/2)**2
    
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c