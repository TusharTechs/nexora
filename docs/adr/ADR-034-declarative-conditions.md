# ADR-034: Declarative Conditional Branches
Status: Accepted. NodeCondition data is evaluated deterministically by the runtime; unmet conditions SKIPPED the node; failed dependencies cascade SKIPPED transitively.
