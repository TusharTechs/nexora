import logging
from collections import defaultdict
from typing import Dict, List, Protocol
from packages.core.models import utcnow

logger = logging.getLogger("nexora.events")

class EventBus(Protocol):
    async def publish(self, event_type: str, payload: Dict) -> None: ...

class LocalEventBus:
    """In-memory Pub/Sub stand-in. Zero GCP cost."""
    def __init__(self):
        self._events: Dict[str, List[Dict]] = defaultdict(list)

    async def publish(self, event_type: str, payload: Dict) -> None:
        record = {"event_type": event_type, "payload": payload, "timestamp": utcnow().isoformat()}
        self._events[payload.get("mission_id", "-")].append(record)
        logger.info("[EVENT] %s %s", event_type, payload)

    def history(self, mission_id: str) -> List[Dict]:
        return self._events.get(mission_id, [])

class PubSubEventBus:
    """Production scaffold. Lazy-imports GCP libs only when used."""
    def __init__(self, project_id: str, topic: str):
        self.project_id = project_id
        self.topic = topic

    async def publish(self, event_type: str, payload: Dict) -> None:
        import json  # noqa
        from google.cloud import pubsub_v1  # lazy: installed only in cloud image
        publisher = pubsub_v1.PublisherClient()
        path = publisher.topic_path(self.project_id, self.topic)
        publisher.publish(path, json.dumps({"event_type": event_type, "payload": payload}).encode())
