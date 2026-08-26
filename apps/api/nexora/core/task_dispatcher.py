import asyncio
import json
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
    """Production: each node becomes a Cloud Tasks HTTP hit on the worker endpoint."""
    def __init__(self, project_id: str, location: str, queue: str, worker_url: str):
        self.project_id = project_id
        self.location = location
        self.queue = queue
        self.worker_url = worker_url

    async def dispatch_node(self, mission_id: str, node_id: str) -> None:
        from google.cloud import tasks_v2  # lazy: installed only in cloud image
        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(self.project_id, self.location, self.queue)
        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{self.worker_url}/internal/execute_node",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"mission_id": mission_id, "node_id": node_id}).encode(),
            }
        }
        client.create_task(request={"parent": parent, "task": task})
