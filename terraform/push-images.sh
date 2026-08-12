#!/usr/bin/env bash
# Build the api + frontend images for linux/amd64 (Fargate) and push them to
# this environment's ECR repos, tagged with the git short SHA + latest.
#
#   AWS_PROFILE=dev ./push-images.sh dev
set -euo pipefail

ENVIRONMENT="${1:-dev}"
OPS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FE_DIR="${OPS_DIR}/frontend" # in-repo UI (not the retired sibling repo)
TAG="${2:-$(git -C "$OPS_DIR" rev-parse --short HEAD)}"

REGION="us-east-1"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
API_REPO="agent-harness-${ENVIRONMENT}-api"
FE_REPO="agent-harness-${ENVIRONMENT}-frontend"

echo ">> ECR login: ${REGISTRY}"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

echo ">> Building api (${API_REPO}:${TAG})"
docker build --platform linux/amd64 \
  -t "${REGISTRY}/${API_REPO}:${TAG}" -t "${REGISTRY}/${API_REPO}:latest" "$OPS_DIR"

echo ">> Building frontend (${FE_REPO}:${TAG})"
docker build --platform linux/amd64 \
  -t "${REGISTRY}/${FE_REPO}:${TAG}" -t "${REGISTRY}/${FE_REPO}:latest" "$FE_DIR"

echo ">> Pushing"
docker push "${REGISTRY}/${API_REPO}:${TAG}"
docker push "${REGISTRY}/${API_REPO}:latest"
docker push "${REGISTRY}/${FE_REPO}:${TAG}"
docker push "${REGISTRY}/${FE_REPO}:latest"

echo
echo ">> Done. Deploy this tag with:"
echo "   terraform apply -var=api_image_tag=${TAG} -var=frontend_image_tag=${TAG}"
