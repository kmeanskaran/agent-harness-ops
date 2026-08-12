# VPC with PUBLIC subnets only (dev choice: no NAT gateway).
#   - Fargate tasks run here with public IPs and reach the internet (Bedrock,
#     Langfuse) directly via the internet gateway.
#   - RDS + ElastiCache also live in these subnets but are NOT publicly
#     accessible (publicly_accessible=false + security groups), so being in a
#     "public" subnet doesn't expose them — the SG is the real gate.
# Prod hardening (private subnets + NAT) is a later change; see locals.tf.

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs            = slice(data.aws_availability_zones.available.names, 0, local.env.az_count)
  public_subnets = [for i in range(local.env.az_count) : cidrsubnet("10.0.0.0/16", 4, i)]
}

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${local.name_prefix}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name_prefix}-igw" }
}

resource "aws_subnet" "public" {
  count                   = local.env.az_count
  vpc_id                  = aws_vpc.main.id
  cidr_block              = local.public_subnets[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true
  tags                    = { Name = "${local.name_prefix}-public-${local.azs[count.index]}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "${local.name_prefix}-public-rt" }
}

resource "aws_route_table_association" "public" {
  count          = local.env.az_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}
