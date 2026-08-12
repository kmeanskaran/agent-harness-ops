# ElastiCache Redis — replaces the compose `redis` service. One cluster serves
# all three roles (Celery broker, job/status store, LLM cache), namespaced by
# key prefix. No auth token, so REDIS_URL is a plain env var (see ecs.tf).

resource "aws_elasticache_subnet_group" "main" {
  name       = "${local.name_prefix}-redis"
  subnet_ids = aws_subnet.public[*].id
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${local.name_prefix}-redis"
  description          = "agent-harness ${terraform.workspace} broker + cache"

  engine         = "redis"
  engine_version = "7.1"
  node_type      = local.env.redis_node_type
  port           = 6379

  num_cache_clusters         = local.env.redis_num_nodes
  automatic_failover_enabled = local.env.redis_num_nodes > 1
  multi_az_enabled           = local.env.redis_num_nodes > 1

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  # Broker/cache is disposable — no snapshots.
  snapshot_retention_limit = 0
  apply_immediately        = true

  tags = { Name = "${local.name_prefix}-redis" }
}
