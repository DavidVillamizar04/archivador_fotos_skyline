"""
main.py — Entry point para Cloud Run Job.

Cloud Run Jobs ejecuta este script directamente (sin servidor HTTP).
Cloud Scheduler dispara el Job via la API de Cloud Run, no via HTTP al contenedor.

Variables de entorno requeridas (configuradas en el Job, no en .env):
  DBX_APP_KEY           — Dropbox app key
  DBX_APP_SECRET        — Dropbox app secret
  DBX_REFRESH_TOKEN     — Dropbox refresh token
  GCS_BUCKET            — Nombre del bucket GCS para estado y logs
  DBX_CARPETA_ENTRADA   — (opcional) Ruta Dropbox de entrada
  DBX_CARPETA_SALIDA    — (opcional) Ruta Dropbox de salida
"""

from src.processors.cloud_sync import ejecutar_procesamiento_skyline

if __name__ == "__main__":
    ejecutar_procesamiento_skyline()
