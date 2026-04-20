import dropbox
from dropbox.exceptions import ApiError
import os
from dotenv import load_dotenv

load_dotenv()

class DropboxConnector:
    def __init__(self):
        # Configuración de credenciales desde el .env
        self.app_key = os.getenv("DBX_APP_KEY")
        self.app_secret = os.getenv("DBX_APP_SECRET")
        self.refresh_token = os.getenv("DBX_REFRESH_TOKEN")
        
        # Conexión persistente con Refresh Token
        self.dbx = dropbox.Dropbox(
            app_key=self.app_key,
            app_secret=self.app_secret,
            oauth2_refresh_token=self.refresh_token,
            timeout=60.0
        )

    def listar_archivos_recursivo(self, ruta_carpeta):
        """
        Replica la lógica de tu script original para listar fotos 
        recursivamente y ordenarlas.
        """
        imagenes_metadata = []
        extensiones_validas = ('.jpg', '.jpeg', '.png', '.dng')
        
        try:
            res = self.dbx.files_list_folder(ruta_carpeta, recursive=True)
            
            def extraer_validos(entries):
                return [e for e in entries if isinstance(e, dropbox.files.FileMetadata) 
                        and e.name.lower().endswith(extensiones_validas)]

            imagenes_metadata.extend(extraer_validos(res.entries))
            
            while res.has_more:
                res = self.dbx.files_list_folder_continue(res.cursor)
                imagenes_metadata.extend(extraer_validos(res.entries))

            # Ordenar por ruta para mantener la secuencia del vuelo
            imagenes_metadata.sort(key=lambda x: x.path_display)
            return imagenes_metadata
        except ApiError as e:
            print(f"Error al listar: {e}")
            return []

    def descargar_fragmento(self, ruta_archivo, limite_bytes=262144):
        """
        Descarga solo el encabezado para EXIF/XMP (evita MemoryError).
        Usa request_custom para poder pasar el encabezado 'Range'.
        """
        try:
            # Definimos el rango en los encabezados HTTP
            headers = {'Range': f"bytes=0-{limite_bytes}"}
            
            # Usamos files_download (sin el argumento range) 
            # pero inyectamos el encabezado manualmente
            meta, response = self.dbx.files_download(ruta_archivo, headers=headers)
            
            fragmento = response.content
            response.close()
            return fragmento
        except Exception as e:
            # Si da error por el Range (algunos archivos muy pequeños), 
            # intentamos descarga normal
            try:
                meta, response = self.dbx.files_download(ruta_archivo)
                fragmento = response.content
                response.close()
                return fragmento
            except:
                print(f"Error crítico en {ruta_archivo}: {e}")
                return None

    def copiar_archivo(self, ruta_origen, ruta_destino):
        """
        En lugar de mover, COPIAMOS para proteger los originales.
        """
        try:
            self.dbx.files_copy_v2(ruta_origen, ruta_destino, autorename=True)
            return True
        except ApiError as e:
            print(f"Error al copiar {ruta_origen}: {e}")
            return False

    def obtener_ultimo_poste_remoto(self, carpeta_salida):
        """
        Adaptación de 'obtener_ubicacion_ultimo_poste' para trabajar 
        100% en la nube sin archivos locales.
        """
        try:
            res = self.dbx.files_list_folder(carpeta_salida)
            carpetas = [e.name for e in res.entries if isinstance(e, dropbox.files.FolderMetadata) 
                        and e.name.isdigit()]
            
            if not carpetas:
                return None
            
            ultima_carpeta_num = max(carpetas, key=int)
            # Retornamos el número para el offset de tu lógica original
            return int(ultima_carpeta_num)
        except ApiError:
            return None