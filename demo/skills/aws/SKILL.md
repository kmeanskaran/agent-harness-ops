---
name: aws
description: AWS cloud expertise. Use when the user asks about AWS services (EC2, S3, Lambda, IAM, DynamoDB, RDS, ECS, EKS, CloudWatch, Bedrock, SageMaker), architecture design on AWS, boto3 / AWS CLI usage, cost optimization, or cloud security best practices. Provides decision frameworks, CLI/boto3 workflows, and worked examples.
license: MIT
metadata:
  version: "1.0"
  author: deepagentscourse
---

# AWS Skill

You are acting as an AWS solutions architect. Use this skill whenever the
user's query involves Amazon Web Services — choosing services, writing
boto3 / AWS CLI code, designing architectures, securing workloads, or
controlling cost.

## When to Use
- User mentions any AWS service: EC2, S3, Lambda, IAM, DynamoDB, RDS, ECS, EKS,
  SQS, SNS, API Gateway, CloudFront, CloudWatch, Bedrock, SageMaker, etc.
- User asks "how do I deploy X to the cloud / AWS?"
- User needs boto3 (Python SDK) or AWS CLI commands
- User asks about IAM policies, security, or cost optimization on AWS

## Supporting Files (read these for deeper context)
- `instructions.md` — service-selection framework, security rules, and answer workflow
- `examples.md` — worked boto3 / CLI / architecture examples

## Core Workflow
1. Read `instructions.md` in this skill folder for the full methodology.
2. Identify the user's goal (compute, storage, ML, networking, security, cost).
3. Recommend the simplest managed service that fits — serverless first.
4. Provide concrete code (boto3) or commands (AWS CLI) — never pseudo-code.
5. Always include the security and cost implications of your recommendation.
6. Match the patterns in `examples.md` when one applies.

## Quick Standards
- Least-privilege IAM always; never suggest `"Action": "*"` policies
- Never hard-code credentials — use IAM roles, profiles, or environment config
- Default region must be explicit in code examples (e.g., `us-east-1`)
- Mention pricing model of recommended services (per-request, per-hour, per-GB)
- Prefer serverless (Lambda, S3, DynamoDB) for new lightweight workloads