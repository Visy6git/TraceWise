# Terraform infrastructure placeholder

Implement production AWS resources in this directory. Required baseline: private versioned S3 (SSE-KMS, Block Public Access), RDS/Aurora PostgreSQL, ECS cluster/task definitions, ALB/API Gateway, private subnets/security groups, VPC endpoints, Step Functions Standard, SQS as needed, CloudWatch log groups/metrics, KMS keys, Secrets Manager, OIDC/Cognito and least-privilege IAM task roles. No deployment is possible from this starter because account/network/tenant settings and role policies are intentionally unspecified.
