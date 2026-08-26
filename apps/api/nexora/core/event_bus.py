import asyncio
import logging
from collections import defaultdict
from typing import Dict, List, Protocol
from packages.core.models import utcnow

logger = logging.getLogger("nexora.events")

class EventBus(Protocol):
    async def publish(self, event_type: str, payload: Dict) -> None: ...

class LocalEventBus:
    def __init__(self):
        self._events: Dict[str, List[Dict]] = defaultdict(list)
        self._subscribers: List[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    async def publish(self, event_type: str, payload: Dict) -> None:
        record = {"event_type": event_type, "payload": payload, "timestamp": utcnow().isoformat()}
        self._events[payload.get("mission_id", "-")].append(record)
        for q in list(self._subscribers):
            q.put_nowait(record)
        logger.info("[EVENT] %s %s", event_type, payload)

    def history(self, mission_id: str) -> List[Dict]:
        return self._events.get(mission_id, [])

class PubSubEventBus:
    def __init__(self, project_id: str, topic: str):
        self.project_id = project_id
        self.topic = topic

    async def publish(self, event_type: str, payload: Dict) -> None:
        import json
        from google.cloud import pubsub_v1  # lazy: cloud image only
        publisher = pubsub_v1.PublisherClient()
        publisher.publish(publisher.topic_path(self.project_id, self.topic),
                          json.dumps({"event_type": event_type, "payload": payload}).encode())
