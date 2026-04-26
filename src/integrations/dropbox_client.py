import dropbox
from dropbox.exceptions import ApiError
import os
import requests
from dotenv import load_dotenv

load_dotenv()

# Cuántos bytes leer del encabezado para extraer XMP/EXIF.
# 256 KB es suficiente para la mayoría de drones DJI; puedes bajar a 128 KB si quieres más velocidad.
LIMITE_FRAGMENTO_BYTES = 262144  # 256 KB


class DropboxConnector:
    def __init__(self):
        self.app_key = os.getenv("DBX_APP_KEY")
        self.app_secret = os.getenv("DBX_APP_SECRET")
        self.refresh_token = os.getenv("DBX_REFRESH_TOKEN")

        self.dbx = dropbox.Dropbox(
            app_key=self.app_key,
            app_secret=self.app_secret,
            oauth2_refresh_token=self.refresh_token,
            timeout=60.0
        )

    def listar_archivos_recursivo(self, ruta_carpeta):
        """
        Lista recursivamente todas las imágenes válidas dentro de una carpeta de Dropbox.
        Retorna una lista de FileMetadata ordenada por ruta.
        """
        imagenes_metadata = []
        extensiones_validas = ('.jpg', '.jpeg', '.png', '.dng')

        try:
            res = self.dbx.files_list_folder(ruta_carpeta, recursive=True)

            def extraer_validos(entries):
                return [
                    e for e in entries
                    if isinstance(e, dropbox.files.FileMetadata)
                    and e.name.lower().endswith(extensiones_validas)
                ]

            imagenes_metadata.extend(extraer_validos(res.entries))

            while res.has_more:
                res = self.dbx.files_list_folder_continue(res.cursor)
                imagenes_metadata.extend(extraer_validos(res.entries))

            imagenes_metadata.sort(key=lambda x: x.path_display)
            return imagenes_metadata

        except ApiError as e:
            print(f"[ERROR] Al listar '{ruta_carpeta}': {e}")
            return []

    def descargar_fragmento(self, ruta_archivo, limite_bytes=LIMITE_FRAGMENTO_BYTES):
        """
        Descarga SOLO el encabezado del archivo para extraer metadatos XMP/EXIF.

        Usa una URL temporal de Dropbox + el header HTTP 'Range' para pedir
        únicamente los primeros N bytes. Esto es lo que realmente evita bajar
        la imagen completa (4K ~20 MB por foto).

        La SDK de Dropbox no expone el header Range directamente en files_download,
        por eso obtenemos la URL temporal y hacemos la petición con `requests`.
        """
        try:
            # Paso 1: Obtener URL temporal de descarga (no consume cuota de lectura extra)
            link_result = self.dbx.files_get_temporary_link(ruta_archivo)
            url_temporal = link_result.link

            # Paso 2: Pedir solo los primeros N bytes vía HTTP Range
            headers = {'Range': f'bytes=0-{limite_bytes - 1}'}
            response = requests.get(url_temporal, headers=headers, timeout=30)

            # 206 = Partial Content (éxito con Range), 200 = archivo muy pequeño
            if response.status_code in (200, 206):
                return response.content

            print(f"[WARN] Respuesta inesperada {response.status_code} para {ruta_archivo}")
            return None

        except Exception as e:
            print(f"[ERROR] Al descargar fragmento de '{ruta_archivo}': {e}")
            return None

    def copiar_archivo(self, ruta_origen, ruta_destino):
        """
        Copia un archivo en Dropbox (sin mover, para proteger los originales).
        Usa autorename=True para evitar colisiones en Nodos/ donde pueden
        coexistir fotos con el mismo nombre de distintos vuelos.
        Retorna True si tuvo éxito.
        """
        try:
            self.dbx.files_copy_v2(ruta_origen, ruta_destino, autorename=True)
            return True
        except ApiError as e:
            print(f"[ERROR] Al copiar '{ruta_origen}': {e}")
            return False

    def reemplazar_cenital(self, ruta_origen, ruta_destino):
        """
        Reemplaza una cenital existente eliminando primero el archivo anterior.
        Usar SOLO para Cenitales/ donde debe existir exactamente un archivo por poste.

        NO usar autorename aquí: si existiera 1(1).jpg significaría que una
        ejecución anterior falló a mitad — en ese caso borramos todo y copiamos limpio.
        """
        # Borrar cualquier archivo previo en esa ruta exacta (ignora error si no existe)
        try:
            self.dbx.files_delete_v2(ruta_destino)
        except ApiError:
            pass  # No existía, no hay problema

        # Ahora copiar sin autorename — la ruta destino está limpia
        try:
            self.dbx.files_copy_v2(ruta_origen, ruta_destino, autorename=False)
            return True
        except ApiError as e:
            print(f"[ERROR] Al reemplazar cenital '{ruta_destino}': {e}")
            return False

    def obtener_ultimo_poste_remoto(self, carpeta_salida):
        """
        Revisa la carpeta de salida en Dropbox y retorna el número del último
        poste ya procesado (para continuar desde ahí en la próxima ejecución).
        Retorna None si la carpeta no existe o está vacía.
        """
        try:
            res = self.dbx.files_list_folder(carpeta_salida)
            carpetas = [
                e.name for e in res.entries
                if isinstance(e, dropbox.files.FolderMetadata) and e.name.isdigit()
            ]
            if not carpetas:
                return None
            return int(max(carpetas, key=int))

        except ApiError:
            return None