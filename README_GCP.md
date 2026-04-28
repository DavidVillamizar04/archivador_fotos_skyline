# Skyline Archivador — Despliegue en Google Cloud Platform

## Arquitectura final

```
GitHub (push a main)
       │
       ▼
  Cloud Build          ← build + push imagen a Artifact Registry
       │  actualiza imagen del Job
       ▼
  Cloud Run Job        ← proceso batch, timeout hasta 24h, sin HTTP
  (skyline-archivador)
       │ lee/escribe
       ├──────────────► GCS Bucket  (zona_state.json, nodos_criticos.log)
       │ descarga metadatos / copia archivos
       └──────────────► Dropbox API

  Cloud Scheduler      ← dispara el Job según cron (ej. diario a las 2 AM)
       │
       ▼
  Cloud Run Jobs API
```

---

## Prereqs

- `gcloud` CLI instalado y autenticado (`gcloud auth login`)
- Proyecto GCP con facturación activa
- Docker instalado localmente (solo para pruebas locales)

Exporta tu Project ID en la terminal antes de ejecutar los comandos:
```bash
export PROJECT_ID="tu-project-id"
export REGION="us-central1"
export SERVICE="skyline-archivador"
export REPO="skyline"
export BUCKET="skyline-estado-${PROJECT_ID}"
```

---

## Paso 1 — Habilitar APIs necesarias

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  cloudscheduler.googleapis.com \
  --project=$PROJECT_ID
```

---

## Paso 2 — Crear el bucket de GCS para estado y logs

```bash
gcloud storage buckets create gs://$BUCKET \
  --project=$PROJECT_ID \
  --location=$REGION \
  --uniform-bucket-level-access
```

El bucket almacenará:
- `zona_state.json` — estado de procesamiento por zona (checkpoint)
- `nodos_criticos.log` — log de auditoría de nodos con pocas fotos o sin cenital

---

## Paso 3 — Guardar credenciales en Secret Manager

Nunca subas el `.env` al repo. Las credenciales viven en Secret Manager:

```bash
# Credenciales de Dropbox
echo -n "jiw2p6ffd1by371"    | gcloud secrets create DBX_APP_KEY     --data-file=- --project=$PROJECT_ID
echo -n "uacpg2im28lafm9"    | gcloud secrets create DBX_APP_SECRET  --data-file=- --project=$PROJECT_ID
echo -n "Q3ZsA29w534AAAA..." | gcloud secrets create DBX_REFRESH_TOKEN --data-file=- --project=$PROJECT_ID
```

Para actualizar un secret en el futuro:
```bash
echo -n "nuevo_valor" | gcloud secrets versions add DBX_REFRESH_TOKEN --data-file=- --project=$PROJECT_ID
```

---

## Paso 4 — Service Account para el Job

```bash
gcloud iam service-accounts create skyline-job-sa \
  --display-name="Skyline Job SA" \
  --project=$PROJECT_ID

SA="skyline-job-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Leer secrets
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role="roles/secretmanager.secretAccessor"

# Leer y escribir en el bucket
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
  --member="serviceAccount:$SA" \
  --role="roles/storage.objectAdmin"
```

---

## Paso 5 — Repositorio de imágenes en Artifact Registry

```bash
gcloud artifacts repositories create $REPO \
  --repository-format=docker \
  --location=$REGION \
  --project=$PROJECT_ID
```

---

## Paso 6 — Primer build y deploy manual

Solo necesitas hacer esto una vez. Después el CI/CD lo hace en cada push.

```bash
# Build y push
gcloud builds submit \
  --tag="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:latest" \
  --project=$PROJECT_ID \
  .

# Crear el Cloud Run Job
gcloud run jobs create $SERVICE \
  --image="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:latest" \
  --region=$REGION \
  --service-account="skyline-job-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --task-timeout=43200 \
  --memory=1Gi \
  --cpu=1 \
  --max-retries=0 \
  --set-secrets="DBX_APP_KEY=DBX_APP_KEY:latest,DBX_APP_SECRET=DBX_APP_SECRET:latest,DBX_REFRESH_TOKEN=DBX_REFRESH_TOKEN:latest" \
  --set-env-vars="GCS_BUCKET=${BUCKET}" \
  --project=$PROJECT_ID
```

> `--task-timeout=43200` = 12 horas. Máximo posible: `86400` (24h).
> `--max-retries=0` evita que el Job se reintente si falla (el checkpoint en GCS
> permite retomarlo manualmente en la siguiente ejecución del cron).

---

## Paso 7 — Cloud Scheduler (cron)

```bash
# Service account para que Scheduler pueda lanzar el Job
SA_SCHEDULER="skyline-scheduler-sa@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create skyline-scheduler-sa \
  --display-name="Skyline Scheduler SA" \
  --project=$PROJECT_ID

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_SCHEDULER" \
  --role="roles/run.invoker"

# Crear el job de Scheduler — ejecuta todos los días a las 2 AM hora Colombia (UTC-5 = 07:00 UTC)
gcloud scheduler jobs create http skyline-cron \
  --schedule="0 7 * * *" \
  --uri="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${SERVICE}:run" \
  --http-method=POST \
  --oauth-service-account-email=$SA_SCHEDULER \
  --location=$REGION \
  --project=$PROJECT_ID
```

Para cambiar el horario:
```bash
gcloud scheduler jobs update http skyline-cron \
  --schedule="0 7 * * 1-5" \
  --location=$REGION \
  --project=$PROJECT_ID
```

Para ejecutar manualmente (sin esperar el cron):
```bash
gcloud run jobs execute $SERVICE --region=$REGION --project=$PROJECT_ID
```

---

## Paso 8 — CI/CD con Cloud Build (push a main → deploy automático)

### 8.1 Dar permisos a Cloud Build

```bash
CB_SA="$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')@cloudbuild.gserviceaccount.com"

# Subir imágenes a Artifact Registry
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$CB_SA" \
  --role="roles/artifactregistry.writer"

# Actualizar el Cloud Run Job
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$CB_SA" \
  --role="roles/run.developer"

# El Job necesita un SA — Cloud Build debe poder usarlo
gcloud iam service-accounts add-iam-policy-binding \
  "skyline-job-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --member="serviceAccount:$CB_SA" \
  --role="roles/iam.serviceAccountUser" \
  --project=$PROJECT_ID
```

### 8.2 Conectar el repositorio de GitHub

1. Ve a **Cloud Build → Triggers** en la consola de GCP.
2. Haz clic en **"Connect Repository"**.
3. Selecciona **GitHub** y autoriza la aplicación de Cloud Build.
4. Elige el repositorio `archivador_fotos_skyline`.

### 8.3 Crear el trigger

```bash
gcloud builds triggers create github \
  --repo-name="archivador_fotos_skyline" \
  --repo-owner="TU_USUARIO_GITHUB" \
  --branch-pattern="^main$" \
  --build-config="cloudbuild.yaml" \
  --region=$REGION \
  --project=$PROJECT_ID
```

O desde la consola: **Cloud Build → Triggers → Create Trigger**:
- Evento: **Push to a branch**
- Rama: `^main$`
- Configuración: **Cloud Build configuration file** → `cloudbuild.yaml`

### 8.4 Flujo resultante

```
git push origin main
       │
       ▼  (automático, ~2-3 min)
  Cloud Build
    1. docker build
    2. docker push → Artifact Registry
    3. gcloud run jobs update → nueva imagen activa en el Job
       │
       ▼  (próxima ejecución del cron o manual)
  Cloud Run Job corre con el código nuevo
```

---

## Variables de entorno del Job (resumen)

| Variable              | Fuente        | Descripción                          |
|-----------------------|---------------|--------------------------------------|
| `DBX_APP_KEY`         | Secret Manager | Dropbox app key                     |
| `DBX_APP_SECRET`      | Secret Manager | Dropbox app secret                  |
| `DBX_REFRESH_TOKEN`   | Secret Manager | Dropbox refresh token               |
| `GCS_BUCKET`          | Env var        | Bucket para estado y logs           |
| `DBX_CARPETA_ENTRADA` | Env var (opt.) | Ruta entrada Dropbox                |
| `DBX_CARPETA_SALIDA`  | Env var (opt.) | Ruta salida Dropbox                 |

Para actualizar variables de entorno sin redesplegar la imagen:
```bash
gcloud run jobs update $SERVICE \
  --region=$REGION \
  --set-env-vars="GCS_BUCKET=${BUCKET},DBX_CARPETA_ENTRADA=/nueva/ruta" \
  --project=$PROJECT_ID
```

---

## Monitoreo

- **Logs del Job**: Cloud Console → Cloud Run → Jobs → `skyline-archivador` → Historial de ejecuciones
- **Log de auditoría**: `gsutil cat gs://$BUCKET/nodos_criticos.log`
- **Estado actual**: `gsutil cat gs://$BUCKET/zona_state.json`
- **Resetear estado de una zona** (para reprocesar desde cero):
  ```bash
  # Descargar, editar, subir
  gsutil cp gs://$BUCKET/zona_state.json .
  # Editar zona_state.json y borrar la clave de la zona que quieras resetear
  gsutil cp zona_state.json gs://$BUCKET/zona_state.json
  ```
