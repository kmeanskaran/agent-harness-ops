# Deploying to AWS via GitHub Actions

> **Superseded.** The full account — architecture, from-scratch runbook, the
> pipeline, and the bugs found along the way — now lives in
> [aws_deployment_from_scratch.md](aws_deployment_from_scratch.md). This page is
> kept as a short reference for the CI/CD mechanics only.

## One workflow, not two

There is a single pipeline, [`ci.yml`](../.github/workflows/ci.yml). The old
`deploy.yml` was merged into it so deploys are gated on the checks passing.

| Stage | Jobs | Touches AWS? |
| --- | --- | --- |
| checks | `quality`, `terraform`, `test`, `smoke` | no |
| deploy | `target`, `ecr`, `build`, `deploy` | yes |

```
push to aws-deployment  ->  dev   (automatic, after all checks pass)
push tag prod-*         ->  prod  (waits for the required reviewer)
pull request            ->  checks only
```

Deploys are push-driven rather than manual because the "Run workflow" button
requires the workflow to live on the repo's default branch, and `master` is
deliberately kept free of AWS code. The approval gate is attached to the GitHub
Environment, so it works identically on a tag push.

## Auth: OIDC, not stored keys

GitHub proves its identity with a short-lived OIDC token and assumes a role.
There are **no `AWS_ACCESS_KEY_ID` secrets in GitHub** — same "identity, not
keys" idea as the Bedrock task role.

```
GitHub Actions run ──OIDC token──► IAM role agent-harness-github-deploy ──► deploy
```

The role and its trust policy live in
[terraform/bootstrap/main.tf](../terraform/bootstrap/main.tf) — not the main
config, because the role name and OIDC provider are account-level and
unnamespaced, so applying them from both workspaces would collide with
`EntityAlreadyExists`.

The trust policy allows four exact subjects. Both forms are required: a job that
declares `environment:` gets `repo:<owner>/<repo>:environment:<name>`, while one
that does not gets `repo:<owner>/<repo>:ref:<git-ref>`. GitHub substitutes the
environment for the ref rather than including both.

## Setup

Two GitHub Actions **Variables** (not Secrets):

| Variable | Value |
| --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | `terraform output github_deploy_role_arn` from bootstrap |
| `AWS_REGION` | `us-east-1` |

Plus two **Environments**: `dev` (no rules) and `prod` (required reviewer).

If `AWS_DEPLOY_ROLE_ARN` is unset, the pipeline runs checks only and stays
green — deploys skip rather than fail. Application secrets (Langfuse, Tavily)
stay in Secrets Manager; CI never sees them.

Full steps: [aws_deployment_from_scratch.md](aws_deployment_from_scratch.md).

## Rollback

Push a tag at an earlier commit, or revert and push. The image tag is the commit
SHA, so `terraform apply` rolls ECS back to exactly that build.
