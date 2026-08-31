#!/usr/bin/env bash
# One-shot deploy of the NEXORA API to Google Cloud Run.
#
# Prereqs: gcloud CLI authenticated, billing enabled.
#
#   PROJECT_ID=your-project ./infrastructure/deploy.sh
#
# Profiles (NEXORA_PROFILE):
#   demo  (default) — in-process task graph, in-memory mission state, one warm
#                     instance. Rock-solid for a judge/demo review; missions are
#                     lost if the instance restarts. No Cloud Tasks / Scheduler.
#   scale           — Cloud Tasks fan-out + Firestore state + Cloud Scheduler.
#                     Durable and horizontally scalable.
#
# GEMINI_API_KEY is optional. The whole stack runs on Vertex AI via the service
# account's ADC; a key is only used for the (optional) Gemma firewall
# second-opinion, which is served from the Gemini API.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
PROFILE="${NEXORA_PROFILE:-demo}"
REPO="nexora"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/api:$(date +%Y%m%d-%H%M%S)"
SA="nexora-api@${PROJECT_ID}.iam.gserviceaccount.com"
GEMINI_API_KEY="${GEMINI_API_KEY:-}"
# Optional: enable the LIVE (real Google Workspace) OAuth flow on the deployed
# service. Provide both to turn it on; add "<service-url>/api/v1/auth/callback"
# to the OAuth client's Authorized redirect URIs first.
GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-}"
GOOGLE_CLIENT_SECRET="${GOOGLE_CLIENT_SECRET:-}"

case "$PROFILE" in
  demo)  NEXORA_REPO=memory;    NEXORA_DISPATCHER=local ;;
  scale) NEXORA_REPO=firestore; NEXORA_DISPATCHER=cloud ;;
  *) echo "unknown NEXORA_PROFILE=$PROFILE (want demo|scale)" >&2; exit 2 ;;
esac
echo "==> Profile: $PROFILE  (repo=$NEXORA_REPO dispatcher=$NEXORA_DISPATCHER)"

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
  echo "       Wait a few minutes and re-run, or: gcloud services enable $svc --project $PROJECT_ID" >&2
  exit 1
}

echo "==> Enabling APIs (one at a time, with retries)"
for svc in run.googleapis.com aiplatform.googleapis.com \
           artifactregistry.googleapis.com cloudbuild.googleapis.com; do
  enable_api "$svc" required
done
[ -n "$GEMINI_API_KEY" ] && enable_api secretmanager.googleapis.com required || true
if [ "$NEXORA_REPO" = "firestore" ]; then enable_api firestore.googleapis.com required; fi

SCHEDULER_OK="no"
if [ "$PROFILE" = "scale" ]; then
  enable_api cloudtasks.googleapis.com required
  enable_api cloudscheduler.googleapis.com optional && SCHEDULER_OK="yes" || true
fi

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

if [ "$NEXORA_REPO" = "firestore" ]; then
  echo "==> Firestore (native mode) — ignore error if it already exists"
  gcloud firestore databases create --location="$REGION" --project "$PROJECT_ID" || true
fi

if [ "$NEXORA_DISPATCHER" = "cloud" ]; then
  echo "==> Cloud Tasks queue"
  gcloud tasks queues create nexora-workers --location="$REGION" --project "$PROJECT_ID" || true
fi

echo "==> Artifact Registry repo"
gcloud artifacts repositories create "$REPO" --repository-format=docker \
  --location="$REGION" --project "$PROJECT_ID" || true

# ---- IAM helpers (SetPolicy is prone to transient DEADLINE_EXCEEDED) ----
bind_member() {  # $1 = member, $2 = role
  local i
  for i in 1 2 3 4 5; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member "$1" --role "$2" --condition=None --quiet && return 0
    echo "    ($2 -> $1) attempt $i failed; retrying in $((i*10))s..."
    sleep $((i*10))
  done
  echo "ERROR: could not bind $2 to $1." >&2
  exit 1
}

echo "==> Service account + IAM"
gcloud iam service-accounts create nexora-api --project "$PROJECT_ID" \
  --display-name "NEXORA API" || true
ROLES="roles/aiplatform.user roles/run.invoker roles/iam.serviceAccountTokenCreator"
[ -n "$GEMINI_API_KEY" ] && ROLES="$ROLES roles/secretmanager.secretAccessor"
[ "$NEXORA_REPO" = "firestore" ] && ROLES="$ROLES roles/datastore.user"
[ "$NEXORA_DISPATCHER" = "cloud" ] && ROLES="$ROLES roles/cloudtasks.enqueuer"
for ROLE in $ROLES; do bind_member "serviceAccount:${SA}" "$ROLE"; done

if [ "$NEXORA_DISPATCHER" = "cloud" ]; then
  # Cloud Tasks must mint an OIDC token as the API SA to call /internal/* — the
  # SA needs actAs on itself.
  for i in 1 2 3 4 5; do
    gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT_ID" \
      --member "serviceAccount:${SA}" --role roles/iam.serviceAccountUser --quiet && break
    echo "    (actAs self-binding) attempt $i failed; retrying..." ; sleep $((i*10))
  done
fi

_SECRETS=""
_put_secret() {  # name value  -> upsert, append to _SECRETS
  printf '%s' "$2" | gcloud secrets create "$1" --data-file=- --project "$PROJECT_ID" 2>/dev/null || \
    printf '%s' "$2" | gcloud secrets versions add "$1" --data-file=- --project "$PROJECT_ID"
}
if [ -n "$GEMINI_API_KEY" ]; then
  echo "==> Gemini API key -> Secret Manager"
  _put_secret nexora-gemini-api-key "$GEMINI_API_KEY"
  _SECRETS="${_SECRETS:+$_SECRETS,}GEMINI_API_KEY=nexora-gemini-api-key:latest"
fi
if [ -n "$GOOGLE_CLIENT_ID" ] && [ -n "$GOOGLE_CLIENT_SECRET" ]; then
  echo "==> Google OAuth client -> Secret Manager (LIVE mode enabled on the host)"
  enable_api secretmanager.googleapis.com required || true
  _put_secret nexora-google-client-id "$GOOGLE_CLIENT_ID"
  _put_secret nexora-google-client-secret "$GOOGLE_CLIENT_SECRET"
  _SECRETS="${_SECRETS:+$_SECRETS,}GOOGLE_CLIENT_ID=nexora-google-client-id:latest,GOOGLE_CLIENT_SECRET=nexora-google-client-secret:latest"
fi
if [ -n "$_SECRETS" ]; then
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${SA}" --role roles/secretmanager.secretAccessor --condition=None --quiet || true
  SECRET_FLAG=(--set-secrets "$_SECRETS")
else
  SECRET_FLAG=()
fi

echo "==> Vertex AI Agent Engine (managed Sessions + Memory Bank)"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user" --condition=None --quiet || true
PY="${PYTHON:-python}"
if ! "$PY" -c 'import vertexai' 2>/dev/null; then
  echo "    installing google-cloud-aiplatform[agent_engines,adk] for the deploy helper..."
  "$PY" -m pip install -q 'google-cloud-aiplatform[agent_engines,adk]>=1.95' || true
fi
# Non-fatal: without an Agent Engine the ADK workforce uses an in-process runner
# and memory stays local. Still fully functional.
AGENT_ENGINE=$(GCP_PROJECT_ID="$PROJECT_ID" GCP_LOCATION="$REGION" \
  "$PY" infrastructure/deploy_agent_engine.py 2>/dev/null || true)
if [ -n "$AGENT_ENGINE" ]; then
  echo "    agent engine id: $AGENT_ENGINE"
  AE_ENV=",NEXORA_AGENT_ENGINE=${AGENT_ENGINE},NEXORA_MEMORY=memorybank"
else
  echo "    Agent Engine unavailable — deploying with in-process runner + local memory."
  AE_ENV=""
fi

echo "==> Cloud Build permissions"
# New projects run builds as the Compute Engine default SA, which no longer gets
# roles/editor — so it can't read its own source upload or push the image.
CB_SA="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
bind_member "$CB_SA" roles/cloudbuild.builds.builder
bind_member "$CB_SA" roles/artifactregistry.writer

echo "==> Build image (Cloud Build, from repo root)"
gcloud builds submit --tag "$IMAGE" --project "$PROJECT_ID" .

# demo: exactly one warm instance with CPU always allocated. Mission state lives
# in that instance's memory, so it must not scale out (a second instance would
# 404 on missions the first one is running) and must not be CPU-throttled (the
# in-process task graph keeps running after the HTTP response returns).
SCALING=(--min-instances=1 --max-instances=1 --no-cpu-throttling)
[ "$PROFILE" = "scale" ] && SCALING=(--min-instances=0 --max-instances=10)

echo "==> Deploy to Cloud Run"
gcloud run deploy nexora-api \
  --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID" \
  --service-account "$SA" --timeout 600 --cpu 1 --memory 1Gi \
  --allow-unauthenticated "${SCALING[@]}" "${SECRET_FLAG[@]}" \
  --set-env-vars "EXECUTION_MODE=MOCK,NEXORA_REPO=${NEXORA_REPO},NEXORA_DISPATCHER=${NEXORA_DISPATCHER},NEXORA_LLM_BACKEND=vertex,GCP_PROJECT_ID=${PROJECT_ID},GCP_LOCATION=${REGION},NEXORA_MODEL_T2=gemini-3.5-flash,NEXORA_WORKER_SA=${SA},CORS_ORIGIN_REGEX=${CORS_ORIGIN_REGEX:-https://.*[.]vercel[.]app}${AE_ENV}"

URL=$(gcloud run services describe nexora-api --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)')
echo "==> Wiring worker URL + zero-trust OIDC gate for /internal/*"
OAUTH_ENV=""
if [ -n "$GOOGLE_CLIENT_ID" ] && [ -n "$GOOGLE_CLIENT_SECRET" ]; then
  OAUTH_ENV=",NEXORA_OAUTH_REDIRECT=${URL}/api/v1/auth/callback"
  echo "    LIVE OAuth redirect: ${URL}/api/v1/auth/callback"
  echo "    ^ add this exact URI to the OAuth client's Authorized redirect URIs."
fi
gcloud run services update nexora-api --region "$REGION" --project "$PROJECT_ID" \
  --update-env-vars "NEXORA_WORKER_URL=${URL},NEXORA_INTERNAL_AUDIENCE=${URL},NEXORA_INTERNAL_SA=${SA}${OAUTH_ENV}"

if [ "$SCHEDULER_OK" = "yes" ]; then
  echo "==> Cloud Scheduler: fire due mission schedules every minute"
  gcloud scheduler jobs create http nexora-run-due --location="$REGION" --project "$PROJECT_ID" \
    --schedule="* * * * *" --uri="${URL}/internal/run_due" --http-method=POST \
    --oidc-service-account-email="$SA" --oidc-token-audience="${URL}" 2>/dev/null || \
  gcloud scheduler jobs update http nexora-run-due --location="$REGION" --project "$PROJECT_ID" \
    --schedule="* * * * *" --uri="${URL}/internal/run_due" --http-method=POST \
    --oidc-service-account-email="$SA" --oidc-token-audience="${URL}"
elif [ "$PROFILE" = "demo" ]; then
  echo "==> Standing schedules fire from the in-process loop (no Cloud Scheduler needed)"
fi

echo
echo "NEXORA API is live: $URL"
echo "Check: curl -s $URL/api/v1/config"
