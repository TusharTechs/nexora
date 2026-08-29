import asyncio
import json
import os
from typing import Awaitable, Callable, Protocol

NodeHandler = Callable[[str, str], Awaitable[None]]

class TaskDispatcher(Protocol):
    async def dispatch_node(self, mission_id: str, node_id: str) -> None: ...

class LocalTaskDispatcher:
    """Durable-execution stand-in for local dev. Tracks tasks to avoid GC."""
    def __init__(self, handler: NodeHandler):
        self.handler = handler
        self._tasks = set()

    async def dispatch_node(self, mission_id: str, node_id: str) -> None:
        task = asyncio.create_task(self.handler(mission_id, node_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

class CloudTasksDispatcher:
    """Production: each node becomes a Cloud Tasks HTTP hit on the worker endpoint.

    Every node is an independently retried unit of work — a mission that pauses
    for approval or spans hours simply has no queued task until it is unblocked.
    When NEXORA_WORKER_SA is set, tasks carry an OIDC token so the worker
    endpoint can require authentication.
    """
    def __init__(self, project_id: str, location: str, queue: str, worker_url: str):
        self.project_id = project_id
        self.location = location
        self.queue = queue
        self.worker_url = worker_url.rstrip("/")
        self.service_account = os.getenv("NEXORA_WORKER_SA", "")

    async def dispatch_node(self, mission_id: str, node_id: str) -> None:
        await asyncio.to_thread(self._enqueue, mission_id, node_id)

    def _enqueue(self, mission_id: str, node_id: str) -> None:
        from google.cloud import tasks_v2  # lazy: installed only in the cloud image

        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(self.project_id, self.location, self.queue)
        http_request = {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{self.worker_url}/internal/execute_node",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"mission_id": mission_id, "node_id": node_id}).encode(),
        }
        if self.service_account:
            http_request["oidc_token"] = {
                "service_account_email": self.service_account,
                "audience": self.worker_url,
            }
        client.create_task(request={"parent": parent, "task": {"http_request": http_request}})
