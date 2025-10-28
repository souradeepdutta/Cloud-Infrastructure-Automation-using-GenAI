resource "aws_s3_bucket" "my-minimal-bucket" {
  bucket = "my-minimal-bucket-12345"
  tags = {
    Name = "MyMinimalBucket"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "my-minimal-bucket" {
  bucket = aws_s3_bucket.my-minimal-bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "my-minimal-bucket" {
  bucket = aws_s3_bucket.my-minimal-bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "my-minimal-bucket" {
  bucket = aws_s3_bucket.my-minimal-bucket.id

  versioning_configuration {
    status = "Enabled"
  }
}