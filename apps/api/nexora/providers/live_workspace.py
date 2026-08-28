"""Live Workspace Provider — Real Google Workspace integration (ADR-063, ADR-064).

Uses the Google API Python Client to interact with real Gmail, Drive, Docs, 
Sheets, Calendar, and Tasks. All blocking API calls are wrapped in asyncio.to_thread
to prevent blocking the FastAPI event loop.

Phase 10: Added real Vertex Imagen image generation with Drive upload.
"""
import asyncio
import base64
import io
import os
import uuid
from typing import Dict, List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from packages.core.models import Artifact
from nexora.core.credential_store import LocalCredentialStore


class LiveProviderConfigError(Exception):
    """Raised when the LiveWorkspaceProvider is missing required configuration."""
    pass


def _insecure_tls() -> bool:
    """Check if insecure TLS mode is enabled (for corporate proxies)."""
    return os.getenv("NEXORA_INSECURE_TLS", "") == "1"


class LiveWorkspaceProvider:
    """Real Google Workspace provider. Requires OAuth connection."""

    def __init__(self, credential_store: LocalCredentialStore, user_id: str = "default"):
        self.credential_store = credential_store
        self.user_id = user_id
        self._folder_id: Optional[str] = None

    async def _get_credentials(self) -> Credentials:
        """Fetch and refresh Google OAuth credentials."""
        creds_data = await self.credential_store.get_google_credentials(self.user_id)
        if not creds_data:
            raise LiveProviderConfigError("Google account not connected. Visit /api/v1/auth/google first.")

        # Normalize OAuth raw format -> google-auth format
        info = dict(creds_data)
        if "token" not in info and "access_token" in info:
            info["token"] = info["access_token"]
        if "scopes" not in info and "scope" in info:
            info["scopes"] = info["scope"].split(" ") if isinstance(info["scope"], str) else info["scope"]

        creds = Credentials.from_authorized_user_info(info)

        # Refresh token if expired or invalid
        if not creds.valid and creds.refresh_token:
            await asyncio.to_thread(creds.refresh, Request())
            # Save the refreshed token back to the store
            new_data = {
                "token": creds.token,
                "access_token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": list(creds.scopes or []),
            }
            await self.credential_store.store_google_credentials(self.user_id, new_data)

        return creds

    async def _build_service(self, service_name: str, version: str):
        """Build a Google API service client."""
        creds = await self._get_credentials()
        # build() is synchronous and slow, run in thread
        return await asyncio.to_thread(build, service_name, version, credentials=creds)

    def _art(self, atype: str, resource_id: str, uri: str, **extra) -> Artifact:
        return Artifact(
            artifact_id=str(uuid.uuid4()),
            mission_id="-", node_id="-", type=atype,
            provider="live", resource_id=resource_id, uri=uri, **extra
        )

    # ---------------- Workspace Management ----------------
    def bind(self, mission_id: str, folder_id: str):
        self._folder_id = folder_id

    async def ensure_workspace(self, goal: str) -> dict:
        """Create a dedicated Google Drive folder for this mission."""
        service = await self._build_service('drive', 'v3')

        def _create_folder():
            file_metadata = {
                'name': f"NEXORA Mission: {goal[:50]}",
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = service.files().create(body=file_metadata, fields='id, webViewLink').execute()
            return {"folder_id": folder['id'], "uri": folder.get('webViewLink', f"https://drive.google.com/drive/folders/{folder['id']}")}

        try:
            result = await asyncio.to_thread(_create_folder)
            self._folder_id = result["folder_id"]
            return result
        except HttpError:
            # Fallback if folder creation fails
            return {"folder_id": "root", "uri": "https://drive.google.com"}

    # ---------------- Gmail ----------------
    async def search_emails(self, query: str, max_results: int = 5) -> List[Dict]:
        """Search emails with smart query extraction."""
        service = await self._build_service('gmail', 'v1')

        # Extract key terms from natural language query
        import re
        stop_words = {'search', 'my', 'emails', 'for', 'anything', 'about', 'the', 'and', 'or', 'in', 'to', 'create', 'a', 'an', 'summary', 'doc', 'document'}
        words = re.findall(r'\b\w+\b', query.lower())
        keywords = [w for w in words if w not in stop_words and len(w) > 3]

        if keywords:
            search_query = ' OR '.join(keywords[:3])
        else:
            search_query = query[:100]

        def _search():
            try:
                res = service.users().messages().list(userId='me', q=search_query, maxResults=max_results).execute()
                messages = res.get('messages', [])

                # If no messages found, return a helpful placeholder
                if not messages:
                    return [{"id": "no_results", "subject": "No emails found",
                             "snippet": f"No emails matching '{search_query}'",
                             "body": "", "attachments": []}]

                emails = []
                for m in messages:
                    msg = service.users().messages().get(userId='me', id=m['id'], format='full').execute()
                    headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
                    body = ""
                    if 'parts' in msg.get('payload', {}):
                        for part in msg['payload']['parts']:
                            if part['mimeType'] == 'text/plain' and 'body' in part and 'data' in part['body']:
                                body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                                break
                    emails.append({
                        "id": m['id'],
                        "subject": headers.get('Subject', 'No Subject'),
                        "snippet": msg.get('snippet', ''),
                        "body": body[:500],
                        "attachments": []
                    })
                return emails
            except Exception as e:
                print(f"Gmail search error: {e}")
                # Return error as result instead of raising
                return [{"id": "error", "subject": "Search failed",
                         "snippet": str(e), "body": "", "attachments": []}]

        return await asyncio.to_thread(_search)

    async def send_email(self, to: List[str], subject: str, body: str) -> Artifact:
        service = await self._build_service('gmail', 'v1')

        def _send():
            message = f"To: {','.join(to)}\nSubject: {subject}\n\n{body}"
            raw = base64.urlsafe_b64encode(message.encode('utf-8')).decode('utf-8')
            res = service.users().messages().send(userId='me', body={'raw': raw}).execute()
            return res['id']

        msg_id = await asyncio.to_thread(_send)
        return self._art("EMAIL", msg_id, f"https://mail.google.com/mail/u/0/#inbox/{msg_id}", to=to, subject=subject)

    async def draft_email(self, to: List[str], subject: str, body: str) -> Artifact:
        service = await self._build_service('gmail', 'v1')

        def _draft():
            message = f"To: {','.join(to)}\nSubject: {subject}\n\n{body}"
            raw = base64.urlsafe_b64encode(message.encode('utf-8')).decode('utf-8')
            res = service.users().drafts().create(userId='me', body={'message': {'raw': raw}}).execute()
            return res['id']

        draft_id = await asyncio.to_thread(_draft)
        return self._art("DRAFT", draft_id, "https://mail.google.com/mail/u/0/#drafts", to=to, subject=subject)

    # ---------------- Google Drive ----------------
    async def search_files(self, query: str) -> List[Dict]:
        """Search Drive files with smart query extraction."""
        service = await self._build_service('drive', 'v3')

        # Extract key terms from natural language query
        import re
        stop_words = {'search', 'my', 'files', 'for', 'anything', 'about', 'the', 'and', 'or', 'in', 'to', 'find', 'a', 'an'}
        words = re.findall(r'\b\w+\b', query.lower())
        keywords = [w for w in words if w not in stop_words and len(w) > 3]

        # Use first keyword for name search
        search_term = keywords[0] if keywords else query[:50]

        def _search():
            try:
                q = f"name contains '{search_term}' or fullText contains '{search_term}'"
                res = service.files().list(q=q, pageSize=10, fields="files(id, name, mimeType)").execute()
                return [{"id": f['id'], "name": f['name'], "type": f['mimeType']} for f in res.get('files', [])]
            except Exception as e:
                print(f"Drive search error: {e}")
                return []

        return await asyncio.to_thread(_search)

    async def read_file(self, file_id: str) -> Dict:
        service = await self._build_service('drive', 'v3')

        def _read():
            # Try to export as text (works for Docs)
            try:
                content = service.files().export(fileId=file_id, mimeType='text/plain').execute()
                return {"id": file_id, "content": content.decode('utf-8')}
            except HttpError:
                # Fallback for non-exportable files
                return {"id": file_id, "content": "(Binary file)"}

        return await asyncio.to_thread(_read)

    # ---------------- Google Docs ----------------
    async def create_document(self, mission_id: str, node_id: str, title: str, content: str) -> Artifact:
        service = await self._build_service('docs', 'v1')
        drive_service = await self._build_service('drive', 'v3')

        def _create():
            doc = service.documents().create(body={'title': title}).execute()
            doc_id = doc['documentId']

            # Insert content
            if content:
                requests = [{'insertText': {'location': {'index': 1}, 'text': content}}]
                service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()

            # Move to mission folder if we have one
            if self._folder_id and self._folder_id != "root":
                file = drive_service.files().get(fileId=doc_id, fields='parents').execute()
                previous_parents = ",".join(file.get('parents', []))
                drive_service.files().update(
                    fileId=doc_id, addParents=self._folder_id,
                    removeParents=previous_parents, fields='id, webViewLink'
                ).execute()

            doc_meta = drive_service.files().get(fileId=doc_id, fields='webViewLink').execute()
            return doc_id, doc_meta.get('webViewLink', f"https://docs.google.com/document/d/{doc_id}")

        doc_id, uri = await asyncio.to_thread(_create)
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="DOC", provider="live", resource_id=doc_id, uri=uri)

    # ---------------- Google Sheets ----------------
    async def create_sheet(self, mission_id: str, node_id: str, title: str, headers: List[str]) -> Artifact:
        service = await self._build_service('sheets', 'v4')
        drive_service = await self._build_service('drive', 'v3')

        def _create():
            sheet = service.spreadsheets().create(body={'properties': {'title': title}}).execute()
            sheet_id = sheet['spreadsheetId']

            if headers:
                service.spreadsheets().values().update(
                    spreadsheetId=sheet_id, range="A1",
                    valueInputOption="RAW",
                    body={"values": [headers]}
                ).execute()

            if self._folder_id and self._folder_id != "root":
                file = drive_service.files().get(fileId=sheet_id, fields='parents').execute()
                previous_parents = ",".join(file.get('parents', []))
                drive_service.files().update(
                    fileId=sheet_id, addParents=self._folder_id,
                    removeParents=previous_parents, fields='id, webViewLink'
                ).execute()

            sheet_meta = drive_service.files().get(fileId=sheet_id, fields='webViewLink').execute()
            return sheet_id, sheet_meta.get('webViewLink', f"https://docs.google.com/spreadsheets/d/{sheet_id}")

        sheet_id, uri = await asyncio.to_thread(_create)
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="SHEET", provider="live", resource_id=sheet_id, uri=uri)

    # ---------------- Google Calendar ----------------
    async def create_event(self, mission_id: str, node_id: str, title: str, attendees: List[str]) -> Artifact:
        service = await self._build_service('calendar', 'v3')
        from datetime import datetime, timedelta

        def _create():
            # Default to tomorrow at 10 AM for 1 hour
            start_time = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
            end_time = start_time + timedelta(hours=1)

            event = {
                'summary': title,
                'start': {'dateTime': start_time.isoformat(), 'timeZone': 'UTC'},
                'end': {'dateTime': end_time.isoformat(), 'timeZone': 'UTC'},
                'attendees': [{'email': a} for a in attendees],
                'conferenceData': {'createRequest': {'requestId': str(uuid.uuid4()), 'conferenceSolutionKey': {'type': 'hangoutsMeet'}}}
            }
            res = service.events().insert(calendarId='primary', body=event, conferenceDataVersion=1).execute()
            return res['id'], res.get('htmlLink', '')

        event_id, uri = await asyncio.to_thread(_create)
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="EVENT", provider="live", resource_id=event_id, uri=uri)

    # ---------------- Phase 10: Vertex Imagen Image Generation ----------------
    async def generate_image(self, mission_id: str, node_id: str, prompt: str) -> Artifact:
        """Generate a real image via Vertex Imagen and upload it to the mission Drive folder.

        Uses ~$0.04 per image (vs $0.30-0.50/sec for Veo videos).
        Model is configurable via NEXORA_IMAGE_MODEL env var.
        """
        creds = await self._get_credentials()
        loc = os.getenv("GCP_LOCATION", "us-central1")
        proj = os.getenv("GCP_PROJECT_ID", "")
        model = os.getenv("NEXORA_IMAGE_MODEL", "imagen-3.0-generate-002")

        # Imagen 3 uses a slightly different endpoint than Gemini
        url = (f"https://{loc}-aiplatform.googleapis.com/v1/projects/{proj}/locations/{loc}/"
               f"publishers/google/models/{model}:predict")

        def _generate() -> bytes:
            import httpx as _httpx
            r = _httpx.post(
                url,
                headers={"Authorization": f"Bearer {creds.token}"},
                json={
                    "instances": [{"prompt": prompt}],
                    "parameters": {
                        "sampleCount": 1,
                        "aspectRatio": "16:9",
                    }
                },
                timeout=90,
                verify=not _insecure_tls()
            )
            r.raise_for_status()
            return base64.b64decode(r.json()["predictions"][0]["bytesBase64Encoded"])

        try:
            png_bytes = await asyncio.to_thread(_generate)
        except Exception as e:
            # If Imagen fails (e.g. model 404, quota), fall back to mock image
            print(f"Vertex Imagen failed: {e}. Falling back to mock image.")
            from nexora.providers.mock_workspace import MockWorkspaceProvider
            return await MockWorkspaceProvider().generate_image(mission_id, node_id, prompt)

        # Upload the PNG into the mission workspace folder
        drive = await self._build_service('drive', 'v3')

        def _upload():
            # Sanitize prompt for filename (first 40 chars, no slashes)
            safe_name = "".join(c for c in prompt[:40] if c.isalnum() or c in " -_").strip()
            filename = f"NEXORA Image - {safe_name or 'generated'}.png"

            parents = [self._folder_id] if self._folder_id and self._folder_id != "root" else []
            meta = {"name": filename, "parents": parents}
            media = MediaIoBaseUpload(io.BytesIO(png_bytes), mimetype="image/png")
            f = drive.files().create(body=meta, media_body=media, fields="id, webViewLink").execute()
            return f["id"], f.get("webViewLink", f"https://drive.google.com/file/d/{f['id']}/view")

        try:
            fid, uri = await asyncio.to_thread(_upload)
        except Exception as e:
            # Upload failure but generation succeeded — still return artifact with note
            print(f"Drive upload failed: {e}")
            return Artifact(
                artifact_id=str(uuid.uuid4()),
                mission_id=mission_id, node_id=node_id,
                type="IMAGE", provider="live",
                resource_id="upload_failed",
                uri="drive://upload_failed",
                prompt=prompt,
            )

        return Artifact(
            artifact_id=str(uuid.uuid4()),
            mission_id=mission_id, node_id=node_id,
            type="IMAGE", provider="live",
            resource_id=fid, uri=uri,
            prompt=prompt,
        )

    # ---------------- Fallbacks for non-Google / unsupported features ----------------
    async def web_research(self, objective: str, max_results: int = 5) -> Dict:
        # Delegate to the shared WebResearchService
        from nexora.core.web_research import WebResearchService
        svc = WebResearchService()
        result = await svc.research(objective, max_results)
        return result.model_dump(mode="json")

    async def verify_artifact(self, artifact: Artifact) -> bool:
        # For LIVE mode, if we have a URI, it exists
        return bool(artifact.uri)

    # Stubs for capabilities not fully implemented in Live mode yet
    async def analyze_attachment(self, mission_id, node_id, attachment):
        # Fallback to mock vision for now (or could integrate Gemini Vision API here)
        from nexora.providers.mock_workspace import MockWorkspaceProvider
        return await MockWorkspaceProvider().analyze_attachment(mission_id, node_id, attachment)

    async def create_task(self, mission_id, node_id, title, notes):
        # Fallback to mock
        from nexora.providers.mock_workspace import MockWorkspaceProvider
        return await MockWorkspaceProvider().create_task(mission_id, node_id, title, notes)

    async def send_chat(self, space, text):
        from nexora.providers.mock_workspace import MockWorkspaceProvider
        return await MockWorkspaceProvider().send_chat(space, text)

    async def generate_video(self, mission_id, node_id, prompt):
        from nexora.providers.mock_workspace import MockWorkspaceProvider
        return await MockWorkspaceProvider().generate_video(mission_id, node_id, prompt)

    async def generate_audio(self, mission_id: str, node_id: str, prompt: str) -> Artifact:
        """Generate a real audio clip via Vertex Lyria and upload it to the mission Drive folder.

        Uses ~$0.02-0.05 per clip. Model is configurable via NEXORA_AUDIO_MODEL env var.
        Falls back to mock audio if Vertex is unavailable or the call fails.
        """
        creds = await self._get_credentials()
        loc = os.getenv("GCP_LOCATION", "us-central1")
        proj = os.getenv("GCP_PROJECT_ID", "")
        model = os.getenv("NEXORA_AUDIO_MODEL", "lyria-02")

        # Lyria 2 uses the predict endpoint
        url = (f"https://{loc}-aiplatform.googleapis.com/v1/projects/{proj}/locations/{loc}/"
               f"publishers/google/models/{model}:predict")

        def _generate() -> tuple:
            import httpx as _httpx
            r = _httpx.post(
                url,
                headers={"Authorization": f"Bearer {creds.token}"},
                json={
                    "instances": [{"text": prompt}],
                    "parameters": {"sampleCount": 1}
                },
                timeout=120,
                verify=not _insecure_tls()
            )
            r.raise_for_status()
            data = r.json()
            pred = data["predictions"][0]
            audio_bytes = base64.b64decode(pred["bytesBase64Encoded"])
            mime = pred.get("mimeType", "audio/wav")
            return audio_bytes, mime

        try:
            audio_bytes, mime = await asyncio.to_thread(_generate)
        except Exception as e:
            print(f"Vertex Lyria failed: {e}. Falling back to mock audio.")
            from nexora.providers.mock_workspace import MockWorkspaceProvider
            return await MockWorkspaceProvider().generate_audio(mission_id, node_id, prompt)

        # Upload to the mission folder
        drive = await self._build_service('drive', 'v3')
        ext = "mp3" if "mp3" in mime else "wav"

        def _upload():
            safe_name = "".join(c for c in prompt[:40] if c.isalnum() or c in " -_").strip()
            filename = f"NEXORA Audio - {safe_name or 'briefing'}.{ext}"
            parents = [self._folder_id] if self._folder_id and self._folder_id != "root" else []
            meta = {"name": filename, "parents": parents}
            media = MediaIoBaseUpload(io.BytesIO(audio_bytes), mimetype=mime)
            f = drive.files().create(body=meta, media_body=media, fields="id, webViewLink").execute()
            return f["id"], f.get("webViewLink", f"https://drive.google.com/file/d/{f['id']}/view")

        try:
            fid, uri = await asyncio.to_thread(_upload)
        except Exception as e:
            print(f"Drive audio upload failed: {e}")
            return Artifact(
                artifact_id=str(uuid.uuid4()),
                mission_id=mission_id, node_id=node_id,
                type="AUDIO", provider="live",
                resource_id="upload_failed", uri="drive://upload_failed",
                prompt=prompt,
            )

        return Artifact(
            artifact_id=str(uuid.uuid4()),
            mission_id=mission_id, node_id=node_id,
            type="AUDIO", provider="live",
            resource_id=fid, uri=uri, prompt=prompt,
        )