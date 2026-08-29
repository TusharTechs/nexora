"""Live Workspace Provider — Real Google Workspace integration (ADR-063, ADR-064).

Uses the Google API Python Client to interact with real Gmail, Drive, Docs, 
Sheets, Calendar, and Tasks. All blocking API calls are wrapped in asyncio.to_thread
to prevent blocking the FastAPI event loop.

Phase 10: Added real Vertex Imagen image generation with Drive upload.
"""
import asyncio
import base64
import logging
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


_log = logging.getLogger("nexora.live")


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

    async def _vertex_token(self) -> str:
        """A cloud-platform-scoped token for direct Vertex REST calls (Veo, Lyria).

        The Workspace OAuth token used for Docs/Drive does NOT carry the Vertex
        scope, so those calls need Application Default Credentials (the Cloud Run
        service account in prod, `gcloud auth application-default login` locally).
        """
        def _adc() -> str:
            import google.auth
            import google.auth.transport.requests
            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"])
            if not creds.valid:
                creds.refresh(google.auth.transport.requests.Request())
            return creds.token
        return await asyncio.to_thread(_adc)

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
                _log.warning(f"Gmail search error: {e}")
                # Return error as result instead of raising
                return [{"id": "error", "subject": "Search failed",
                         "snippet": str(e), "body": "", "attachments": []}]

        return await asyncio.to_thread(_search)

    @staticmethod
    def _mime_email(to: List[str], subject: str, body_markdown: str) -> str:
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from nexora.providers.formatting import markdown_to_html, parse_markdown_blocks
        plain_lines = [b.get("text", "") for b in parse_markdown_blocks(body_markdown)]
        msg = MIMEMultipart("alternative")
        msg["To"] = ", ".join(to) if to else ""
        msg["Subject"] = subject
        msg.attach(MIMEText(body_markdown, "plain", "utf-8"))
        msg.attach(MIMEText(markdown_to_html(body_markdown, title=subject,
                                             preheader=(plain_lines[0] if plain_lines else subject)),
                            "html", "utf-8"))
        return base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    async def send_email(self, to: List[str], subject: str, body: str) -> Artifact:
        service = await self._build_service('gmail', 'v1')
        raw = self._mime_email(to, subject, body)

        def _send():
            return service.users().messages().send(userId='me', body={'raw': raw}).execute()['id']

        msg_id = await asyncio.to_thread(_send)
        return self._art("EMAIL", msg_id, f"https://mail.google.com/mail/u/0/#sent/{msg_id}",
                         to=to, subject=subject)

    async def draft_email(self, to: List[str], subject: str, body: str) -> Artifact:
        service = await self._build_service('gmail', 'v1')
        raw = self._mime_email(to, subject, body)

        def _draft():
            return service.users().drafts().create(
                userId='me', body={'message': {'raw': raw}}).execute()['id']

        draft_id = await asyncio.to_thread(_draft)
        return self._art("DRAFT", draft_id, "https://mail.google.com/mail/u/0/#drafts",
                         to=to, subject=subject)

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
                _log.warning(f"Drive search error: {e}")
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
            from nexora.providers.formatting import markdown_to_docs_requests
            doc = service.documents().create(body={'title': title}).execute()
            doc_id = doc['documentId']

            if content:
                try:
                    requests = markdown_to_docs_requests(content, title)
                except Exception:
                    requests = [{'insertText': {'location': {'index': 1},
                                                'text': f"{title}\n\n{content}"}}]
                # Docs batchUpdate caps ranges; send in chunks to stay safe.
                for i in range(0, len(requests), 400):
                    service.documents().batchUpdate(
                        documentId=doc_id,
                        body={'requests': requests[i:i + 400]}).execute()

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
    async def create_sheet(self, mission_id: str, node_id: str, title: str,
                           headers: List[str], rows: Optional[List[List]] = None) -> Artifact:
        service = await self._build_service('sheets', 'v4')
        drive_service = await self._build_service('drive', 'v3')

        def _create():
            sheet = service.spreadsheets().create(body={'properties': {'title': title}}).execute()
            sheet_id = sheet['spreadsheetId']

            values = []
            if headers:
                values.append([str(h) for h in headers])
            for r in (rows or []):
                values.append([("" if c is None else str(c)) for c in r])
            if values:
                service.spreadsheets().values().update(
                    spreadsheetId=sheet_id, range="A1",
                    valueInputOption="USER_ENTERED",
                    body={"values": values}
                ).execute()
                try:
                    from nexora.providers.formatting import (sheet_format_requests,
                                                             guess_money_columns)
                    grid_id = sheet["sheets"][0]["properties"]["sheetId"]
                    reqs = sheet_format_requests(
                        grid_id, n_cols=len(values[0]), n_rows=len(values),
                        money_cols=guess_money_columns([str(h) for h in (headers or [])]))
                    service.spreadsheets().batchUpdate(
                        spreadsheetId=sheet_id, body={"requests": reqs}).execute()
                except Exception as e:
                    _log.warning(f"Sheet formatting skipped: {e}")

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

    # ---------------- Image generation (Gemini / Imagen via GenAI SDK) ----------------
    async def generate_image(self, mission_id: str, node_id: str, prompt: str) -> Artifact:
        """Generate a real image and upload it to the mission Drive folder.

        Uses the GenAI SDK with an image-capable model (NEXORA_IMAGE_MODEL,
        default gemini-2.5-flash-image) — works on both the Gemini API and Vertex.
        """
        model = os.getenv("NEXORA_IMAGE_MODEL", "gemini-2.5-flash-image")

        def _generate() -> bytes:
            from nexora.core.llm_client import genai_client
            client = genai_client()
            resp = client.models.generate_content(
                model=model,
                contents=("Generate a single photorealistic, editorial-quality 16:9 image. "
                          + prompt))
            for part in resp.candidates[0].content.parts:
                inline = getattr(part, "inline_data", None)
                if inline and inline.data:
                    return inline.data
            raise RuntimeError("model returned no image part")

        try:
            png_bytes = await asyncio.to_thread(_generate)
        except Exception as e:
            _log.warning(f"Image generation failed: {e}. Falling back to mock image.")
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
            _log.warning(f"Drive upload failed: {e}")
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

    # ---------------- Google Slides ----------------
    async def create_slides(self, mission_id: str, node_id: str, title: str, slides) -> Artifact:
        service = await self._build_service('slides', 'v1')
        drive_service = await self._build_service('drive', 'v3')

        # Normalise: accept list[str] or list[{title, bullets, notes}]
        deck = []
        for s in (slides or []):
            if isinstance(s, dict):
                deck.append({"title": str(s.get("title", "")),
                             "bullets": [str(b) for b in (s.get("bullets") or [])]})
            else:
                deck.append({"title": str(s), "bullets": []})
        if not deck:
            deck = [{"title": title, "bullets": []}]

        def _create():
            from nexora.providers.formatting import slide_deck_requests, slide_theme_requests
            pres = service.presentations().create(body={'title': title}).execute()
            pres_id = pres['presentationId']
            existing = pres.get('slides', [])

            struct, text_reqs = slide_deck_requests(deck, title, subtitle="Prepared by NEXORA")
            if existing:
                struct.append({"deleteObject": {"objectId": existing[0]['objectId']}})
            service.presentations().batchUpdate(
                presentationId=pres_id, body={"requests": struct}).execute()
            if text_reqs:
                service.presentations().batchUpdate(
                    presentationId=pres_id, body={"requests": text_reqs}).execute()
            # Theme pass: recolour titles to the accent
            try:
                fresh = service.presentations().get(presentationId=pres_id).execute()
                theme = slide_theme_requests(fresh)
                if theme:
                    service.presentations().batchUpdate(
                        presentationId=pres_id, body={"requests": theme}).execute()
            except Exception as e:
                _log.warning(f"Slide theme pass skipped: {e}")

            if self._folder_id and self._folder_id != "root":
                f = drive_service.files().get(fileId=pres_id, fields='parents').execute()
                drive_service.files().update(
                    fileId=pres_id, addParents=self._folder_id,
                    removeParents=",".join(f.get('parents', [])), fields='id').execute()
            meta = drive_service.files().get(fileId=pres_id, fields='webViewLink').execute()
            return pres_id, meta.get('webViewLink', f"https://docs.google.com/presentation/d/{pres_id}")

        try:
            pres_id, uri = await asyncio.to_thread(_create)
        except Exception as e:
            _log.warning(f"Slides creation failed: {e}. Falling back to mock deck.")
            from nexora.providers.mock_workspace import MockWorkspaceProvider
            return await MockWorkspaceProvider().create_slides(mission_id, node_id, title, slides)
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="SLIDES", provider="live", resource_id=pres_id, uri=uri)

    # ---------------- Google Tasks ----------------
    async def create_task(self, mission_id, node_id, title, notes):
        try:
            service = await self._build_service('tasks', 'v1')

            def _create():
                lists = service.tasklists().list(maxResults=1).execute().get('items', [])
                tasklist_id = lists[0]['id'] if lists else '@default'
                t = service.tasks().insert(tasklist=tasklist_id,
                                           body={'title': title[:1024], 'notes': (notes or '')[:8000]}).execute()
                return t['id']
            task_id = await asyncio.to_thread(_create)
            return self._art("TASK", task_id, "https://tasks.google.com/", title=title)
        except Exception as e:
            _log.warning(f"Tasks create failed: {e}. Falling back to mock.")
            from nexora.providers.mock_workspace import MockWorkspaceProvider
            return await MockWorkspaceProvider().create_task(mission_id, node_id, title, notes)

    # ---------------- Directory / People ----------------
    async def search_people(self, query: str) -> List[Dict]:
        try:
            service = await self._build_service('people', 'v1')

            def _search():
                res = service.people().searchContacts(
                    query=query[:100],
                    readMask="names,emailAddresses,organizations").execute()
                out = []
                for r in res.get('results', []):
                    p = r.get('person', {})
                    names = p.get('names', [{}])
                    emails = p.get('emailAddresses', [{}])
                    orgs = p.get('organizations', [{}])
                    out.append({
                        "name": names[0].get('displayName', 'Unknown') if names else 'Unknown',
                        "email": emails[0].get('value', '') if emails else '',
                        "role": orgs[0].get('title', '') if orgs else '',
                    })
                return out
            people = await asyncio.to_thread(_search)
            return people or [{"name": "No directory matches", "email": "", "role": ""}]
        except Exception as e:
            _log.warning(f"People search failed: {e}. Falling back to mock.")
            from nexora.providers.mock_workspace import MockWorkspaceProvider
            return await MockWorkspaceProvider().search_people(query)

    # ---------------- Gmail read ----------------
    async def read_email(self, message_id: str) -> Dict:
        try:
            service = await self._build_service('gmail', 'v1')

            def _read():
                msg = service.users().messages().get(userId='me', id=message_id, format='full').execute()
                headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
                body = ""
                payload = msg.get('payload', {})
                for part in payload.get('parts', [payload]):
                    if part.get('mimeType') == 'text/plain' and part.get('body', {}).get('data'):
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                        break
                return {"id": message_id, "subject": headers.get('Subject', ''),
                        "from": headers.get('From', ''), "body": body,
                        "snippet": msg.get('snippet', '')}
            return await asyncio.to_thread(_read)
        except Exception as e:
            return {"id": message_id, "body": f"(read failed: {e})"}

    async def read_sheet(self, sheet_id: str, range_: str) -> List[List]:
        try:
            service = await self._build_service('sheets', 'v4')

            def _read():
                res = service.spreadsheets().values().get(
                    spreadsheetId=sheet_id, range=range_ or "A1:Z100").execute()
                return res.get('values', [])
            return await asyncio.to_thread(_read)
        except Exception as e:
            _log.warning(f"Sheet read failed: {e}")
            return []

    # ---------------- Gemini Vision ----------------
    async def analyze_attachment(self, mission_id, node_id, attachment):
        attachment = attachment or {}
        img_bytes = None
        raw = attachment.get("bytes") or attachment.get("data")
        if raw:
            try:
                img_bytes = base64.b64decode(raw) if isinstance(raw, str) else raw
            except Exception:
                img_bytes = None
        text_hint = attachment.get("text", "")
        try:
            from google.genai import types
            from nexora.core.llm_client import genai_client, llm_available
            model = os.getenv("NEXORA_MODEL_T2", "gemini-3.5-flash")
            if llm_available() and img_bytes:
                client = genai_client()
                prompt = ("Analyze this screenshot/image. Extract any error codes, stack traces, "
                          "UI state, and what the user is seeing. Return JSON: "
                          '{"error_code": "...", "summary": "...", "visual_evidence": "..."}')
                resp = await client.aio.models.generate_content(
                    model=model,
                    contents=[types.Part.from_bytes(data=img_bytes, mime_type=attachment.get("type", "image/png")),
                              prompt])
                txt = resp.text or ""
                import json as _json, re as _re
                m = _re.search(r"\{.*\}", txt, _re.S)
                parsed = _json.loads(m.group(0)) if m else {}
                error_code = parsed.get("error_code") or "UNKNOWN"
                art = Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                               type="ANALYSIS", provider="live", resource_id=f"vision_{node_id}",
                               uri=f"vision://{node_id}")
                return {"error_code": error_code,
                        "timestamp": "", "visual_evidence": parsed.get("visual_evidence", txt[:400]),
                        "summary": parsed.get("summary", ""), "analyzed_by": "Gemini Vision",
                        "artifact": art}
        except Exception as e:
            _log.warning(f"Gemini Vision failed: {e}. Falling back to mock analysis.")
        from nexora.providers.mock_workspace import MockWorkspaceProvider
        return await MockWorkspaceProvider().analyze_attachment(mission_id, node_id, attachment)

    async def send_chat(self, space, text):
        from nexora.providers.mock_workspace import MockWorkspaceProvider
        return await MockWorkspaceProvider().send_chat(space, text)

    async def create_form(self, mission_id, node_id, title, questions):
        from nexora.providers.mock_workspace import MockWorkspaceProvider
        return await MockWorkspaceProvider().create_form(mission_id, node_id, title, questions)

    # ---------------- Vertex Veo (GA managed model — no enablement needed,
    # just aiplatform.googleapis.com + roles/aiplatform.user) ----------------
    async def generate_video(self, mission_id, node_id, prompt):
        token = await self._vertex_token()
        loc = os.getenv("NEXORA_VIDEO_LOCATION", "us-central1")  # Veo: regional
        proj = os.getenv("GCP_PROJECT_ID", "")
        model = os.getenv("NEXORA_VIDEO_MODEL", "veo-3.1-fast-generate-001")
        base = f"https://{loc}-aiplatform.googleapis.com/v1/projects/{proj}/locations/{loc}/publishers/google/models/{model}"

        def _generate() -> bytes:
            import time as _t
            import httpx as _httpx
            with _httpx.Client(timeout=120, verify=not _insecure_tls()) as c:
                r = c.post(f"{base}:predictLongRunning",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"instances": [{"prompt": prompt}],
                                 "parameters": {"sampleCount": 1, "durationSeconds": 6,
                                                "resolution": "720p", "generateAudio": True}})
                r.raise_for_status()
                op = r.json().get("name")
                for _ in range(36):
                    _t.sleep(10)
                    poll = c.post(f"{base}:fetchPredictOperation",
                                  headers={"Authorization": f"Bearer {token}"},
                                  json={"operationName": op})
                    poll.raise_for_status()
                    pj = poll.json()
                    if pj.get("done"):
                        if pj.get("error"):
                            raise RuntimeError(str(pj["error"]))
                        resp = pj.get("response", {})
                        vids = resp.get("videos") or resp.get("generatedSamples") or resp.get("predictions", [])
                        v = vids[0]
                        b64 = (v.get("bytesBase64Encoded")
                               or v.get("video", {}).get("bytesBase64Encoded"))
                        if b64:
                            return base64.b64decode(b64)
                        gcs = v.get("gcsUri") or v.get("video", {}).get("uri")
                        if gcs:
                            raise RuntimeError(f"Veo returned a GCS URI ({gcs}); "
                                               "set no storageUri to get bytes back")
                        raise RuntimeError(f"Veo response had no video bytes: {list(v)}")
                raise TimeoutError("Veo generation timed out")

        try:
            video_bytes = await asyncio.to_thread(_generate)
        except Exception as e:
            _log.warning(f"Vertex Veo failed: {e}. Falling back to mock video.")
            from nexora.providers.mock_workspace import MockWorkspaceProvider
            return await MockWorkspaceProvider().generate_video(mission_id, node_id, prompt)

        drive = await self._build_service('drive', 'v3')

        def _upload():
            safe = "".join(c for c in prompt[:40] if c.isalnum() or c in " -_").strip()
            parents = [self._folder_id] if self._folder_id and self._folder_id != "root" else []
            media = MediaIoBaseUpload(io.BytesIO(video_bytes), mimetype="video/mp4")
            f = drive.files().create(body={"name": f"NEXORA Video - {safe or 'clip'}.mp4", "parents": parents},
                                     media_body=media, fields="id, webViewLink").execute()
            return f["id"], f.get("webViewLink", f"https://drive.google.com/file/d/{f['id']}/view")

        try:
            fid, uri = await asyncio.to_thread(_upload)
        except Exception as e:
            _log.warning(f"Drive video upload failed: {e}")
            return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                            type="VIDEO", provider="live", resource_id="upload_failed",
                            uri="drive://upload_failed", prompt=prompt)
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="VIDEO", provider="live", resource_id=fid, uri=uri, prompt=prompt)

    @staticmethod
    def _pcm_to_wav(pcm: bytes, rate: int = 24000, channels: int = 1, width: int = 2) -> bytes:
        import io as _io, wave
        buf = _io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(width)
            w.setframerate(rate)
            w.writeframes(pcm)
        return buf.getvalue()

    async def generate_audio(self, mission_id: str, node_id: str, prompt: str,
                             kind: str = "speech") -> Artifact:
        """Produce a real audio file for the mission Drive folder.

        kind="speech" (default) — spoken narration via Gemini TTS (NEXORA_TTS_MODEL).
        kind="music"            — original music/jingle via Vertex Lyria (NEXORA_AUDIO_MODEL).
        Falls back to a mock audio artifact if the model call fails.
        """
        proj = os.getenv("GCP_PROJECT_ID", "")

        if kind != "music":
            model = os.getenv("NEXORA_TTS_MODEL", "gemini-2.5-flash-tts")
            voice = os.getenv("NEXORA_TTS_VOICE", "Kore")

            def _tts() -> tuple:
                from google.genai import types
                from nexora.core.llm_client import genai_client
                client = genai_client()
                resp = client.models.generate_content(
                    model=model,
                    contents=("Read this briefing aloud in a clear, warm, professional "
                              f"voice:\n\n{prompt}"),
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=voice)))))
                for p in resp.candidates[0].content.parts:
                    inline = getattr(p, "inline_data", None)
                    if inline and inline.data:
                        pcm, mime = inline.data, (inline.mime_type or "")
                        if "pcm" in mime or "L16" in mime:
                            rate = 24000
                            for tok in mime.split(";"):
                                if "rate=" in tok:
                                    rate = int(tok.split("=")[1])
                            return self._pcm_to_wav(pcm, rate=rate), "audio/wav"
                        return pcm, (mime or "audio/wav")
                raise RuntimeError("TTS returned no audio part")

            try:
                audio_bytes, mime = await asyncio.to_thread(_tts)
            except Exception as e:
                _log.warning(f"Gemini TTS failed: {e}. Falling back to mock audio.")
                from nexora.providers.mock_workspace import MockWorkspaceProvider
                return await MockWorkspaceProvider().generate_audio(mission_id, node_id, prompt)
        else:
            token = await self._vertex_token()
            model = os.getenv("NEXORA_AUDIO_MODEL", "lyria-002")
            # Lyria 2 is served only from the global endpoint.
            url = (f"https://aiplatform.googleapis.com/v1/projects/{proj}/locations/global/"
                   f"publishers/google/models/{model}:predict")

            def _lyria() -> tuple:
                import httpx as _httpx
                r = _httpx.post(url, headers={"Authorization": f"Bearer {token}"},
                                json={"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1}},
                                timeout=120, verify=not _insecure_tls())
                r.raise_for_status()
                pred = r.json()["predictions"][0]
                return base64.b64decode(pred["bytesBase64Encoded"]), pred.get("mimeType", "audio/wav")

            try:
                audio_bytes, mime = await asyncio.to_thread(_lyria)
            except Exception as e:
                _log.warning(f"Vertex Lyria failed: {e}. Falling back to mock audio.")
                from nexora.providers.mock_workspace import MockWorkspaceProvider
                return await MockWorkspaceProvider().generate_audio(mission_id, node_id, prompt)

        # Upload to the mission folder
        drive = await self._build_service('drive', 'v3')
        ext = "mp3" if "mp3" in mime else "wav"

        def _upload():
            label = "Music" if kind == "music" else "Briefing"
            filename = f"NEXORA {label} - {mission_id[:8]}.{ext}"
            parents = [self._folder_id] if self._folder_id and self._folder_id != "root" else []
            meta = {"name": filename, "parents": parents}
            media = MediaIoBaseUpload(io.BytesIO(audio_bytes), mimetype=mime)
            f = drive.files().create(body=meta, media_body=media, fields="id, webViewLink").execute()
            return f["id"], f.get("webViewLink", f"https://drive.google.com/file/d/{f['id']}/view")

        try:
            fid, uri = await asyncio.to_thread(_upload)
        except Exception as e:
            _log.warning(f"Drive audio upload failed: {e}")
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