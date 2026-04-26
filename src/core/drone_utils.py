import math

# Umbral mínimo de pitch para considerar una foto como cenital válida
PITCH_CENITAL = -80.0
# Umbral para promoción de clúster: si ninguna foto llega a -80°, se usa este como mínimo aceptable
PITCH_PROMOCION_MIN = -60.0

def extraer_datos_drone(fragmento_bytes):
    """
    Analiza un fragmento de bytes para extraer GPS, Pitch, Altitud y Yaw sin usar Pillow.
    Evita errores de memoria al no cargar la imagen completa.
    """
    resultado = {
        'latitud': None,
        'longitud': None,
        'altitud': 0.0,
        'pitch': None,
        'gimbal_yaw': 0.0,
        'es_cenital': False
    }

    tags_xmp = {
        'pitch':      b'GimbalPitchDegree="',
        'latitud':    b'GpsLatitude="',
        'longitud':   b'GpsLongitude="',
        'altitud':    b'AbsoluteAltitude="',
        'gimbal_yaw': b'GimbalYawDegree="'
    }

    for clave, tag in tags_xmp.items():
        if tag in fragmento_bytes:
            try:
                inicio = fragmento_bytes.find(tag) + len(tag)
                fin = fragmento_bytes.find(b'"', inicio)
                valor = float(fragmento_bytes[inicio:fin].decode('utf-8'))
                resultado[clave] = valor
                if clave == 'pitch':
                    resultado['es_cenital'] = valor <= PITCH_CENITAL
            except (ValueError, UnicodeDecodeError):
                pass

    # Fallback a altitud relativa si la absoluta no existe
    if resultado['altitud'] == 0.0:
        tag_alt_rel = b'RelativeAltitude="'
        if tag_alt_rel in fragmento_bytes:
            try:
                inicio = fragmento_bytes.find(tag_alt_rel) + len(tag_alt_rel)
                fin = fragmento_bytes.find(b'"', inicio)
                resultado['altitud'] = float(fragmento_bytes[inicio:fin].decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                pass

    return resultado


def calcular_distancia_metros(p1, p2):
    """
    Calcula la distancia entre dos puntos GPS usando la fórmula de Haversine.
    p1 y p2: diccionarios con {'latitud': float, 'longitud': float}
    """
    if None in [p1['latitud'], p1['longitud'], p2['latitud'], p2['longitud']]:
        return float('inf')

    R = 6371000
    phi1 = math.radians(p1['latitud'])
    phi2 = math.radians(p2['latitud'])
    delta_phi = math.radians(p2['latitud'] - p1['latitud'])
    delta_lambda = math.radians(p2['longitud'] - p1['longitud'])

    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2) ** 2

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def calcular_rumbo(punto1, punto2):
    """
    Calcula el azimut/rumbo (0-360°) entre dos puntos GPS.
    Centralizado aquí para evitar duplicación con cloud_sync.py.
    """
    lat1 = math.radians(punto1['latitud'])
    lon1 = math.radians(punto1['longitud'])
    lat2 = math.radians(punto2['latitud'])
    lon2 = math.radians(punto2['longitud'])
    d_lon = lon2 - lon1
    y = math.sin(d_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def tiene_gps_valido(datos):
    """Verifica que los datos de una foto tengan coordenadas GPS utilizables."""
    return datos['latitud'] is not None and datos['longitud'] is not None