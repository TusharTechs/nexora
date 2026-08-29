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

# Enable one service at a time with retries. Enabling many at once makes Google
# apply several service-agent IAM changes concurrently, which intermittently
# fails with "Exhausted maximum IAM policy modification retry attempts /
# DEADLINE_EXCEEDED" — a transient Google-side error, not a config problem.
enable_api() {  # $1 = service, $2 = "required" | "optional"
  local svc="$1" mode="${2:-required}" i
  for i in 1 2 3 4 5; do
    if gcloud services enable "$svc" --project "$PROJECT_ID" 2>/tmp/nx_enable_err; then
      return 0
    fi
    echo "    ($svc) enable attempt $i failed; retrying in $((i*15))s..."
    sed 's/^/      /' /tmp/nx_enable_err || true
    sleep $((i*15))
  done
  if [ "$mode" = "optional" ]; then
    echo "    ($svc) could not be enabled — continuing without it."
    return 1
  fi
  echo "ERROR: could not enable required service $svc after 5 attempts." >&2
  echo "       Wait a few minutes and re-run, or enable it manually:" >&2
  echo "         gcloud services enable $svc --project $PROJECT_ID" >&2
  exit 1
}

echo "==> Enabling APIs (one at a time, with retries)"
for svc in run.googleapis.com aiplatform.googleapis.com firestore.googleapis.com \
           artifactregistry.googleapis.com secretmanager.googleapis.com \
           cloudbuild.googleapis.com; do
  enable_api "$svc" required
done

# Cloud Tasks + Cloud Scheduler power durable dispatch and standing schedules.
# If either can't be enabled, NEXORA still runs fully — missions execute
# in-process (NEXORA_DISPATCHER=local) and "Run now" on a schedule still works;
# only auto-firing on a cron is lost.
DISPATCHER="cloud"
SCHEDULER_OK="yes"
enable_api cloudtasks.googleapis.com optional     || DISPATCHER="local"
enable_api cloudscheduler.googleapis.com optional || SCHEDULER_OK="no"
echo "    dispatcher: $DISPATCHER   scheduler cron: $SCHEDULER_OK"

echo "==> Firestore (native mode) — ignore error if it already exists"
gcloud firestore databases create --location="$REGION" --project "$PROJECT_ID" || true

if [ "$DISPATCHER" = "cloud" ]; then
  echo "==> Cloud Tasks queue"
  gcloud tasks queues create nexora-workers --location="$REGION" --project "$PROJECT_ID" || true
fi

echo "==> Artifact Registry repo"
gcloud artifacts repositories create "$REPO" --repository-format=docker \
  --location="$REGION" --project "$PROJECT_ID" || true

echo "==> Service account + IAM"
gcloud iam service-accounts create nexora-api --project "$PROJECT_ID" \
  --display-name "NEXORA API" || true
bind_role() {  # retry — IAM SetPolicy is also prone to transient DEADLINE_EXCEEDED
  local role="$1" i
  for i in 1 2 3 4 5; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member "serviceAccount:${SA}" --role "$role" --condition=None --quiet && return 0
    echo "    ($role) bind attempt $i failed; retrying in $((i*10))s..."
    sleep $((i*10))
  done
  echo "ERROR: could not bind $role to $SA." >&2
  exit 1
}
for ROLE in roles/datastore.user roles/cloudtasks.enqueuer roles/aiplatform.user \
            roles/run.invoker roles/iam.serviceAccountTokenCreator \
            roles/secretmanager.secretAccessor; do
  bind_role "$ROLE"
done

echo "==> Gemini API key -> Secret Manager"
printf '%s' "${GEMINI_API_KEY:?set GEMINI_API_KEY}" | \
  gcloud secrets create nexora-gemini-api-key --data-file=- --project "$PROJECT_ID" 2>/dev/null || \
  printf '%s' "${GEMINI_API_KEY}" | \
  gcloud secrets versions add nexora-gemini-api-key --data-file=- --project "$PROJECT_ID"

echo "==> Vertex AI Agent Engine (managed Sessions + Memory Bank)"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user" --condition=None --quiet || true

PY="${PYTHON:-python}"
if ! "$PY" -c 'import vertexai' 2>/dev/null; then
  echo "    installing google-cloud-aiplatform[agent_engines,adk] for the deploy helper..."
  "$PY" -m pip install -q 'google-cloud-aiplatform[agent_engines,adk]>=1.95' || true
fi
# Non-fatal: without an Agent Engine, the ADK workforce runs on an in-process
# runner and memory stays local (NEXORA_MEMORY unset). Still fully functional.
AGENT_ENGINE=$(GCP_PROJECT_ID="$PROJECT_ID" GCP_LOCATION="$REGION" \
  "$PY" infrastructure/deploy_agent_engine.py 2>/dev/null || true)
if [ -n "$AGENT_ENGINE" ]; then
  echo "    agent engine id: $AGENT_ENGINE"
  AE_ENV=",NEXORA_AGENT_ENGINE=${AGENT_ENGINE},NEXORA_MEMORY=memorybank"
else
  echo "    Agent Engine unavailable — deploying with in-process runner + local memory."
  AE_ENV=""
fi

echo "==> Build image (Cloud Build, from repo root)"
gcloud builds submit --tag "$IMAGE" --project "$PROJECT_ID" .

echo "==> Deploy to Cloud Run"
gcloud run deploy nexora-api \
  --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID" \
  --service-account "$SA" --timeout 600 --cpu 1 --memory 1Gi \
  --allow-unauthenticated \
  --set-env-vars "EXECUTION_MODE=MOCK,NEXORA_REPO=firestore,NEXORA_DISPATCHER=${DISPATCHER},NEXORA_LLM_BACKEND=vertex,GCP_PROJECT_ID=${PROJECT_ID},GCP_LOCATION=${REGION},NEXORA_MODEL_T2=gemini-3.5-flash,NEXORA_WORKER_SA=${SA}${AE_ENV}" \
  --set-secrets "GEMINI_API_KEY=nexora-gemini-api-key:latest"

URL=$(gcloud run services describe nexora-api --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)')
echo "==> Wiring worker URL + zero-trust OIDC gate for /internal/*"
gcloud run services update nexora-api --region "$REGION" --project "$PROJECT_ID" \
  --update-env-vars "NEXORA_WORKER_URL=${URL},NEXORA_INTERNAL_AUDIENCE=${URL},NEXORA_INTERNAL_SA=${SA}"

if [ "$SCHEDULER_OK" = "yes" ]; then
  echo "==> Cloud Scheduler: fire due mission schedules every minute"
  gcloud scheduler jobs create http nexora-run-due --location="$REGION" --project "$PROJECT_ID" \
    --schedule="* * * * *" --uri="${URL}/internal/run_due" --http-method=POST \
    --oidc-service-account-email="$SA" --oidc-token-audience="${URL}" 2>/dev/null || \
  gcloud scheduler jobs update http nexora-run-due --location="$REGION" --project "$PROJECT_ID" \
    --schedule="* * * * *" --uri="${URL}/internal/run_due" --http-method=POST \
    --oidc-service-account-email="$SA" --oidc-token-audience="${URL}"
else
  echo "==> Skipping Cloud Scheduler (API unavailable) — use the 'Run now'"
  echo "    button on a standing instruction, or POST /internal/run_due yourself."
fi

echo
echo "NEXORA API is live: $URL"
echo "Try:  curl -s $URL/api/v1/capabilities | head -c 200"
