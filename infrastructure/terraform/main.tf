terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = "nexora-dev" # Replace with your actual GCP project ID later
  region  = "us-central1"
}
