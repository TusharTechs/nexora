# ADR-050: Mission Workspace Folder
Status: Accepted.

Decision: Every mission creates a workspace folder (LIVE: Drive folder
"NEXORA Mission - <goal>"; MOCK: mock://workspace/<id>) stored as
mission.workspace_folder_id / workspace_uri. All artifact-producing provider calls
are parented into that folder via provider.bind(mission_id, folder_id). The UI shows
the workspace link as the single "everything is in one place" surface.

Consequences: Users open one link to find every Doc/Sheet/Slide/Task the mission
produced. LIVE uses drive.file least-privilege (app-created files only).