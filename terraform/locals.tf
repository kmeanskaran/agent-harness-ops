# Per-environment sizing, keyed on the active workspace. Resource code reads
# local.env.* so it's identical across environments.
#
# NOTE (POC): this is a proof of concept — BOTH workspaces are sized the same
# (smallest everything, single node, no HA) and BOTH are built to be destroyed.
# `prod` here means "a second isolated stack", not "hardened and durable". If
# this ever becomes a real production environment, the things to restore are:
# multi-AZ RDS, >1 Redis node, >1 task per service, deletion protection, final
# snapshots, longer backup/log retention — plus the networking note below.
#
# NOTE (networking): tasks run in PUBLIC subnets with public IPs and NO NAT
# (saves ~$32/mo). Private subnets + NAT + HTTPS is deliberately not wired.

locals {
  name_prefix = "agent-harness-${terraform.workspace}"

  workspace_config = {
    dev = {
      az_count = 2 # 2 AZs required for the RDS subnet group + ALB, even in dev

      db_instance_class      = "db.t4g.micro"
      db_allocated_storage   = 20
      db_multi_az            = false
      db_backup_retention    = 1
      db_deletion_protection = false

      redis_node_type = "cache.t4g.micro"
      redis_num_nodes = 1

      api_cpu          = 256
      api_memory       = 512
      api_desired      = 1
      worker_cpu       = 512
      worker_memory    = 1024
      worker_desired   = 1
      frontend_cpu     = 256
      frontend_memory  = 512
      frontend_desired = 1

      log_retention_days = 7
    }

    # POC: identical to dev on purpose — same cost, same teardown behaviour.
    prod = {
      az_count = 2

      db_instance_class      = "db.t4g.micro"
      db_allocated_storage   = 20
      db_multi_az            = false
      db_backup_retention    = 1
      db_deletion_protection = false

      redis_node_type = "cache.t4g.micro"
      redis_num_nodes = 1

      api_cpu          = 256
      api_memory       = 512
      api_desired      = 1
      worker_cpu       = 512
      worker_memory    = 1024
      worker_desired   = 1
      frontend_cpu     = 256
      frontend_memory  = 512
      frontend_desired = 1

      log_retention_days = 7
    }
  }

  # Fall back to dev in the "default" workspace so validate/plan work before a
  # workspace is selected. Real work always runs under dev/prod.
  env = lookup(local.workspace_config, terraform.workspace, local.workspace_config["dev"])

  # Same image, different entrypoint — mirrors docker-compose.
  api_command    = ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
  worker_command = ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=info"]
}
