# IAM role policies

Create separate least-privilege task roles for API, Run Control Plane callbacks, each stage orchestrator, analytics read access, artifact publisher, and sandbox. A task role must not be shared across stages if it would allow cross-stage workspace or artifact mutation. Reviewer task tokens are server-side secrets and never passed to models or browser code.
