# RDS Postgres 16 — replaces the compose `postgres` service.
# Lives in the public subnets but is NOT publicly accessible; the security group
# (ingress only from the ECS SG) is the real gate.
# The app's init_db() creates tables on boot, so no migration step is needed.

resource "random_password" "db" {
  length  = 24
  special = false # avoid URL-encoding issues inside DATABASE_URL
}

resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db"
  subnet_ids = aws_subnet.public[*].id
  tags       = { Name = "${local.name_prefix}-db" }
}

resource "aws_db_instance" "postgres" {
  identifier     = "${local.name_prefix}-postgres"
  engine         = "postgres"
  engine_version = "16"
  instance_class = local.env.db_instance_class

  allocated_storage = local.env.db_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = "devvoice"
  username = "devvoice"
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  multi_az               = local.env.db_multi_az
  publicly_accessible    = false

  # POC: every workspace is disposable. No final snapshot (it would outlive the
  # destroy and keep costing), no deletion protection. Restore both for a real
  # production environment.
  backup_retention_period   = local.env.db_backup_retention
  deletion_protection       = local.env.db_deletion_protection
  skip_final_snapshot       = true
  final_snapshot_identifier = null

  apply_immediately = true

  tags = { Name = "${local.name_prefix}-postgres" }
}
