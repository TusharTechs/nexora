"""Live Google Workspace provider (Phase 9.3). All Google code stays here (Rule 1).
Least privilege: drive.file, documents, spreadsheets, presentations, calendar,
tasks, gmail.compose. Reads of existing user data can add readonly scopes later."""
import base64
import os
import uuid
from typing import Dict, List
from packages.core.models import Artifact
from nexora.core.credential_store import CredentialStore


class LiveProviderConfigError(Exception):
    pass


class LiveWorkspaceProvider:
    def __init__(self, credential_store: CredentialStore):
        self.credential_store = credential_store
        self._creds = None
        self._workspaces: Dict[str, str] = {}

    async def _credentials(self):
        if self._creds is not None:
            return self._creds
        data = await self.credential_store.get_google_credentials("default")
        if not data:
            raise LiveProviderConfigError("Google not connected. Open /api/v1/auth/google first.")
        from google.oauth2.credentials import Credentials
        
        # Read from stored data first, fall back to env if somehow missing
        cid = data.get("client_id") or os.getenv("GOOGLE_CLIENT_ID", "")
        csec = data.get("client_secret") or os.getenv("GOOGLE_CLIENT_SECRET", "")
        
        self._creds = Credentials(
            token=data.get("access_token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=cid,
            client_secret=csec,
        )
        return self._creds
    
    def _service(self, api: str, version: str):
        from googleapiclient.discovery import build
        import google_auth_httplib2
        import httplib2

        insecure = os.getenv("NEXORA_INSECURE_TLS", "") == "1"
        http = httplib2.Http(
            disable_ssl_certificate_validation=insecure,
            ca_certs=os.getenv("NEXORA_CA_BUNDLE") or None,
        )
        # Authorize the transport ourselves; build() then receives ONLY http=.
        authorized = google_auth_httplib2.AuthorizedHttp(self._creds, http=http)
        return build(api, version, http=authorized, cache_discovery=False)

    # ---- Mission Workspace (ADR-050) ----
    def bind(self, mission_id, folder_id):
        if folder_id:
            self._workspaces[mission_id] = folder_id

    async def ensure_workspace(self, goal) -> dict:
        await self._credentials()
        f = self._service("drive", "v3").files().create(
            body={"name": f"NEXORA Mission - {goal[:40]}",
                  "mimeType": "application/vnd.google-apps.folder"}).execute()
        return {"folder_id": f["id"], "uri": f"https://drive.google.com/drive/folders/{f['id']}"}

    def _place(self, file_id: str, mission_id: str):
        fid = self._workspaces.get(mission_id)
        if not fid:
            return
        d = self._service("drive", "v3")
        cur = d.files().get(fileId=file_id, fields="parents").execute()
        d.files().update(fileId=file_id, addParents=fid,
                         removeParents=",".join(cur.get("parents", [])),
                         fields="id").execute()

    # ---- Docs ----
    async def create_document(self, mission_id, node_id, title, content) -> Artifact:
        await self._credentials()
        doc = self._service("docs", "v1").documents().create(body={"title": title}).execute()
        if content:
            self._service("docs", "v1").documents().batchUpdate(
                documentId=doc["documentId"],
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]}).execute()
        self._place(doc["documentId"], mission_id)
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="DOC", provider="google", resource_id=doc["documentId"],
                        uri=f"https://docs.google.com/document/d/{doc['documentId']}/edit")

    # ---- Sheets ----
    async def create_sheet(self, mission_id, node_id, title, headers) -> Artifact:
        await self._credentials()
        sh = self._service("sheets", "v4").spreadsheets().create(
            body={"properties": {"title": title},
                  "sheets": [{"properties": {"title": "Tracker"},
                              "data": [{"rowData": [
                                  {"values": [{"userEnteredValue": {"stringValue": h}} for h in headers]}
                              ]}]}]}).execute()
        self._place(sh["spreadsheetId"], mission_id)
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="SHEET", provider="google", resource_id=sh["spreadsheetId"],
                        uri=f"https://docs.google.com/spreadsheets/d/{sh['spreadsheetId']}")

    # ---- Slides ----
    async def create_slides(self, mission_id, node_id, title, slides) -> Artifact:
        await self._credentials()
        pr = self._service("slides", "v1").presentations().create(body={"title": title}).execute()
        self._place(pr["presentationId"], mission_id)
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="SLIDES", provider="google", resource_id=pr["presentationId"],
                        uri=f"https://docs.google.com/presentation/d/{pr['presentationId']}")

    # ---- Calendar (+Meet) ----
    async def create_event(self, mission_id, node_id, title, attendees) -> Artifact:
        await self._credentials()
        from datetime import datetime, timedelta, timezone
        start = datetime.now(timezone.utc) + timedelta(days=1, hours=1)
        ev = self._service("calendar", "v3").events().insert(
            calendarId="primary",
            body={"summary": title, "attendees": [{"email": e} for e in attendees],
                  "start": {"dateTime": start.isoformat()},
                  "end": {"dateTime": (start + timedelta(hours=1)).isoformat()},
                  "conferenceData": {"createRequest": {"requestId": str(uuid.uuid4())}}},
            conferenceDataVersion=1).execute()
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="EVENT", provider="google", resource_id=ev["id"],
                        uri=ev.get("htmlLink", ""))

    # ---- Tasks ----
    async def create_task(self, mission_id, node_id, title, notes) -> Artifact:
        await self._credentials()
        t = self._service("tasks", "v1").tasks().insert(
            tasklist="@default", body={"title": title, "notes": notes}).execute()
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="TASK", provider="google", resource_id=t["id"],
                        uri="https://mail.google.com/tasks")

    # ---- Gmail (compose scope: draft + send) ----
    def _raw(self, to, subject, body):
        return base64.urlsafe_b64encode(f"To: {', '.join(to)}\nSubject: {subject}\n\n{body}".encode()).decode()

    async def draft_email(self, to, subject, body) -> Artifact:
        await self._credentials()
        d = self._service("gmail", "v1").users().messages().drafts().create(
            userId="me", body={"message": {"raw": self._raw(to, subject, body)}}).execute()
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id="-", node_id="-", type="DRAFT",
                        provider="google", resource_id=d["id"], uri="https://mail.google.com")

    async def send_email(self, to, subject, body) -> Artifact:
        await self._credentials()
        m = self._service("gmail", "v1").users().messages().send(
            userId="me", body={"raw": self._raw(to, subject, body)}).execute()
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id="-", node_id="-", type="EMAIL",
                        provider="google", resource_id=m["id"], uri="https://mail.google.com")

    # ---- Reads / others: explicit, honest unavailability in LIVE for now ----
    async def search_emails(self, query, max_results) -> List[Dict]:
        raise LiveProviderConfigError("gmail.readonly scope not granted yet; add it in Google consent screen.")

    async def read_email(self, message_id) -> Dict:
        raise LiveProviderConfigError("gmail.readonly scope not granted yet.")

    async def search_files(self, query) -> List[Dict]:
        await self._credentials()
        r = self._service("drive", "v3").files().list(q=f"name contains '{query}'", pageSize=10).execute()
        return r.get("files", [])

    async def read_sheet(self, sheet_id, range_) -> List[List]:
        await self._credentials()
        r = self._service("sheets", "v4").values().get(spreadsheetId=sheet_id, range=range_ or "A1:Z100").execute()
        return r.get("values", [])

    async def send_chat(self, space, text) -> Artifact:
        raise LiveProviderConfigError("Chat app not configured in LIVE yet (Phase 9.6).")

    async def search_people(self, query) -> List[Dict]:
        raise LiveProviderConfigError("People directory not configured in LIVE yet.")

    async def create_form(self, mission_id, node_id, title, questions) -> Artifact:
        raise LiveProviderConfigError("Forms not configured in LIVE yet.")

    async def analyze_attachment(self, mission_id, node_id, attachment) -> Dict:
        raise LiveProviderConfigError("Gemini vision LIVE seam lands with your GEMINI_API_KEY (Phase 9.6).")

    async def generate_video(self, mission_id, node_id, prompt) -> Artifact:
        raise LiveProviderConfigError("Veo requires Vertex billing; MOCK only for now.")

    async def generate_audio(self, mission_id, node_id, prompt) -> Artifact:
        raise LiveProviderConfigError("Lyria requires Vertex billing; MOCK only for now.")

    async def verify_artifact(self, artifact: Artifact) -> bool:
        return artifact.provider == "google" and bool(artifact.resource_id)