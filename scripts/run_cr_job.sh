#!/usr/bin/env bash
# Run CR job to get product images
set -euo pipefail

PROJECT_ID="hm-studios-metadata-c54a"
REGION="europe-west1"
ENVIRONMENT="dev"
IMG_NAME="europe-west1-docker.pkg.dev/${PROJECT_ID}/annotate-ar-${ENVIRONMENT}/annotations:latest"

SA_NAME="cr-job-sa-${ENVIRONMENT}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

CPU=2
MEMORY="6Gi"
TIMEOUT="86400s" # 24 hours
ARGS="src/annotate.py"

gcloud run jobs deploy annotate-images \
  --image="$IMG_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --cpu="$CPU" \
  --memory="$MEMORY" \
  --task-timeout="$TIMEOUT" \
  --service-account="$SA_EMAIL" \
  --command=python \
  --args="$ARGS" \
  --verbosity=warning \
  --execute-now