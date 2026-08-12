# Active backend — the org MANAGEMENT account (585662413932).
#
# Both workspaces (dev, prod) share this bucket; Terraform namespaces them under
# env:/<workspace>/<key>, so their state never collides.
#
# The bucket must already exist — create it with ./bootstrap first.
#
#   terraform init -reconfigure -backend-config=backend.hcl
bucket         = "agent-harness-tfstate-585662413932"
key            = "agent-harness/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "agent-harness-tflock"
encrypt        = true
