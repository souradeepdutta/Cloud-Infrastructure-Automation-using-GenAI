# tfsec Security Rules (Simplified for LocalStack)

**Source**: https://aquasecurity.github.io/tfsec/latest/checks/aws/

## S3 Bucket Security (aws-s3-\*)

**REQUIRED - All in main.tf:**

1. **aws_s3_bucket** - The main bucket resource
2. **aws_s3_bucket_server_side_encryption_configuration** - Use `sse_algorithm = "AES256"`
3. **aws_s3_bucket_public_access_block** - Block all public access (4 attributes = true)
4. **aws_s3_bucket_versioning** - Enable versioning `status = "Enabled"`

**Example for simple S3 bucket:**

```hcl
resource "aws_s3_bucket" "example" {
  bucket = "my-bucket"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "example" {
  bucket = aws_s3_bucket.example.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "example" {
  bucket                  = aws_s3_bucket.example.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "example" {
  bucket = aws_s3_bucket.example.id
  versioning_configuration {
    status = "Enabled"
  }
}
```

## EC2 Instance Security (aws-ec2-\*)

**REQUIRED:**

1. `metadata_options { http_tokens = "required" }`
2. `associate_public_ip_address = false`
3. EBS volumes: `encrypted = true` in `ebs_block_device`

## Other Resources (Only if requested)

**DynamoDB:** `server_side_encryption { enabled = true }`, `point_in_time_recovery { enabled = true }`
**Lambda:** `tracing_config { mode = "Active" }`, requires IAM role
**RDS:** `storage_encrypted = true`, `publicly_accessible = false`, `backup_retention_period = 7`

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
