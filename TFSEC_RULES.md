# tfsec Security Rules for AWS Infrastructure

**Source**: https://aquasecurity.github.io/tfsec/latest/checks/aws/

---

## 🎲 Unique Resource Names (CRITICAL)

**ALWAYS use `random_id` to generate unique names for resources to avoid conflicts with previous deployments:**

```hcl
resource "random_id" "suffix" {
  byte_length = 4
}
```

**Apply to these resources:**

- S3 buckets: `bucket = "my-bucket-${random_id.suffix.hex}"`
- Security groups: `name_prefix = "my-sg-${random_id.suffix.hex}-"`
- DynamoDB tables: `name = "my-table-${random_id.suffix.hex}"`
- Lambda functions: `function_name = "my-function-${random_id.suffix.hex}"`
- RDS instances: `identifier = "my-db-${random_id.suffix.hex}"`
- IAM roles: `name = "my-role-${random_id.suffix.hex}"`

**Add random provider to provider.tf:**

```hcl
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}
```

---

## 📋 Priority Matrix

### ALWAYS Include (P0 - Critical):

- ✅ Encryption at rest (S3, DynamoDB, RDS, EBS)
- ✅ Block public access (S3, RDS, EC2)
- ✅ No wildcards in IAM policies
- ✅ Proper security group configuration
- ✅ Secure metadata access (EC2)

### Usually Include (P1 - High):

- ✅ Versioning (S3)
- ✅ Point-in-time recovery (DynamoDB)
- ✅ Backup retention (RDS)
- ✅ Tracing enabled (Lambda)

### Good to Include (P2 - Medium):

- ✅ Logging enabled
- ✅ Performance insights
- ✅ Key rotation

---

## 🪣 S3 Bucket Security (aws-s3-\*)

### REQUIRED - Must Create 4 Resources in main.tf:

1. **aws_s3_bucket** - The main bucket resource
2. **aws_s3_bucket_server_side_encryption_configuration** - Use `sse_algorithm = "AES256"`
3. **aws_s3_bucket_public_access_block** - Block all public access (4 attributes = true)
4. **aws_s3_bucket_versioning** - Enable versioning `status = "Enabled"`

### Complete Example:

```hcl
resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "example" {
  bucket = "my-unique-bucket-${random_id.suffix.hex}"

  tags = {
    Name        = "My Bucket"
    Environment = "Production"
  }
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

### Optional (High Priority):

5. **aws_s3_bucket_logging** - Enable access logging (DO NOT use if this IS the logging bucket)

```hcl
resource "aws_s3_bucket_logging" "example" {
  bucket        = aws_s3_bucket.example.id
  target_bucket = aws_s3_bucket.logs.id
  target_prefix = "log/"
}
```

---

## 🖥️ EC2 Instance Security (aws-ec2-_, aws-ebs-_)

### REQUIRED:

1. **Secure Metadata Access**: `metadata_options { http_tokens = "required", http_endpoint = "enabled" }`
2. **No Public IP**: `associate_public_ip_address = false`
3. **Encrypted EBS**: `encrypted = true` in all `ebs_block_device` and `root_block_device`

### Complete Example:

```hcl
resource "aws_instance" "example" {
  ami           = "ami-ff0fea8310f3"
  instance_type = "t3.small"

  associate_public_ip_address = false

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    encrypted = true
  }

  ebs_block_device {
    device_name = "/dev/sdb"
    volume_size = 20
    encrypted   = true
  }

  tags = {
    Name = "My Instance"
  }
}
```

### Security Group Best Practices:

**Note:** The `aws-ec2-no-public-egress-sgr` check is excluded from our tfsec scans because egress to 0.0.0.0/0 is standard practice - instances need internet access for updates, package downloads, and API calls.

**IMPORTANT:** Always use `name_prefix` with random_id suffix for security groups to avoid conflicts with existing resources from previous deployments.

```hcl
resource "aws_security_group" "example" {
  name_prefix = "example-sg-${random_id.suffix.hex}-"
  description = "Security group for example application"
  vpc_id      = aws_vpc.main.id

  # DO NOT use 0.0.0.0/0 for ingress unless absolutely necessary
  ingress {
    description = "HTTPS from VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.main.cidr_block]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]  # This is standard practice and excluded from tfsec checks
  }

  tags = {
    Name = "example-security-group"
  }
}
```

---

## ⚡ Lambda Function Security (aws-lambda-\*)

### REQUIRED:

1. **IAM Role**: Dedicated role with least privilege
2. **Enable Tracing**: `tracing_config { mode = "Active" }`
3. **Restrict Permissions**: Add `source_arn` to `aws_lambda_permission`

### Complete Example:

```hcl
resource "aws_iam_role" "lambda_role" {
  name = "lambda-execution-role-${random_id.suffix.hex}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "example" {
  filename      = "lambda_function.zip"
  function_name = "example-function-${random_id.suffix.hex}"
  role          = aws_iam_role.lambda_role.arn
  handler       = "index.handler"
  runtime       = "python3.9"

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = {
      ENV = "production"
    }
  }
}

resource "aws_lambda_permission" "allow_api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.example.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.example.execution_arn}/*/*"
}
```

---

## 🗄️ DynamoDB Table Security (aws-dynamodb-\*)

### REQUIRED:

1. **At-rest Encryption**: `server_side_encryption { enabled = true }`
2. **Point-in-Time Recovery**: `point_in_time_recovery { enabled = true }`

### Complete Example:

```hcl
resource "aws_dynamodb_table" "example" {
  name           = "example-table-${random_id.suffix.hex}"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "id"

  attribute {
    name = "id"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name = "example-table"
  }
}
```

---

## 🗃️ RDS Database Security (aws-rds-\*)

### REQUIRED:

1. **Storage Encryption**: `storage_encrypted = true`
2. **No Public Access**: `publicly_accessible = false`
3. **Backup Retention**: `backup_retention_period = 7` (minimum)

### Complete Example:

```hcl
resource "aws_db_instance" "example" {
  identifier           = "example-db-${random_id.suffix.hex}"
  engine               = "mysql"
  engine_version       = "8.0"
  instance_class       = "db.t3.micro"
  allocated_storage    = 20

  db_name  = "exampledb"
  username = "admin"
  password = "changeme123!"

  storage_encrypted        = true
  publicly_accessible      = false
  backup_retention_period  = 7

  skip_final_snapshot = true

  tags = {
    Name = "example-database"
  }
}
```

---

## 🔐 IAM Security (aws-iam-\*)

### CRITICAL RULES:

1. **No Wildcards**: Avoid `Action = "*"` or `Resource = "*"`
2. **Least Privilege**: Grant only necessary permissions
3. **Attach to Groups/Roles**: Not directly to users

### Example (Good vs Bad):

```hcl
# ❌ BAD - Too permissive
resource "aws_iam_policy" "bad" {
  name = "bad-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "*"
      Resource = "*"
    }]
  })
}

# ✅ GOOD - Specific permissions
resource "aws_iam_policy" "good" {
  name = "good-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject"
      ]
      Resource = "arn:aws:s3:::my-bucket/*"
    }]
  })
}
```

---

## 📬 SQS Queue Security (aws-sqs-\*)

### REQUIRED:

1. **Enable Encryption**: Set `kms_master_key_id` or use default encryption

```hcl
resource "aws_sqs_queue" "example" {
  name = "example-queue"

  kms_master_key_id                 = "alias/aws/sqs"
  kms_data_key_reuse_period_seconds = 300

  tags = {
    Name = "example-queue"
  }
}
```

---

## 📢 SNS Topic Security (aws-sns-\*)

### REQUIRED:

1. **Enable Encryption**: Set `kms_master_key_id`

```hcl
resource "aws_sns_topic" "example" {
  name = "example-topic"

  kms_master_key_id = "alias/aws/sns"

  tags = {
    Name = "example-topic"
  }
}
```

---

## 🔑 KMS Key Security (aws-kms-\*)

### REQUIRED:

1. **Auto-rotate Keys**: `enable_key_rotation = true`

```hcl
resource "aws_kms_key" "example" {
  description             = "Example KMS key"
  enable_key_rotation     = true
  deletion_window_in_days = 10

  tags = {
    Name = "example-key"
  }
}
```

---

## 🌐 VPC / Network Security (aws-vpc-_, aws-ec2-_)

### BEST PRACTICES:

1. **Don't use default VPC** for production
2. **Add security group descriptions** always
3. **Limit port ranges** - be specific
4. **Restrict public access** - avoid 0.0.0.0/0 for ingress

---

## 📦 ECS/ECR Security (aws-ecr-_, aws-ecs-_)

### REQUIRED:

1. **Enable Image Scans**: `scan_on_push = true`
2. **No Public Access**: Keep repositories private
3. **Enable TLS**: Configure encryption in transit
4. **No Plaintext Secrets**: Use Secrets Manager

```hcl
resource "aws_ecr_repository" "example" {
  name                 = "example-repo"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "example-repository"
  }
}
```

---

## 🚪 API Gateway Security (aws-api-gateway-\*)

### REQUIRED:

1. **Enable Access Logging**: Configure CloudWatch logs
2. **Enable Cache Encryption**: Encrypt API cache
3. **Use Secure TLS**: TLS 1.2 or higher

### Common Ports:

- **Port 80**: HTTP
- **Port 443**: HTTPS
- **Port 22**: SSH
- **Port 3306**: MySQL
- **Port 5432**: PostgreSQL
- **Port 5672**: RabbitMQ
- **Port 6379**: Redis
- **Port 27017**: MongoDB

### Instance Type RAM Mapping (REFERENCE):

- `t3.micro` = 1GB RAM
- `t3.small` = 2GB RAM
- `t3.medium` = 4GB RAM
- `t3.large` = 8GB RAM
- `t3.xlarge` = 16GB RAM
- `t3.2xlarge` = 32GB RAM
- `t3.4xlarge` = 64GB RAM

---

## 💡 Code Generation Guidelines

### Golden Rule: **Security features should be DEFAULT, not optional!**

### Resource-Specific Requirements:

1. **S3 Buckets** → 4 resources: Bucket + Encryption + Public Access Block + Versioning
2. **Lambda Functions** → 3 resources: IAM Role + Function (with tracing) + Permission
3. **DynamoDB Tables** → Table with encryption + PITR enabled
4. **EC2 Instances** → Instance with encrypted EBS + no public IP + secure metadata + security group
5. **RDS Databases** → DB with encryption + no public access + backups (7 days min)
6. **IAM Policies** → Least privilege + no wildcards + specific actions/resources

### File Organization:

- **provider.tf**: AWS provider configuration
- **main.tf**: ALL application resources with security configurations

---

## 📚 References

- Full tfsec AWS checks: https://aquasecurity.github.io/tfsec/latest/checks/aws/
- tfsec GitHub: https://github.com/aquasecurity/tfsec
- AWS Security Best Practices: https://docs.aws.amazon.com/security/
