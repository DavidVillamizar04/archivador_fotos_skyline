"""
gcs_client.py — Capa de persistencia en Google Cloud Storage.

Reemplaza las lecturas/escrituras de archivos locales (zona_state.json,
nodos_criticos.log) por operaciones contra un bucket de GCS.

El bucket se lee de la variable de entorno GCS_BUCKET.
Las credenciales se resuelven automáticamente desde el Service Account
asociado al Cloud Run Job (no se necesita ningún archivo de clave).
"""

import os
import json
import datetime
from google.cloud import storage
from google.api_core.exceptions import NotFound

_GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
_BLOB_ESTADO = "zona_state.json"
_BLOB_LOG    = "nodos_criticos.log"

# Cliente singleton (thread-safe para lectura; escrituras son secuenciales en el Job)
_cliente: storage.Client | None = None


def _bucket() -> storage.Bucket:
    global _cliente
    if _cliente is None:
        _cliente = storage.Client()
    return _cliente.bucket(_GCS_BUCKET)


# ---------------------------------------------------------------------------
# Estado de zonas (zona_state.json)
# ---------------------------------------------------------------------------

def cargar_estado_zonas() -> dict:
    """
    Lee el JSON de estado desde GCS.
    Retorna dict vacío si el objeto aún no existe (primera ejecución).
    """
    try:
        blob = _bucket().blob(_BLOB_ESTADO)
        contenido = blob.download_as_text(encoding="utf-8")
        return json.loads(contenido)
    except NotFound:
        return {}
    except Exception as e:
        print(f"[GCS][WARN] No se pudo leer {_BLOB_ESTADO}: {e}")
        return {}


def guardar_estado_zonas(estado: dict) -> None:
    """
    Sube el JSON de estado a GCS sobreescribiendo el blob anterior.
    Falla en voz alta para que el Job quede marcado como fallido en GCP
    si el checkpoint no se puede guardar.
    """
    blob = _bucket().blob(_BLOB_ESTADO)
    blob.upload_from_string(
        json.dumps(estado, ensure_ascii=False, indent=2),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Log de auditoría (nodos_criticos.log)
# ---------------------------------------------------------------------------

def registrar_en_log(linea: str) -> None:
    """
    Agrega una línea al log de auditoría en GCS usando download + upload
    (GCS no tiene append nativo). Para bajo volumen de escrituras de log
    esto es perfectamente aceptable; si se necesitara alta frecuencia
    habría que bufferizar en memoria y hacer un único upload al final.
    """
    blob = _bucket().blob(_BLOB_LOG)
    try:
        contenido_actual = blob.download_as_text(encoding="utf-8")
    except NotFound:
        contenido_actual = ""
    except Exception as e:
        print(f"[GCS][WARN] No se pudo leer {_BLOB_LOG}: {e}")
        contenido_actual = ""

    blob.upload_from_string(
        contenido_actual + linea + "\n",
        content_type="text/plain",
    )
