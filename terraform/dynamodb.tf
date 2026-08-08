resource "aws_dynamodb_table" "main" {
  name         = var.project
  billing_mode = "PAY_PER_REQUEST" # every access pattern is a point lookup or a small scan
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }

  # RATE#<uid> records exist only to cap suggestions per UTC day; let them expire.
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  lifecycle {
    prevent_destroy = false # destroy.sh exports the table first
  }
}
