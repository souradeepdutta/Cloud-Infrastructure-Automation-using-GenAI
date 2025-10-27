# tfsec Security Rules (Official Requirements)

**Source**: https://aquasecurity.github.io/tfsec/latest/checks/aws/

## EC2 Instance Security (aws-ec2-\*)

**CRITICAL - Must pass tfsec:**

1. **enforce-http-token-imds** - `metadata_options { http_tokens = "required" }`
2. **no-public-ip** - `associate_public_ip_address = false`
3. **enable-volume-encryption** - EBS volumes: `encrypted = true` in `ebs_block_device`

## S3 Bucket Security (aws-s3-\*)

**CRITICAL - Must pass tfsec:**

1. **enable-bucket-encryption** - Separate resource: `aws_s3_bucket_server_side_encryption_configuration` with `sse_algorithm = "AES256"`
2. **specify-public-access-block** - Separate resource: `aws_s3_bucket_public_access_block` with `block_public_acls = true`, `block_public_policy = true`, `ignore_public_acls = true`, `restrict_public_buckets = true`
3. **enable-versioning** - Separate resource: `aws_s3_bucket_versioning` with `status = "Enabled"`

## DynamoDB Security (aws-dynamodb-\*)

**CRITICAL - Must pass tfsec:**

1. **enable-at-rest-encryption** - `server_side_encryption { enabled = true }`
2. **enable-recovery** - `point_in_time_recovery { enabled = true }`

## Lambda Security (aws-lambda-\*)

**CRITICAL - Must pass tfsec:**

1. **enable-tracing** - `tracing_config { mode = "Active" }`
2. **restrict-source-arn** - In `aws_lambda_permission`: add `source_arn = "arn:aws:..."`

**Note**: Lambda requires IAM role with assume_role_policy for service principal

## RDS Security (aws-rds-\*)

**CRITICAL - Must pass tfsec:**

1. **encrypt-instance-storage-data** - `storage_encrypted = true`
2. **no-public-db-access** - `publicly_accessible = false`
3. **specify-backup-retention** - `backup_retention_period = 7` (minimum)

## SQS Security (aws-sqs-\*)

**CRITICAL - Must pass tfsec:**

1. **enable-queue-encryption** - `kms_master_key_id = "alias/aws/sqs"` or custom KMS key

## SNS Security (aws-sns-\*)

**CRITICAL - Must pass tfsec:**

1. **enable-topic-encryption** - `kms_master_key_id = "alias/aws/sns"` or custom KMS key

## IAM Security (aws-iam-\*)

**CRITICAL - Must pass tfsec:**

1. **no-policy-wildcards** - Avoid `Action = "*"` or `Resource = "*"` in policies
2. **no-user-attached-policies** - Attach policies to roles/groups, not users

## VPC/Security Group (aws-vpc-_, aws-ec2-_)

**CRITICAL - Must pass tfsec:**

1. **add-description-to-security-group** - Always add `description` to security groups
2. **no-public-ingress-sgr** - Avoid `cidr_blocks = ["0.0.0.0/0"]` in ingress rules

## KMS Security (aws-kms-\*)

**CRITICAL - Must pass tfsec:**

1. **auto-rotate-keys** - `enable_key_rotation = true` for KMS keys

---

## Constants (Always True - HARDCODE THESE)

- **LocalStack AMI**: `ami-ff0fea8310f3` (for ALL EC2 instances)
- **LocalStack endpoint**: `http://localhost:4566` (for ALL services)
- **AWS region**: `us-east-1`
- **Test credentials**: `access_key = "test"`, `secret_key = "test"`
- **S3 encryption**: Use `AES256` (not KMS for simplicity)
- **Port 80**: HTTP
- **Port 443**: HTTPS
- **Port 22**: SSH
- **Port 3306**: MySQL
- **Port 5432**: PostgreSQL

## Instance Type RAM Mapping (REFERENCE)

- t3.micro = 1GB
- t3.small = 2GB
- t3.medium = 4GB
- t3.large = 8GB
- t3.xlarge = 16GB
- t3.2xlarge = 32GB
- t3.4xlarge = 64GB
