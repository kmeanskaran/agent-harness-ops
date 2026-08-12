# Backend for the ORIGINAL dev member account (890439389722).
# Kept so the pre-existing stack there stays reachable — you need this to run
# `terraform destroy` against it once the management-account deploy is up.
#
#   terraform init -reconfigure -backend-config=backend.dev.hcl
bucket         = "agent-harness-tfstate-890439389722"
key            = "agent-harness/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "agent-harness-tflock"
encrypt        = true
