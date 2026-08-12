# Deploying to AWS via GitHub Actions

How CI/CD works for this repo, and the one-time setup to enable it.

## The two pipelines

| Workflow | Trigger | Does | Touches AWS? |
|---|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | every push / PR | Ruff lint + format check, `terraform fmt`/`validate` | No |
| [`deploy.yml`](../.github/workflows/deploy.yml) | **manual** (Run workflow) | build both images → push ECR → `terraform apply` → roll ECS | Yes |

Deploy is **manual (`workflow_dispatch`)** while in dev phase — you press *Run
workflow* and pick `dev`. Flip it to `on: push` later once you trust it.

## Auth: OIDC, not stored keys

GitHub proves its identity to AWS with a short-lived OIDC token and **assumes a
role** — there are **no `AWS_ACCESS_KEY_ID` secrets in GitHub**. Same "identity,
not keys" idea as the Bedrock task role.

```
GitHub Actions run ──OIDC token──► IAM role agent-harness-github-deploy ──► deploy
                    (trusts repo:kmeanskaran/agent-harness-ops:*)
```

The role + trust policy live in [terraform/cicd.tf](../terraform/cicd.tf).

## One-time setup

### 1. Retire the standalone bedrock.tf (if not done)
It duplicates `provider "aws"` and blocks `terraform init`. Its role is already
folded into `iam.tf`.
```bash
cd terraform && export AWS_PROFILE=dev
terraform destroy            # removes the old standalone role
rm bedrock.tf terraform.tfstate*
```

### 2. Bootstrap state + create the OIDC role
```bash
cd bootstrap && terraform init && terraform apply && cd ..
terraform init
terraform workspace new dev
terraform apply -target=aws_iam_openid_connect_provider.github \
                -target=aws_iam_role.github_deploy \
                -var github_repo="kmeanskaran/agent-harness-ops"
terraform output github_deploy_role_arn      # copy this
```

### 3. Add GitHub Actions variables
Repo → **Settings → Secrets and variables → Actions → Variables** (not Secrets):

| Variable | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | the `github_deploy_role_arn` output above |
| `AWS_REGION` | `us-east-1` |

That's it — no keys, no secrets. Application secrets (Langfuse, Tavily) stay in
**Secrets Manager**; CI never sees them.

## Deploying

Actions tab → **deploy** → *Run workflow* → choose `dev`. The run:
1. Assumes the AWS role via OIDC
2. Builds `api` (from `.`) and `frontend` (from `./frontend`) for linux/amd64
3. Pushes both to ECR, tagged with the commit SHA
4. `terraform apply` with those image tags
5. Forces a new ECS deployment so tasks pick up the new images

First deploy also creates the whole stack (VPC, RDS, ElastiCache, ALB, ECS) —
~15 min. Later deploys just push a new image + roll ECS (~2–3 min).

## Notes

- **Secrets:** after the very first apply, set the placeholder secrets once
  (`aws secretsmanager put-secret-value ...`, see [terraform/README.md](../terraform/README.md)).
  They persist across deploys (`ignore_changes`), so this is one-time.
- **Prod:** the workflow already accepts `prod` as an input; it uses the `prod`
  workspace (multi-AZ, deletion protection). Add an approval gate
  (GitHub Environments → required reviewers) before enabling prod deploys.
- **Rollback:** re-run the workflow from an earlier commit — its SHA becomes the
  image tag, and `terraform apply` rolls ECS back to it.
