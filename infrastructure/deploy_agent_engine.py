#!/usr/bin/env python3
"""Create (or reuse) NEXORA's Vertex AI Agent Engine instance.

The Agent Engine gives NEXORA's ADK workforce **managed Sessions** and a
**Memory Bank** for organizational memory. NEXORA doesn't need to *package and
upload* an agent — it runs the ADK agents itself and points ADK's
VertexAiSessionService / VertexAiMemoryBankService at this instance.

Usage:
    GCP_PROJECT_ID=your-project GCP_LOCATION=us-central1 \
        python infrastructure/deploy_agent_engine.py

Prints the reasoningEngine id — put it in NEXORA_AGENT_ENGINE (and set
NEXORA_MEMORY=memorybank).

One-time IAM (Memory Bank uses an embedding model under its own service agent):
    PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)')
    gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
      --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
      --role="roles/aiplatform.user" --condition=None
"""
import os
import sys

import vertexai

DISPLAY_NAME = "nexora-agent-engine"


def main() -> int:
    project = os.getenv("GCP_PROJECT_ID")
    location = os.getenv("GCP_LOCATION", "us-central1")
    if not project:
        print("set GCP_PROJECT_ID", file=sys.stderr)
        return 2

    client = vertexai.Client(project=project, location=location)

    for ae in client.agent_engines.list():
        api = getattr(ae, "api_resource", ae)
        if getattr(api, "display_name", "") == DISPLAY_NAME:
            print(api.name.rsplit("/", 1)[-1])
            return 0

    ae = client.agent_engines.create(config={
        "display_name": DISPLAY_NAME,
        "description": "NEXORA workforce runtime — managed Sessions + Memory Bank",
    })
    print(ae.api_resource.name.rsplit("/", 1)[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
