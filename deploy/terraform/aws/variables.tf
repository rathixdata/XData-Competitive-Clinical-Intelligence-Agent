variable "environment" {
  description = "Deployment environment: staging or production."
  type        = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "VPC CIDR. Must match the ipBlock in the k8s NetworkPolicy overlay."
  type        = string
  default     = "10.10.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones to span."
  type        = number
  default     = 3
}

variable "eks_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.31"
}

variable "eks_node_instance_types" {
  description = "Instance types for the default managed node group."
  type        = list(string)
  default     = ["m6i.xlarge"]
}

variable "eks_node_min" {
  type    = number
  default = 2
}

variable "eks_node_max" {
  type    = number
  default = 10
}

variable "eks_node_desired" {
  type    = number
  default = 3
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.r6g.large"
}

variable "db_allocated_storage_gb" {
  type    = number
  default = 100
}

variable "db_max_allocated_storage_gb" {
  type    = number
  default = 1000
}

variable "db_backup_retention_days" {
  description = "Automated backup retention (enables PITR). 14 days per the DR policy."
  type        = number
  default     = 14
}

variable "redis_node_type" {
  type    = string
  default = "cache.r6g.large"
}

variable "raw_bucket_name" {
  description = "Globally-unique name of the raw-artifact bucket (immutable source retention)."
  type        = string
}

variable "backup_bucket_name" {
  description = "Globally-unique name of the logical-backup bucket (pg_dump CronJob)."
  type        = string
}

variable "object_lock_retention_days" {
  description = "Default Object Lock COMPLIANCE retention for raw source artifacts. Cannot be shortened once objects are written."
  type        = number
  default     = 2555 # ~7 years
}

variable "raw_glacier_transition_days" {
  description = "Days after which raw artifacts transition to Glacier Flexible Retrieval."
  type        = number
  default     = 90
}

variable "k8s_namespace" {
  description = "Namespace the app runs in (IRSA trust condition)."
  type        = string
  default     = "xdata"
}

variable "k8s_service_account" {
  description = "Service account bound to the app IRSA role."
  type        = string
  default     = "xdata"
}

variable "tags" {
  description = "Extra tags applied to every resource."
  type        = map(string)
  default     = {}
}
