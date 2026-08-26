# ADR-032: Dispatcher & EventBus Protocols
Status: Accepted. LocalTaskDispatcher/LocalEventBus for zero-cost dev; CloudTasksDispatcher/PubSubEventBus for production, selected via env. Worker endpoint /internal/execute_node is the Cloud Tasks target.
