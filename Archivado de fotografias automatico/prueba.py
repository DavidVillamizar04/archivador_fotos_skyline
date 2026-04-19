import re
import os

def verificar_inclinacion_local(ruta_archivo):
    try:
        if not os.path.exists(ruta_archivo):
            print(f"Error: No se encuentra el archivo en {ruta_archivo}")
            return

        # 1. Leer el archivo en modo binario
        with open(ruta_archivo, 'rb') as f:
            imagen_bytes = f.read()
        
        # 2. Decodificar buscando metadatos XMP
        # Usamos latin-1 para evitar errores con los datos binarios de la imagen
        contenido_texto = imagen_bytes.decode('latin-1', errors='ignore')
        
        # 3. Buscar el campo GimbalPitchDegree de DJI
        match = re.search(r'GimbalPitchDegree="([^"]+)"', contenido_texto)
        
        if match:
            pitch = float(match.group(1))
            print(f"Archivo: {os.path.basename(ruta_archivo)}")
            print(f"Inclinación del Gimbal: {pitch}°")
            
            # Clasificación según tu lógica
            if pitch <= -85:
                print("Resultado: Es una foto [CENITAL]")
            else:
                print("Resultado: Es una foto de [NODO]")
        else:
            print("No se encontró el metadato 'GimbalPitchDegree'.")
            print("Asegúrate de que la foto sea original de un dron DJI.")
            
    except Exception as e:
        print(f"Error al procesar la imagen: {e}")

# --- CAMBIA ESTA RUTA POR LA DE TU FOTO ---
ruta_test = r"Archivado de fotografias automatico\Data\DJI_0448.JPG"
verificar_inclinacion_local(ruta_test)