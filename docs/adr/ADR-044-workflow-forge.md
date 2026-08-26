# ADR-044: Workflow Forge Templates
Status: Accepted. Forge stores the SUCCESS-node blueprint (capability, deps, inputs)
plus expected cost/runtime from the Capability Network. `run` rebuilds nodes with fresh
IDs and remapped dependencies, then executes through the normal runtime and critic.