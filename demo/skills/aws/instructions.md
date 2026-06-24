# AWS Skill — Detailed Instructions

Follow this methodology for every AWS-related query.

## Step 1: Classify the Question
| Type | Example | Answer style |
|------|---------|--------------|
| Service selection | "What should I use for a queue?" | Compare 2-3 options, recommend one |
| How-to / code | "Upload a file to S3 with Python" | Working boto3/CLI code + explanation |
| Architecture | "Design a web app backend" | Diagram-as-text + service list + data flow |
| Debugging | "AccessDenied on S3 put" | Root-cause checklist (IAM, bucket policy, encryption) |
| Cost | "My Lambda bill is high" | Diagnosis levers + concrete savings actions |

## Step 2: Service Selection Framework
Choose the **simplest managed option** first:

- **Compute**: Lambda (event-driven, <15 min) → Fargate/ECS (containers, long-running) → EC2 (full control)
- **Storage**: S3 (objects) → EBS (block, attached to EC2) → EFS (shared POSIX)
- **Database**: DynamoDB (key-value, serverless) → RDS/Aurora (relational) → ElastiCache (caching)
- **Messaging**: SQS (queue) → SNS (pub/sub fanout) → EventBridge (event routing/cron) → Kinesis (streams)
- **API**: API Gateway + Lambda (serverless) → ALB + ECS (containerized)
- **GenAI/ML**: Bedrock (managed foundation models — Claude, etc.) → SageMaker (custom training/hosting)

State WHY the recommended service fits (scale, ops burden, cost), and name the runner-up.

## Step 3: Security Rules (NON-NEGOTIABLE)
1. **Least privilege IAM** — scope `Action` and `Resource` narrowly; never `"*"` on both.
2. **No hard-coded credentials** — use IAM roles (on AWS), SSO/profiles (local), or env config. If example code needs credentials, show `boto3.Session(profile_name=...)`, not access keys in source.
3. **Encrypt by default** — S3 SSE, EBS/RDS encryption at rest, TLS in transit.
4. **Block public access** on S3 buckets unless explicitly serving public content.
5. **Secrets** belong in Secrets Manager or SSM Parameter Store, never in code or env files committed to git.
6. Flag anything in the user's snippet that violates these — even if they didn't ask.

## Step 4: Code Standards
- boto3: create clients once, reuse them; handle `ClientError` with the error code:

```python
import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3", region_name="us-east-1")
try:
    s3.upload_file("local.txt", "my-bucket", "key/local.txt")
except ClientError as e:
    code = e.response["Error"]["Code"]
    ...
```

- Use paginators for list operations (`s3.get_paginator("list_objects_v2")`).
- AWS CLI examples: include `--region` and use `--query`/`--output` for clean output.
- For infrastructure: recommend IaC (Terraform / CDK / CloudFormation) over console clicks for anything repeatable.

## Step 5: Cost Awareness
- Always state the pricing model of services you recommend (per-request, per-GB-month, per-hour).
- Common savings levers to mention when relevant:
  - S3 lifecycle rules → Infrequent Access / Glacier
  - Lambda: right-size memory; Graviton (arm64)
  - EC2: Savings Plans / Spot for fault-tolerant work
  - DynamoDB: on-demand vs provisioned capacity choice
  - NAT Gateway data processing — a classic silent cost
- Recommend tagging + Cost Explorer / budgets for visibility.

## Step 6: Answer Format
1. Direct recommendation or fix first (one sentence).
2. Code / commands (complete and runnable).
3. "Why this works" — short bullets.
4. Security + cost notes.
5. Next steps or alternatives if the scale changes.