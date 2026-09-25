environment                = "production"
region                     = "us-east-1"
vpc_cidr                   = "10.10.0.0/16"
az_count                   = 3
raw_bucket_name            = "xdata-ci-raw-prod"
backup_bucket_name         = "xdata-backups-prod"
object_lock_retention_days = 2555
k8s_namespace              = "xdata"
