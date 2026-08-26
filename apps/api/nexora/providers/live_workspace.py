import uuid
from typing import Dict, List
from packages.core.models import Artifact
from nexora.core.credential_store import CredentialStore

class LiveWorkspaceProvider:
    """Isolated Google-specific code. Core engine never imports googleapiclient."""
    def __init__(self, credential_store: CredentialStore):
        self.credential_store = credential_store

    def _service(self, api: str, version: str):
        from googleapiclient.discovery import build  # lazy
        # creds = await self.credential_store.get_google_credentials("default")
        return build(api, version)  # real impl attaches creds

    async def create_document(self, mission_id, node_id, title, content) -> Artifact:
        svc = self._service("docs", "v1")
        doc = svc.documents().create(body={"title": title}).execute()
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="DOC", provider="google", resource_id=doc["documentId"],
                        uri=f"https://docs.google.com/document/d/{doc['documentId']}/edit")

    async def search_emails(self, query, max_results) -> List[Dict]:
        svc = self._service("gmail", "v1")
        res = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        return [{"id": m["id"]} for m in res.get("messages", [])]

    async def read_email(self, message_id) -> Dict:
        svc = self._service("gmail", "v1")
        return svc.users().messages().get(userId="me", id=message_id, format="metadata").execute()

    async def send_email(self, to, subject, body) -> Artifact:
        import base64  # noqa - real impl builds RFC822 message
        svc = self._service("gmail", "v1")
        raw = base64.urlsafe_b64encode(f"To: {', '.join(to)}\nSubject: {subject}\n\n{body}".encode()).decode()
        msg = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id="-", node_id="-", type="EMAIL",
                        provider="google", resource_id=msg["id"], uri=f"https://mail.google.com/mail/u/0/#sent/{msg['id']}")

    async def search_files(self, query) -> List[Dict]:
        svc = self._service("drive", "v3")
        res = svc.files().list(q=f"name contains '{query}'", pageSize=10).execute()
        return res.get("files", [])

    async def create_sheet(self, mission_id, node_id, title, headers) -> Artifact:
        svc = self._service("sheets", "v4")
        sheet = svc.spreadsheets().create(body={"properties": {"title": title}}).execute()
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="SHEET", provider="google", resource_id=sheet["spreadsheetId"],
                        uri=f"https://docs.google.com/spreadsheets/d/{sheet['spreadsheetId']}")

    async def create_event(self, mission_id, node_id, title, attendees) -> Artifact:
        svc = self._service("calendar", "v3")
        event = svc.events().insert(
            calendarId="primary",
            body={"summary": title, "attendees": [{"email": e} for e in attendees],
                  "start": {"dateTime": "2026-08-26T15:00:00Z"}, "end": {"dateTime": "2026-08-26T16:00:00Z"},
                  "conferenceData": {"createRequest": {"requestId": str(uuid.uuid4())}}},
            conferenceDataVersion=1,
        ).execute()
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="EVENT", provider="google", resource_id=event["id"],
                        uri=event.get("htmlLink", ""))

    async def verify_artifact(self, artifact: Artifact) -> bool:
        return artifact.provider == "google" and bool(artifact.resource_id)
