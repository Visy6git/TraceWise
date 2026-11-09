# ECS task definition templates

Create separate task definitions for `claims-orchestrator`, `rules-orchestrator`, `evaluator-orchestrator` and `claim-sandbox`. Do not reuse the API task role for agent tasks. Sandbox tasks must be non-root, no general network egress, read-only source mounts, scoped writable claim output, bounded resources and no ambient credentials.
