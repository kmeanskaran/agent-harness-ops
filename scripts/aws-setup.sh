#!/usr/bin/env bash
# Bring a clean AWS account to the point where `git push` can deploy.
#
#   ./scripts/aws-setup.sh                    # profile mgmt
#   AWS_PROFILE=other ./scripts/aws-setup.sh
#   ./scripts/aws-setup.sh --check            # report state, change nothing
#
# Three steps, in the only order that works:
#   1. bootstrap  — the state bucket, lock table, GitHub OIDC provider and
#                   deploy role. This is the one apply that must run by hand:
#                   GitHub cannot authenticate to AWS until the role exists.
#   2. init       — point the main config at the bucket step 1 created.
#   3. report     — print exactly what to paste into GitHub.
#
# Safe to re-run. Bootstrap is idempotent and the role ARN is identical every
# time (fixed role name + fixed account), so the GitHub value never changes —
# which is what makes this safe to run again after a `make aws-nuke`.

set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE="${AWS_PROFILE:-mgmt}"
REGION="${REGION:-us-east-1}"
CHECK_ONLY=false
[ "${1:-}" = "--check" ] && CHECK_ONLY=true

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
warn() { printf '  \033[33mmissing\033[0m %s\n' "$1"; }

# --- preflight ---------------------------------------------------------------
command -v terraform >/dev/null || { echo "terraform not found on PATH" >&2; exit 1; }
command -v aws       >/dev/null || { echo "aws cli not found on PATH" >&2; exit 1; }

if ! caller=$(aws sts get-caller-identity --profile "$PROFILE" --output json 2>&1); then
  echo "Cannot authenticate with AWS profile '$PROFILE'." >&2
  echo "Check ~/.aws/credentials, or run: aws configure --profile $PROFILE" >&2
  exit 1
fi
ACCOUNT=$(sed -n 's/.*"Account": "\([0-9]*\)".*/\1/p' <<<"$caller")
ARN=$(sed -n 's/.*"Arn": "\([^"]*\)".*/\1/p' <<<"$caller")

bold "Account $ACCOUNT  region $REGION  profile $PROFILE"
echo "  identity: $ARN"
case "$ARN" in
  *:root)
    printf '  \033[33mwarning\033[0m authenticating as ROOT. Root keys cannot be scoped\n'
    printf '          or safely revoked. Use an IAM user or SSO identity instead.\n' ;;
esac

# The bucket name is derived the same way bootstrap/main.tf derives it.
BUCKET="agent-harness-tfstate-${ACCOUNT}"
EXPECTED_ROLE="arn:aws:iam::${ACCOUNT}:role/agent-harness-github-deploy"

# --- current state -----------------------------------------------------------
echo
bold "Current state"
have_bucket=false; have_role=false
aws s3api head-bucket --bucket "$BUCKET" --profile "$PROFILE" >/dev/null 2>&1 \
  && { have_bucket=true; ok "state bucket   $BUCKET"; } || warn "state bucket   $BUCKET"
aws iam get-role --role-name agent-harness-github-deploy --profile "$PROFILE" >/dev/null 2>&1 \
  && { have_role=true; ok "deploy role    $EXPECTED_ROLE"; } || warn "deploy role    $EXPECTED_ROLE"

if $CHECK_ONLY; then
  echo
  { $have_bucket && $have_role; } \
    && echo "Ready to deploy." \
    || echo "Not bootstrapped — run without --check."
  exit 0
fi

# --- 1. bootstrap ------------------------------------------------------------
echo
bold "1/3  bootstrap (state bucket, lock table, OIDC provider, deploy role)"
(
  cd terraform/bootstrap
  terraform init -input=false >/dev/null
  terraform apply -auto-approve -input=false -var="aws_profile=$PROFILE"
) || { echo "bootstrap failed" >&2; exit 1; }

ROLE_ARN=$(cd terraform/bootstrap && terraform output -raw github_deploy_role_arn)

# --- 2. init the main config -------------------------------------------------
echo
bold "2/3  terraform init (main config -> s3://$BUCKET)"
# -reconfigure, not -migrate-state: after a nuke the local .terraform still
# points at the old, deleted backend, and migration would try to read it.
(cd terraform && AWS_PROFILE="$PROFILE" terraform init -reconfigure -input=false \
  -backend-config=backend.hcl >/dev/null) || { echo "terraform init failed" >&2; exit 1; }
ok "backend configured"

# CI creates the workspaces itself (`workspace select || workspace new`), so
# there is nothing to create here — just show what state already exists.
existing=$(cd terraform && terraform workspace list 2>/dev/null | tr -d ' *' | tr '\n' ' ')
ok "workspaces: ${existing:-default}"

# --- 3. what GitHub needs ----------------------------------------------------
echo
bold "3/3  Add these in GitHub -> Settings -> Secrets and variables -> Actions"
cat <<EOF

  VARIABLES tab (visible in logs — these are identifiers, not credentials):
    AWS_DEPLOY_ROLE_ARN   $ROLE_ARN
    AWS_REGION            $REGION

  SECRETS tab (masked in logs):
    BUDGET_EMAIL          <your email for AWS budget alerts>

  ENVIRONMENTS tab:
    dev    no protection rules  (deploys run straight through)
    prod   required reviewer    (this is the approval gate; without a
           protection rule the \`environment: prod\` job does NOT pause)

Then deploy:
    git push origin aws-deployment          # -> dev
    git tag prod-\$(date +%F) && git push origin prod-\$(date +%F)   # -> prod
EOF

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo
  echo "gh is authenticated — set the variables with:"
  echo "    gh variable set AWS_DEPLOY_ROLE_ARN --body '$ROLE_ARN'"
  echo "    gh variable set AWS_REGION --body '$REGION'"
  echo "    gh secret   set BUDGET_EMAIL      # prompts for the value"
fi
