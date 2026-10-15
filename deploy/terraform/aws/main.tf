# =============================================================================
# XData CI Agent - AWS infrastructure (skeleton).
#   VPC -> EKS (IRSA) -> RDS PostgreSQL 16 (pgvector) -> ElastiCache Redis -> S3 (Object Lock)
#   + KMS keys, Secrets Manager containers, IRSA role for the app.
# One state per environment:  terraform apply -var-file=envs/<env>.tfvars
# =============================================================================

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

locals {
  name    = "xdata-${var.environment}"
  is_prod = var.environment == "production"
  azs     = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  tags = merge({
    Project     = "xdata-ci-agent"
    Environment = var.environment
    ManagedBy   = "terraform"
  }, var.tags)
}

# -----------------------------------------------------------------------------
# KMS - separate keys per data domain so access can be granted narrowly.
# -----------------------------------------------------------------------------
resource "aws_kms_key" "data" {
  description             = "${local.name}: RDS + ElastiCache encryption at rest"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "data" {
  name          = "alias/${local.name}-data"
  target_key_id = aws_kms_key.data.key_id
}

resource "aws_kms_key" "s3" {
  description             = "${local.name}: S3 raw artifacts + backups (SSE-KMS)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "s3" {
  name          = "alias/${local.name}-s3"
  target_key_id = aws_kms_key.s3.key_id
}

resource "aws_kms_key" "secrets" {
  description             = "${local.name}: Secrets Manager"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "secrets" {
  name          = "alias/${local.name}-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}

# -----------------------------------------------------------------------------
# Network
# -----------------------------------------------------------------------------
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.7"

  name = local.name
  cidr = var.vpc_cidr
  azs  = local.azs

  # /20 private (pods + nodes), /24 public (load balancers), /24 database, /24 cache
  private_subnets     = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets      = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 48 + i)]
  database_subnets    = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 64 + i)]
  elasticache_subnets = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 80 + i)]

  create_database_subnet_group    = true
  create_elasticache_subnet_group = true

  enable_nat_gateway     = true
  single_nat_gateway     = !local.is_prod # one NAT per AZ in production
  one_nat_gateway_per_az = local.is_prod
  enable_dns_hostnames   = true
  enable_dns_support     = true

  enable_flow_log                      = true
  create_flow_log_cloudwatch_log_group = true
  create_flow_log_cloudwatch_iam_role  = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
  }
}

# -----------------------------------------------------------------------------
# EKS
# -----------------------------------------------------------------------------
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.24"

  cluster_name    = local.name
  cluster_version = var.eks_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Restrict the public endpoint to CI / VPN CIDRs in a real deployment.
  cluster_endpoint_public_access           = true
  cluster_endpoint_private_access          = true
  enable_irsa                              = true
  enable_cluster_creator_admin_permissions = true

  cluster_addons = {
    coredns                = {}
    kube-proxy             = {}
    eks-pod-identity-agent = {}
    vpc-cni = {
      # enforce k8s NetworkPolicy natively (deploy/k8s/base/networkpolicy.yaml)
      configuration_values = jsonencode({ enableNetworkPolicy = "true" })
    }
  }

  eks_managed_node_groups = {
    default = {
      instance_types = var.eks_node_instance_types
      min_size       = var.eks_node_min
      max_size       = var.eks_node_max
      desired_size   = var.eks_node_desired
      capacity_type  = "ON_DEMAND"
      ami_type       = "AL2023_x86_64_STANDARD"

      metadata_options = {
        http_tokens                 = "required" # IMDSv2 only
        http_put_response_hop_limit = 1          # pods must use IRSA, not the node role
      }
    }
  }
}

# -----------------------------------------------------------------------------
# RDS PostgreSQL 16
# pgvector ("vector") and pg_trgm are trusted extensions on RDS and need no
# shared_preload_libraries. A one-time bootstrap (deploy/README.md) creates the
# non-superuser app role "xdata" (RLS must not be bypassed) and the extensions.
# -----------------------------------------------------------------------------
resource "aws_security_group" "rds" {
  name_prefix = "${local.name}-rds-"
  description = "PostgreSQL from EKS nodes/pods only"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description     = "PostgreSQL from EKS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_parameter_group" "pg16" {
  name_prefix = "${local.name}-pg16-"
  family      = "postgres16"
  description = "XData CI Agent PostgreSQL 16"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  parameter {
    name  = "log_connections"
    value = "1"
  }

  # pgvector HNSW index builds benefit from more maintenance memory (KB)
  parameter {
    name  = "maintenance_work_mem"
    value = "1048576"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "postgres" {
  identifier     = local.name
  engine         = "postgres"
  engine_version = "16.4"
  instance_class = var.db_instance_class

  db_name  = "xdata"
  username = "xdata_admin" # bootstrap/admin only - the app uses the non-superuser "xdata" role
  # Master password generated + rotated by RDS in Secrets Manager (never in code/state).
  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.secrets.key_id

  allocated_storage     = var.db_allocated_storage_gb
  max_allocated_storage = var.db_max_allocated_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.data.arn

  multi_az               = local.is_prod
  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  parameter_group_name   = aws_db_parameter_group.pg16.name

  # Automated backups + transaction logs => point-in-time recovery (RPO ~5 min, target 15)
  backup_retention_period  = var.db_backup_retention_days
  backup_window            = "02:00-03:00"
  maintenance_window       = "sun:04:00-sun:05:00"
  copy_tags_to_snapshot    = true
  delete_automated_backups = false

  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name}-final"

  auto_minor_version_upgrade            = true
  performance_insights_enabled          = true
  performance_insights_kms_key_id       = aws_kms_key.data.arn
  performance_insights_retention_period = 7
  enabled_cloudwatch_logs_exports       = ["postgresql", "upgrade"]
  iam_database_authentication_enabled   = true
}

# -----------------------------------------------------------------------------
# ElastiCache Redis 7 (Celery broker + rate limiter): TLS in transit + AUTH token
# -----------------------------------------------------------------------------
resource "random_password" "redis_auth" {
  length  = 64
  special = false # ElastiCache AUTH tokens allow only a restricted special-char set
}

resource "aws_security_group" "redis" {
  name_prefix = "${local.name}-redis-"
  description = "Redis from EKS nodes/pods only"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description     = "Redis TLS from EKS"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = local.name
  description          = "XData CI Agent broker / rate limiter"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.redis_node_type
  port                 = 6379
  parameter_group_name = "default.redis7"

  num_cache_clusters         = local.is_prod ? 2 : 1
  automatic_failover_enabled = local.is_prod
  multi_az_enabled           = local.is_prod

  subnet_group_name  = module.vpc.elasticache_subnet_group_name
  security_group_ids = [aws_security_group.redis.id]

  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.data.arn
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth.result

  snapshot_retention_limit = local.is_prod ? 7 : 1
  snapshot_window          = "03:00-04:00"
  apply_immediately        = !local.is_prod
}

# -----------------------------------------------------------------------------
# S3 - raw source artifacts (immutable retention, FR-SRC-008)
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "raw" {
  bucket              = var.raw_bucket_name
  object_lock_enabled = true # must be set at creation; also enables versioning

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    default_retention {
      mode = "COMPLIANCE" # nobody, including root, can delete/overwrite before expiry
      days = var.object_lock_retention_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.raw]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket                  = aws_s3_bucket.raw.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    id     = "archive-raw-artifacts"
    status = "Enabled"
    filter {}

    transition {
      days          = var.raw_glacier_transition_days
      storage_class = "GLACIER"
    }

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "GLACIER"
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.raw]
}

data "aws_iam_policy_document" "raw_bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.raw.arn, "${aws_s3_bucket.raw.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "raw" {
  bucket     = aws_s3_bucket.raw.id
  policy     = data.aws_iam_policy_document.raw_bucket.json
  depends_on = [aws_s3_bucket_public_access_block.raw]
}

# -----------------------------------------------------------------------------
# S3 - logical backups (pg_dump CronJob). Secondary to RDS PITR.
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "backups" {
  bucket = var.backup_bucket_name
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id

  rule {
    id     = "expire-logical-backups"
    status = "Enabled"
    filter {}

    transition {
      days          = 30
      storage_class = "GLACIER"
    }

    expiration {
      days = 365
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  depends_on = [aws_s3_bucket_versioning.backups]
}

# -----------------------------------------------------------------------------
# Secrets Manager - containers only. Values are written out-of-band
# (aws secretsmanager put-secret-value ...) and synced into k8s by external-secrets.
# See deploy/k8s/base/externalsecret.yaml for the expected JSON keys.
# -----------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "app" {
  name                    = "xdata/${var.environment}/app"
  description             = "XData CI Agent application secrets (${var.environment})"
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 30
}

# Redis AUTH token is generated here, so store it for operators / the app secret.
# (It is also in Terraform state: use an encrypted remote backend with restricted access.)
resource "aws_secretsmanager_secret" "redis_auth" {
  name                    = "xdata/${var.environment}/redis-auth-token"
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 30
}

resource "aws_secretsmanager_secret_version" "redis_auth" {
  secret_id     = aws_secretsmanager_secret.redis_auth.id
  secret_string = random_password.redis_auth.result
}

# -----------------------------------------------------------------------------
# IRSA - IAM role for the app's Kubernetes service account
# -----------------------------------------------------------------------------
data "aws_iam_policy_document" "app_irsa_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:sub"
      values   = ["system:serviceaccount:${var.k8s_namespace}:${var.k8s_service_account}"]
    }

    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app_irsa" {
  name               = "${local.name}-app-irsa"
  assume_role_policy = data.aws_iam_policy_document.app_irsa_trust.json
}

data "aws_iam_policy_document" "app" {
  statement {
    sid       = "RawBucketList"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.raw.arn, aws_s3_bucket.backups.arn]
  }

  # Raw artifacts: write-once/read. No delete permission (Object Lock enforces it anyway).
  statement {
    sid       = "RawObjects"
    actions   = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:PutObjectRetention"]
    resources = ["${aws_s3_bucket.raw.arn}/*"]
  }

  statement {
    sid       = "BackupObjects"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.backups.arn}/*"]
  }

  statement {
    sid       = "S3Kms"
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [aws_kms_key.s3.arn]
  }

  statement {
    sid       = "ReadAppSecrets"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [aws_secretsmanager_secret.app.arn, aws_secretsmanager_secret.redis_auth.arn]
  }

  statement {
    sid       = "SecretsKms"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.secrets.arn]
  }
}

resource "aws_iam_policy" "app" {
  name   = "${local.name}-app"
  policy = data.aws_iam_policy_document.app.json
}

resource "aws_iam_role_policy_attachment" "app" {
  role       = aws_iam_role.app_irsa.name
  policy_arn = aws_iam_policy.app.arn
}
