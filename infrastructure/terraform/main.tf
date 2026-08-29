terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "us-central1"
}
variable "image" {
  type        = string
  description = "Full container image, e.g. us-central1-docker.pkg.dev/PROJECT/nexora/api:latest"
}
variable "gemini_api_key" {
  type      = string
  sensitive = true
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------- APIs ----------------
resource "google_project_service" "svc" {
  for_each = toset([
    "run.googleapis.com",
    "cloudtasks.googleapis.com",
    "cloudscheduler.googleapis.com",
    "firestore.googleapis.com",
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# ---------------- State: Firestore (native mode) ----------------
resource "google_firestore_database" "default" {
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
  depends_on  = [google_project_service.svc]
}

# ---------------- Durable execution: Cloud Tasks ----------------
resource "google_cloud_tasks_queue" "workers" {
  name     = "nexora-workers"
  location = var.region
  retry_config {
    max_attempts  = 5
    min_backoff   = "5s"
    max_backoff   = "300s"
    max_doublings = 4
  }
  depends_on = [google_project_service.svc]
}

# ---------------- Identity ----------------
resource "google_service_account" "api" {
  account_id   = "nexora-api"
  display_name = "NEXORA API (Cloud Run + Vertex + Tasks + Firestore)"
}

resource "google_project_iam_member" "api_roles" {
  for_each = toset([
    "roles/datastore.user",
    "roles/cloudtasks.enqueuer",
    "roles/aiplatform.user",
    "roles/run.invoker",
    "roles/iam.serviceAccountTokenCreator",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_secret_manager_secret" "gemini" {
  secret_id = "nexora-gemini-api-key"
  replication { auto {} }
  depends_on = [google_project_service.svc]
}
resource "google_secret_manager_secret_version" "gemini" {
  secret      = google_secret_manager_secret.gemini.id
  secret_data = var.gemini_api_key
}
resource "google_secret_manager_secret_iam_member" "gemini_access" {
  secret_id = google_secret_manager_secret.gemini.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

# ---------------- Service ----------------
resource "google_cloud_run_v2_service" "api" {
  name     = "nexora-api"
  location = var.region

  template {
    service_account = google_service_account.api.email
    timeout         = "600s"
    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }
    containers {
      image = var.image
      resources { limits = { cpu = "1", memory = "1Gi" } }

      env {
        name  = "EXECUTION_MODE"
        value = "MOCK"
      }
      env {
        name  = "NEXORA_REPO"
        value = "firestore"
      }
      env {
        name  = "NEXORA_DISPATCHER"
        value = "cloud"
      }
      env {
        name  = "NEXORA_LLM_BACKEND"
        value = "vertex"
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_LOCATION"
        value = var.region
      }
      env {
        name  = "NEXORA_MODEL_T2"
        value = "gemini-3.5-flash"
      }
      env {
        name  = "NEXORA_WORKER_SA"
        value = google_service_account.api.email
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini.secret_id
            version = "latest"
          }
        }
      }
    }
  }
  depends_on = [google_project_service.svc]
}

# ---------------- Scheduled missions: Cloud Scheduler ----------------
resource "google_cloud_scheduler_job" "run_due" {
  name      = "nexora-run-due-schedules"
  region    = var.region
  schedule  = "* * * * *" # every minute
  time_zone = "Etc/UTC"
  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.api.uri}/internal/run_due"
    oidc_token {
      service_account_email = google_service_account.api.email
      audience              = google_cloud_run_v2_service.api.uri
    }
  }
  depends_on = [google_project_service.svc]
}

# NEXORA_WORKER_URL must equal the service URL — set it after first deploy:
#   gcloud run services update nexora-api --region REGION \
#     --update-env-vars NEXORA_WORKER_URL=$(gcloud run services describe nexora-api \
#       --region REGION --format='value(status.url)')
output "service_url" { value = google_cloud_run_v2_service.api.uri }
output "service_account" { value = google_service_account.api.email }
