# tfsec Security Policies for Common AWS Resources

## 📋 Critical Security Policies by Resource Type

This document contains the most important tfsec security checks that should be followed when generating Terraform code.

---

## 🪣 S3 Bucket Security Policies

### Must Have (Critical):

1. **Enable bucket encryption** (`aws-s3-enable-bucket-encryption`)

   - Use `aws_s3_bucket_server_side_encryption_configuration`
   - Set `sse_algorithm` to "AES256" or "aws:kms"

2. **Block all public access** (`aws-s3-specify-public-access-block`)

   - Use `aws_s3_bucket_public_access_block`
   - Set all four settings to `true`:
     - `block_public_acls = true`
     - `block_public_policy = true`
     - `ignore_public_acls = true`
     - `restrict_public_buckets = true`

3. **Enable versioning** (`aws-s3-enable-versioning`)
   - Use `aws_s3_bucket_versioning`
   - Set `status = "Enabled"`

### Should Have (High Priority):

4. **Enable bucket logging** (`aws-s3-enable-bucket-logging`)
   - Use `aws_s3_bucket_logging`
   - Configure target bucket and prefix

---

## ⚡ Lambda Function Security Policies

### Must Have (Critical):

1. **Restrict source ARN** (`aws-lambda-restrict-source-arn`)

   - Add `source_arn` to `aws_lambda_permission`
   - Restrict which services can invoke the function

2. **Enable tracing** (`aws-lambda-enable-tracing`)

   - Add `tracing_config` block with `mode = "Active"`
   - Enables AWS X-Ray

3. **Use proper IAM role** (general best practice)
   - Create dedicated `aws_iam_role` with least privilege
   - Use `assume_role_policy` with specific service principals
   - Attach only necessary policies

---

## 🗄️ DynamoDB Table Security Policies

### Must Have (Critical):

1. **Enable at-rest encryption** (`aws-dynamodb-enable-at-rest-encryption`)

   - Add `server_side_encryption` block
   - Set `enabled = true`

2. **Enable point-in-time recovery** (`aws-dynamodb-enable-recovery`)
   - Add `point_in_time_recovery` block
   - Set `enabled = true`

### Should Have (High Priority):

3. **Use customer-managed KMS key** (`aws-dynamodb-table-customer-key`)
   - Set `kms_key_arn` in `server_side_encryption` block

---

## 🖥️ EC2 / EBS Security Policies

### Must Have (Critical):

1. **Enable volume encryption** (`aws-ebs-enable-volume-encryption`, `aws-ec2-enable-volume-encryption`)

   - Set `encrypted = true` on EBS volumes
   - Set `encrypted = true` on `ebs_block_device`

2. **No public IP** (`aws-ec2-no-public-ip`)

   - Set `associate_public_ip_address = false`

3. **Enforce HTTP token for IMDS** (`aws-ec2-enforce-http-token-imds`)

   - Add `metadata_options` block
   - Set `http_tokens = "required"`
   - Set `http_endpoint = "enabled"`

4. **Security group descriptions** (`aws-ec2-add-description-to-security-group`)

   - Always add `description` to security groups

5. **No excessive port access** (`aws-ec2-no-excessive-port-access`)

   - Avoid opening all ports (0-65535)
   - Be specific with port ranges

6. **No public ingress** (`aws-ec2-no-public-ingress-sgr`)
   - Avoid `cidr_blocks = ["0.0.0.0/0"]` for ingress rules
   - Use specific IP ranges

---

## 🔐 IAM Security Policies

### Must Have (Critical):

1. **No policy wildcards** (`aws-iam-no-policy-wildcards`)

   - Avoid `Action = "*"` or `Resource = "*"`
   - Use specific actions and resources

2. **Enforce MFA** (`aws-iam-enforce-mfa`)

   - Require MFA for sensitive operations

3. **No user attached policies** (`aws-iam-no-user-attached-policies`)

   - Attach policies to groups/roles, not directly to users

4. **Password policy requirements**:
   - Minimum length: 14 characters (`aws-iam-set-minimum-password-length`)
   - Require uppercase (`aws-iam-require-uppercase-in-passwords`)
   - Require lowercase (`aws-iam-require-lowercase-in-passwords`)
   - Require numbers (`aws-iam-require-numbers-in-passwords`)
   - Require symbols (`aws-iam-require-symbols-in-passwords`)
   - Max password age: 90 days (`aws-iam-set-max-password-age`)

---

## 🗃️ RDS Database Security Policies

### Must Have (Critical):

1. **Encrypt instance storage** (`aws-rds-encrypt-instance-storage-data`)

   - Set `storage_encrypted = true`

2. **No public access** (`aws-rds-no-public-db-access`)

   - Set `publicly_accessible = false`

3. **Backup retention** (`aws-rds-specify-backup-retention`)
   - Set `backup_retention_period` (minimum 7 days)

### Should Have (High Priority):

4. **Enable performance insights** (`aws-rds-enable-performance-insights`)

   - Set `enabled_performance_insights = true`

5. **Encrypt performance insights** (`aws-rds-enable-performance-insights-encryption`)
   - Set `performance_insights_kms_key_id`

---

## 📬 SQS Queue Security Policies

### Must Have (Critical):

1. **Enable queue encryption** (`aws-sqs-enable-queue-encryption`)

   - Set `kms_master_key_id` or use default encryption

2. **No wildcards in policy** (`aws-sqs-no-wildcards-in-policy-documents`)
   - Be specific in SQS policies

---

## 📢 SNS Topic Security Policies

### Must Have (Critical):

1. **Enable topic encryption** (`aws-sns-enable-topic-encryption`)
   - Set `kms_master_key_id` for encryption

---

## 🔑 KMS Key Security Policies

### Must Have (Critical):

1. **Auto-rotate keys** (`aws-kms-auto-rotate-keys`)
   - Set `enable_key_rotation = true`

---

## 🌐 VPC / Network Security Policies

### Must Have (Critical):

1. **No default VPC** (`aws-vpc-no-default-vpc`)

   - Don't use default VPC for production

2. **Add security group descriptions** (`aws-vpc-add-description-to-security-group`)

   - Always include description

3. **No excessive port access** (`aws-vpc-no-excessive-port-access`)

   - Limit port ranges

4. **No public ingress** (`aws-vpc-no-public-ingress-sgr`)
   - Restrict public access

---

## 🚪 API Gateway Security Policies

### Must Have (Critical):

1. **Enable access logging** (`aws-api-gateway-enable-access-logging`)

   - Configure CloudWatch logging

2. **Enable cache encryption** (`aws-api-gateway-enable-cache-encryption`)

   - Encrypt API Gateway cache

3. **Use secure TLS policy** (`aws-api-gateway-use-secure-tls-policy`)
   - Use TLS 1.2 or higher

---

## 📦 ECS/ECR Security Policies

### Must Have (Critical):

1. **Enable image scans** (`aws-ecr-enable-image-scans`)

   - Set `scan_on_push = true`

2. **No public access** (`aws-ecr-no-public-access`)

   - Don't make ECR repositories public

3. **Enable in-transit encryption** (`aws-ecs-enable-in-transit-encryption`)

   - Configure TLS for ECS services

4. **No plaintext secrets** (`aws-ecs-no-plaintext-secrets`)
   - Use Secrets Manager or Parameter Store

---

## 🎯 Priority Matrix

### ALWAYS Include (P0 - Critical):

- ✅ Encryption at rest (S3, DynamoDB, RDS, EBS)
- ✅ Block public access (S3, RDS, ECR)
- ✅ No wildcards in IAM policies
- ✅ Encryption in transit
- ✅ Proper security group configuration

### Usually Include (P1 - High):

- ✅ Versioning (S3)
- ✅ Point-in-time recovery (DynamoDB)
- ✅ Backup retention (RDS)
- ✅ Logging enabled
- ✅ Tracing enabled (Lambda)

### Good to Include (P2 - Medium):

- ✅ Customer-managed KMS keys
- ✅ Performance insights
- ✅ Key rotation

---

## 📚 References

- Full tfsec AWS checks: https://aquasecurity.github.io/tfsec/latest/checks/aws/
- tfsec GitHub: https://github.com/aquasecurity/tfsec
- AWS Security Best Practices: https://docs.aws.amazon.com/security/

---

## 💡 Usage in Code Generation

When generating Terraform code, ensure:

1. **S3 Buckets** = Bucket + Encryption + Public Access Block + Versioning
2. **Lambda Functions** = Function + IAM Role + Tracing Config
3. **DynamoDB Tables** = Table + Server-Side Encryption + Point-in-Time Recovery
4. **EC2 Instances** = Instance + Encrypted EBS + No Public IP + Secure SG
5. **RDS Databases** = DB + Encryption + No Public Access + Backups
6. **IAM Policies** = Least Privilege + No Wildcards + Specific Actions/Resources

**Golden Rule:** Security features should be default, not optional!
