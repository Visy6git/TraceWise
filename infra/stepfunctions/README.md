# Step Functions

`review_gated_workflow.asl.json` is an illustrative AWS Step Functions Standard Workflow skeleton. Replace all `REPLACE_*` placeholders and test failure/rework paths before deployment. The human review wait must use callback task tokens held only by the backend. The user-facing API should continue to use the same stage/review contract for local and AWS environments.
