#!/usr/bin/env bash
# Tear down the POC — by default both workspaces, one command.
#
#   ./destroy-all.sh              destroy the dev + prod app stacks (keeps the
#                                 Terraform state backend, which is ~free)
#   ./destroy-all.sh --env prod   destroy ONLY that workspace, leaving the other
#                                 one running
#   ./destroy-all.sh --nuke       destroy both, PLUS delete the workspaces, empty
#                                 the state bucket (all versions) and destroy
#                                 bootstrap. Leaves the AWS account with nothing.
#
# --nuke always spans both workspaces: it removes the shared state backend, so
# tearing down one environment while leaving the other's state homeless is never
# what you want. Use --env for single-environment teardown.
#
# Env:
#   AWS_PROFILE           local profile to auth with (default: mgmt)
#   TF_VAR_budget_email   required by the config (no default, so it is not
#                         committed to this public repo). Any syntactically
#                         valid address works for a destroy — the budget is
#                         being torn down, not created.
#
# Every resource in this config is built to be destroyable — no deletion
# protection, no RDS final snapshot, force_delete on ECR, 0-day secret recovery
# — in BOTH workspaces. See the POC note in locals.tf.

set -euo pipefail
cd "$(dirname "$0")"

PROFILE="${AWS_PROFILE:-mgmt}"
NUKE=false
ENVS=(dev prod)

# var.budget_email has no default so it never lands in this public repo. A
# destroy still evaluates it, so fall back to a placeholder rather than blocking
# a teardown on an unrelated variable — nothing is created here.
export TF_VAR_budget_email="${TF_VAR_budget_email:-teardown@example.com}"

while [ $# -gt 0 ]; do
  case "$1" in
    --nuke) NUKE=true; shift ;;
    --env)
      [ $# -ge 2 ] || { echo "--env needs a workspace name (dev|prod)" >&2; exit 2; }
      case "$2" in
        dev|prod) ENVS=("$2") ;;
        *) echo "unknown workspace '$2' (expected dev or prod)" >&2; exit 2 ;;
      esac
      shift 2 ;;
    *) echo "unknown argument '$1' (expected --nuke or --env <dev|prod>)" >&2; exit 2 ;;
  esac
done

# --nuke destroys the shared state backend, so it must span every workspace.
if $NUKE && [ "${#ENVS[@]}" -ne 2 ]; then
  echo "--nuke cannot be combined with --env: it deletes the shared state" >&2
  echo "backend, which would strand the other workspace's state." >&2
  exit 2
fi

echo "About to DESTROY these workspaces in profile '$PROFILE': ${ENVS[*]}"
$NUKE && echo "  --nuke: will ALSO delete the state bucket, lock table and workspaces."
printf "Type 'destroy' to continue: "
read -r reply
[ "$reply" = "destroy" ] || { echo "Aborted."; exit 1; }

terraform init -reconfigure -backend-config=backend.hcl

existing=$(terraform workspace list | tr -d ' *')

for env in "${ENVS[@]}"; do
  if ! grep -qx "$env" <<<"$existing"; then
    echo "── workspace '$env' does not exist, skipping"
    continue
  fi
  echo "── destroying workspace '$env'"
  terraform workspace select "$env"
  terraform destroy -auto-approve -var="aws_profile=$PROFILE"
done

if ! $NUKE; then
  echo "Done. App stacks destroyed; state backend kept."
  exit 0
fi

# --- full nuke ---------------------------------------------------------------
terraform workspace select default
for env in "${ENVS[@]}"; do
  grep -qx "$env" <<<"$existing" && terraform workspace delete "$env" || true
done

ACCOUNT=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)
BUCKET="agent-harness-tfstate-${ACCOUNT}"

# The bucket is versioned and bootstrap sets force_destroy=false, so Terraform
# cannot delete it while any object version or delete-marker remains.
echo "── emptying s3://$BUCKET (all versions)"
while true; do
  batch=$(aws s3api list-object-versions --bucket "$BUCKET" --max-keys 500 \
    --profile "$PROFILE" --output json \
    --query '{Objects: [Versions, DeleteMarkers][].{Key: Key, VersionId: VersionId}}')
  stripped=$(tr -d ' \n' <<<"$batch")
  [ "$stripped" = '{"Objects":null}' ] && break
  [ "$stripped" = '{"Objects":[]}' ] && break
  aws s3api delete-objects --bucket "$BUCKET" --delete "$batch" \
    --profile "$PROFILE" >/dev/null
done

echo "── destroying state backend (bootstrap)"
cd bootstrap
terraform init
terraform destroy -auto-approve -var="aws_profile=$PROFILE"

echo "Done. Nothing left in account $ACCOUNT."
