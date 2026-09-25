output "vpc_id" {
  value = module.vpc.vpc_id
}

output "vpc_cidr" {
  description = "Use as the ipBlock in the k8s NetworkPolicy overlay."
  value       = module.vpc.vpc_cidr_block
}

output "eks_cluster_name" {
  value = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "rds_endpoint" {
  description = "host:port for XDATA_DATABASE_URL."
  value       = aws_db_instance.postgres.endpoint
}

output "rds_master_user_secret_arn" {
  description = "Secrets Manager secret holding the RDS-managed admin password."
  value       = aws_db_instance.postgres.master_user_secret[0].secret_arn
}

output "redis_primary_endpoint" {
  description = "Use rediss://:<token>@<endpoint>:6379/0 for XDATA_REDIS_URL."
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "raw_bucket" {
  value = aws_s3_bucket.raw.bucket
}

output "backup_bucket" {
  value = aws_s3_bucket.backups.bucket
}

output "s3_kms_key_alias" {
  description = "XDATA_S3_KMS_KEY_ID"
  value       = aws_kms_alias.s3.name
}

output "app_secret_name" {
  description = "Secrets Manager secret synced by external-secrets (populate out-of-band)."
  value       = aws_secretsmanager_secret.app.name
}

output "app_irsa_role_arn" {
  description = "Annotate the xdata ServiceAccount with this (eks.amazonaws.com/role-arn)."
  value       = aws_iam_role.app_irsa.arn
}

output "account_id" {
  value = data.aws_caller_identity.current.account_id
}
