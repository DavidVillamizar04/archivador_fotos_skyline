#!/bin/bash
# deploy.sh — Despliega el servicio en Cloud Run con timeout máximo de 3600s
# (1 hora). Para procesos de 12+ horas usa Cloud Run Jobs (ver README).

set -e

PROJECT_ID="TU_PROJECT_ID"
REGION="us-central1"
SERVICE_NAME="skyline-archivador"
IMAGE="gcr.io/$PROJECT_ID/$SERVICE_NAME"

echo "Build y push de la imagen..."
gcloud builds submit --tag "$IMAGE" .

echo "Desplegando en Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE" \
  --region "$REGION" \
  --platform managed \
  --no-allow-unauthenticated \
  --timeout 3600 \
  --memory 1Gi \
  --cpu 1 \
  --max-instances 1 \
  --set-env-vars "DBX_APP_KEY=${DBX_APP_KEY},DBX_APP_SECRET=${DBX_APP_SECRET},DBX_REFRESH_TOKEN=${DBX_REFRESH_TOKEN}"

echo "Listo. URL del servicio:"
gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format "value(status.url)"
