# 🛸 Skyline Drone Data Pipeline

Sistema automatizado para la clasificación, filtrado y organización de inspecciones fotográficas de infraestructura eléctrica (Postes ENEL) utilizando metadatos de drones DJI e integración con Dropbox API.

## 📌 Descripción del Proyecto
Este proyecto optimiza el flujo de trabajo de inspección técnica, eliminando la organización manual de miles de imágenes. El sistema analiza metadatos **XMP** y **EXIF** en tiempo real para tomar decisiones de clasificación basadas en la ubicación geográfica y la orientación del drone.

### Funcionalidades Clave
* **Detección de Postes:** Identifica fotos cenitales automáticamente cuando el Gimbal Pitch es ≤ -80°.
* **Filtro de Altitud Inteligente:** Si existen múltiples fotos cenitales de un mismo nodo, el sistema conserva la de mayor altitud (mejor perspectiva) en la carpeta principal.
* **Triple Confirmación:** Asigna fotos de detalle a cada poste evaluando proximidad geográfica, orientación del gimbal (Yaw) y cercanía relativa.
* **Resiliencia de API:** Manejo de errores `too_many_write_operations` mediante reintentos exponenciales para garantizar la integridad de los datos en Dropbox.
* **Persistencia de Estado:** Capacidad de pausar y reanudar procesos en diferentes subzonas manteniendo el conteo de postes correlativo.

## 🛠️ Requisitos Técnicos
* **Python 3.10+**
* **Dropbox SDK**
* **Metadatos DJI:** Imágenes con etiquetas XMP (AbsoluteAltitude, GimbalPitchDegree, GpsLatitude, etc.).

## 📂 Estructura del Repositorio
```text
skyline-project/
├── src/
│   ├── core/
│   │   └── drone_utils.py      # Extracción de metadatos XMP/GPS sin carga de memoria
│   ├── integrations/
│   │   └── dropbox_client.py   # Conector y gestión de archivos
│   └── scripts/
│       └── cloud_sync.py       # Orquestador principal del pipeline
├── logs/
│   └── nodos_criticos.log      # Reporte de postes con cobertura insuficiente (< 4 fotos)
└── README.md