# ADR-063: Live Workspace Integration
Status: Accepted.

Context: To demonstrate real-world value to hackathon judges, NEXORA must interact
with actual Google Workspace data (Gmail, Drive, Docs, Sheets, Calendar), not just
mock data. 

Decision: `LiveWorkspaceProvider` uses `google-api-python-client` wrapped in 
`asyncio.to_thread` to prevent blocking the FastAPI event loop. OAuth tokens are 
stored in `LocalCredentialStore` and automatically refreshed when expired. All 
artifacts created in LIVE mode are filed into a dedicated Google Drive folder 
created per mission.

Consequences: Judges can connect their own Google accounts and watch NEXORA 
create real documents, schedule real meetings, and search real emails in real-time.