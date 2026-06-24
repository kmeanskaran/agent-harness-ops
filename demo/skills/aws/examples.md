# AWS Skill — Worked Examples

---

## Example 1: Upload / Download with S3 (boto3)

```python
import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3", region_name="us-east-1")


def upload_file(local_path: str, bucket: str, key: str) -> bool:
    """Upload a local file to S3. Returns True on success."""
    try:
        s3.upload_file(local_path, bucket, key)
        return True
    except ClientError as e:
        print(f"Upload failed ({e.response['Error']['Code']}): {e}")
        return False


def list_all_keys(bucket: str, prefix: str = "") -> list[str]:
    """List every key under a prefix using a paginator (handles >1000 objects)."""
    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(obj["Key"] for obj in page.get("Contents", []))
    return keys
```

Security note: the bucket should have Block Public Access ON and default SSE encryption.

---

## Example 2: Least-Privilege IAM Policy

"Allow an app to read/write only its own prefix in one bucket":

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AppPrefixReadWrite",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::my-app-bucket/app-data/*"
    },
    {
      "Sid": "ListBucketPrefixOnly",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::my-app-bucket",
      "Condition": {"StringLike": {"s3:prefix": "app-data/*"}}
    }
  ]
}
```

Anti-pattern to flag: `"Action": "s3:*", "Resource": "*"`.

---

## Example 3: Serverless API (architecture answer pattern)

**User asks:** "Design a backend for a small REST API."

**Recommended stack:**
```
Client -> API Gateway (HTTP API) -> Lambda (Python) -> DynamoDB
                                       |
                                  CloudWatch Logs
```
- **API Gateway HTTP API** — pay-per-request, built-in throttling.
- **Lambda** — no servers; scales to zero; 15-min max duration.
- **DynamoDB on-demand** — no capacity planning for spiky/low traffic.
- **Cost**: roughly free-tier friendly at low volume; all three are per-request pricing.
- **Alternative at scale**: sustained high traffic → ECS Fargate + ALB + Aurora.

---

## Example 4: Invoke Claude via Amazon Bedrock

```python
import json

import boto3

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

response = bedrock.converse(
    modelId="anthropic.claude-sonnet-4-6",
    messages=[{"role": "user", "content": [{"text": "Summarize what AWS Lambda is."}]}],
    inferenceConfig={"maxTokens": 512},
)
print(response["output"]["message"]["content"][0]["text"])
```

Requires IAM permission `bedrock:InvokeModel` on the model ARN and model access enabled in the Bedrock console.

---

## Example 5: Debugging "AccessDenied" Checklist

When the user reports `AccessDenied` on an AWS call, walk this list in order:
1. **Identity** — which principal is actually making the call? (`aws sts get-caller-identity`)
2. **IAM policy** — does it allow the exact action + resource ARN?
3. **Resource policy** — bucket policy / key policy / queue policy denying or not allowing?
4. **Explicit Deny** — SCPs (Organizations) and permission boundaries override Allows.
5. **Encryption** — KMS-encrypted resource also needs `kms:Decrypt`/`kms:GenerateDataKey`.
6. **Region/partition mismatch** — wrong region client hitting the wrong resource.

---

## Example 6: Useful AWS CLI One-Liners

```bash
# Who am I?
aws sts get-caller-identity

# List Lambda functions with runtime, sorted output
aws lambda list-functions --region us-east-1 \
  --query "Functions[].{Name:FunctionName,Runtime:Runtime}" --output table

# Tail logs of a Lambda live
aws logs tail /aws/lambda/my-fn --follow --region us-east-1

# S3 sync a folder up
aws s3 sync ./dist s3://my-bucket/site --delete
```