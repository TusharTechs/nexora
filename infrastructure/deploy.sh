#!/usr/bin/env bash
# One-shot deploy of the NEXORA API to Google Cloud Run.
# Prereqs: gcloud CLI authenticated, billing enabled, a GEMINI_API_KEY.
#
#   PROJECT_ID=your-project GEMINI_API_KEY=xxx ./infrastructure/deploy.sh
#
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
REPO="nexora"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/api:$(date +%Y%m%d-%H%M%S)"
SA="nexora-api@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Enabling APIs"
gcloud services enable run.googleapis.com cloudtasks.googleapis.com \
  cloudscheduler.googleapis.com firestore.googleapis.com aiplatform.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  cloudbuild.googleapis.com --project "$PROJECT_ID"

echo "==> Firestore (native mode) — ignore error if it already exists"
gcloud firestore databases create --location="$REGION" --project "$PROJECT_ID" || true

echo "==> Cloud Tasks queue"
gcloud tasks queues create nexora-workers --location="$REGION" --project "$PROJECT_ID" || true

echo "==> Artifact Registry repo"
gcloud artifacts repositories create "$REPO" --repository-format=docker \
  --location="$REGION" --project "$PROJECT_ID" || true

echo "==> Service account + IAM"
gcloud iam service-accounts create nexora-api --project "$PROJECT_ID" \
  --display-name "NEXORA API" || true
for ROLE in roles/datastore.user roles/cloudtasks.enqueuer roles/aiplatform.user \
            roles/run.invoker roles/iam.serviceAccountTokenCreator \
            roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${SA}" --role "$ROLE" --condition=None --quiet
done

echo "==> Gemini API key -> Secret Manager"
printf '%s' "${GEMINI_API_KEY:?set GEMINI_API_KEY}" | \
  gcloud secrets create nexora-gemini-api-key --data-file=- --project "$PROJECT_ID" 2>/dev/null || \
  printf '%s' "${GEMINI_API_KEY}" | \
  gcloud secrets versions add nexora-gemini-api-key --data-file=- --project "$PROJECT_ID"

echo "==> Build image (Cloud Build, from repo root)"
gcloud builds submit --tag "$IMAGE" --project "$PROJECT_ID" .

echo "==> Deploy to Cloud Run"
gcloud run deploy nexora-api \
  --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID" \
  --service-account "$SA" --timeout 600 --cpu 1 --memory 1Gi \
  --allow-unauthenticated \
  --set-env-vars "EXECUTION_MODE=MOCK,NEXORA_REPO=firestore,NEXORA_DISPATCHER=cloud,NEXORA_LLM_BACKEND=vertex,GCP_PROJECT_ID=${PROJECT_ID},GCP_LOCATION=${REGION},NEXORA_MODEL_T2=gemini-3.5-flash,NEXORA_WORKER_SA=${SA}" \
  --set-secrets "GEMINI_API_KEY=nexora-gemini-api-key:latest"

URL=$(gcloud run services describe nexora-api --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)')
echo "==> Wiring NEXORA_WORKER_URL=$URL"
gcloud run services update nexora-api --region "$REGION" --project "$PROJECT_ID" \
  --update-env-vars "NEXORA_WORKER_URL=${URL}"

echo "==> Cloud Scheduler: fire due mission schedules every minute"
gcloud scheduler jobs create http nexora-run-due --location="$REGION" --project "$PROJECT_ID" \
  --schedule="* * * * *" --uri="${URL}/internal/run_due" --http-method=POST \
  --oidc-service-account-email="$SA" --oidc-token-audience="${URL}" 2>/dev/null || \
gcloud scheduler jobs update http nexora-run-due --location="$REGION" --project "$PROJECT_ID" \
  --schedule="* * * * *" --uri="${URL}/internal/run_due" --http-method=POST \
  --oidc-service-account-email="$SA" --oidc-token-audience="${URL}"

echo
echo "NEXORA API is live: $URL"
echo "Try:  curl -s $URL/api/v1/capabilities | head -c 200"
