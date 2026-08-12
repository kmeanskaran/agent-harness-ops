#!/usr/bin/env bash
# Verify NOTHING billable is left in the account after a teardown.
#
#   ./scripts/aws-verify-clean.sh            # profile mgmt, region us-east-1
#   AWS_PROFILE=other REGION=eu-west-1 ./scripts/aws-verify-clean.sh
#
# Exits 0 only if every check is empty. Anything found is printed with its
# identifier so you can delete it by hand.
#
# Covers more than this project creates on purpose: an interrupted destroy can
# strand things Terraform no longer tracks (orphaned EBS volumes, unattached
# Elastic IPs, RDS final snapshots), and those bill silently.

set -uo pipefail

PROFILE="${AWS_PROFILE:-mgmt}"
REGION="${REGION:-us-east-1}"
AWS="aws --profile $PROFILE --region $REGION"

found=0

# check <label> <cost-note> <aws query...>
check() {
  local label="$1" cost="$2"; shift 2
  local out
  out=$("$@" 2>/dev/null | tr '\t' ' ' | xargs 2>/dev/null)
  if [ -z "$out" ] || [ "$out" = "None" ]; then
    printf '  \033[32mok\033[0m    %-26s none\n' "$label"
  else
    printf '  \033[31mFOUND\033[0m %-26s %s   \033[33m(%s)\033[0m\n' "$label" "$out" "$cost"
    found=1
  fi
}

echo "Account: $($AWS sts get-caller-identity --query Account --output text 2>/dev/null)  region: $REGION"
echo
echo "── compute / networking"
check "ECS clusters"        "~\$35/mo of tasks" \
  $AWS ecs list-clusters --query 'clusterArns' --output text
check "Load balancers"      "~\$17/mo" \
  $AWS elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName' --output text
check "Target groups"       "free, but orphaned" \
  $AWS elbv2 describe-target-groups --query 'TargetGroups[].TargetGroupName' --output text
check "NAT gateways"        "~\$32/mo each" \
  $AWS ec2 describe-nat-gateways --filter Name=state,Values=available \
  --query 'NatGateways[].NatGatewayId' --output text
check "Elastic IPs"         "\$3.60/mo when unattached" \
  $AWS ec2 describe-addresses --query 'Addresses[].AllocationId' --output text
check "EBS volumes"         "\$0.08/GB-mo" \
  $AWS ec2 describe-volumes --query 'Volumes[].VolumeId' --output text
check "VPCs (non-default)"  "free, but leftovers" \
  $AWS ec2 describe-vpcs --filters Name=isDefault,Values=false \
  --query 'Vpcs[].VpcId' --output text

echo
echo "── data stores"
check "RDS instances"       "~\$14/mo" \
  $AWS rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier' --output text
check "RDS snapshots"       "\$0.095/GB-mo, outlive the DB" \
  $AWS rds describe-db-snapshots --snapshot-type manual \
  --query 'DBSnapshots[].DBSnapshotIdentifier' --output text
check "ElastiCache groups"  "~\$12/mo" \
  $AWS elasticache describe-replication-groups \
  --query 'ReplicationGroups[].ReplicationGroupId' --output text
check "ElastiCache snapshots" "storage cost" \
  $AWS elasticache describe-snapshots --query 'Snapshots[].SnapshotName' --output text
check "DynamoDB tables"     "\$0 idle on-demand" \
  $AWS dynamodb list-tables --query 'TableNames' --output text
check "S3 buckets"          "storage cost" \
  $AWS s3api list-buckets --query 'Buckets[].Name' --output text

echo
echo "── images, secrets, DNS, observability"
check "ECR repositories"    "\$0.10/GB-mo of layers" \
  $AWS ecr describe-repositories --query 'repositories[].repositoryName' --output text
check "Secrets Manager"     "\$0.40/secret/mo" \
  $AWS secretsmanager list-secrets --query 'SecretList[].Name' --output text
check "Cloud Map namespaces" "free, holds a Route53 zone" \
  $AWS servicediscovery list-namespaces --query 'Namespaces[].Name' --output text
check "Route53 hosted zones" "\$0.50/zone/mo" \
  $AWS route53 list-hosted-zones --query 'HostedZones[].Name' --output text
check "CloudWatch log groups" "\$0.03/GB-mo ingested" \
  $AWS logs describe-log-groups --query 'logGroups[].logGroupName' --output text
check "CloudWatch alarms"   "\$0.10/alarm/mo" \
  $AWS cloudwatch describe-alarms --query 'MetricAlarms[].AlarmName' --output text
check "SNS topics"          "free at rest" \
  $AWS sns list-topics --query 'Topics[].TopicArn' --output text

echo
echo "── IAM (free, but shows leftovers)"
check "Project IAM roles"   "free" \
  $AWS iam list-roles --query 'Roles[?starts_with(RoleName, `agent-harness`)].RoleName' --output text
check "OIDC providers"      "free" \
  $AWS iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn' --output text

echo
if [ "$found" -eq 0 ]; then
  echo -e "\033[32mCLEAN — nothing billable remains.\033[0m"
else
  echo -e "\033[31mNOT CLEAN — see FOUND rows above.\033[0m"
  echo "Some may be pre-existing and unrelated to this project; check names before deleting."
fi
exit "$found"
