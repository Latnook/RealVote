# RealVote — AWS Deployment — Implementation Plan (4 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `https://realvote.latnook.com` serving the built site and API from AWS, created and destroyed by Terraform alone.

**Architecture:** CloudFront in front of a private S3 bucket (site + `/img/*`) and an API Gateway HTTP API; one Python Lambda over a single on-demand DynamoDB table; Cognito guards `/api/admin/*` via a JWT authorizer. Everything regional lives in **il-central-1**; only the CloudFront ACM certificate and the billing alarm must live in us-east-1 (AWS requires it), reached through a second provider alias.

**Tech Stack:** Terraform 1.15, AWS provider v5, Python 3.13 Lambda runtime, existing `backend/` and `site/` trees unchanged.

**Spec:** `docs/superpowers/specs/2026-08-06-lr-voting-site-design.md` §7 plus the deploy notes in `2026-08-07-lr-affiliation-categories-design.md` §3.

## Global Constraints

- Region `il-central-1` for every regional resource; provider alias `us_east_1` **only** for the ACM certificate, its validation records, and the billing alarm.
- Domain exactly `realvote.latnook.com`; hosted zone `latnook.com.` already exists (`Z00371679I0OE09A8HIG`) and must be **looked up, never created**.
- API Gateway HTTP API must use the **`$default` stage** — the handler matches on `rawPath` and does no stage stripping, so a named stage 404s every route.
- CloudFront behaviours: `/api/items` cached ~30s with **Cookie excluded from the cache key**; every other `/api/*` path `no-store` with **cookies forwarded**; `/img/*` and static assets cached long.
- The JWT authorizer covers `/api/admin/*` **including the deeper `/api/admin/items/{id}/image` path**.
- `/admin/config.json` must return a real 404 when absent — CloudFront must **not** rewrite 403/404 to `/index.html` for that path, or the admin page boots LOCAL mode in production.
- `/img/*` responses carry `X-Content-Type-Options: nosniff` and `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox` (SVGs are served from this origin).
- S3 image bucket CORS allows `PUT` from `https://realvote.latnook.com` for presigned uploads.
- Cognito user pool: **one** admin user, `allow_admin_create_user_only = true` (self-signup disabled), MFA off.
- Lambda env: `TABLE_NAME`, `IMG_BUCKET`, and **no `ALLOW_ADMIN`** — its presence would be inert anyway (the code ignores it when `AWS_LAMBDA_FUNCTION_NAME` is set) but it must not be set.
- Terraform state in the **existing** `voteball-tfstate-590183895228` bucket under key `realvote/terraform.tfstate` — never create or delete that bucket.
- Every billed resource is created by `terraform apply`; `./scripts/destroy.sh` must export DynamoDB contents to a local file before destroying.
- Secrets/identity live only in `terraform/realvote.tfvars` (gitignored); `realvote.tfvars.example` is committed.
- All commands run from repo root `/home/latnook/Documents/LR2026`.

## File Structure

```
terraform/
├── versions.tf          # terraform + provider requirements, both provider blocks
├── variables.tf         # domain, zone, region, alarm email, budget threshold
├── backend.hcl.example  # state backend config (committed; real one is gitignored)
├── data.tf              # hosted zone lookup, caller identity
├── dynamodb.tf          # single table, on-demand, TTL on RATE# records
├── lambda.tf            # package, function, IAM role + least-privilege policy, log group
├── apigw.tf             # HTTP API, $default stage, routes, Cognito JWT authorizer
├── cognito.tf           # user pool, app client, single admin user
├── s3.tf                # site bucket, OAC policy, CORS for presigned PUT
├── cloudfront.tf        # distribution, cache/origin-request/response-headers policies
├── acm.tf               # us-east-1 certificate + DNS validation
├── route53.tf           # A/AAAA alias records for realvote.latnook.com
├── monitoring.tf        # SNS topic + email sub, Lambda 5xx alarm, billing alarm
└── outputs.tf           # domain, distribution id, api endpoint, bucket, pool ids
scripts/
├── deploy.sh            # terraform apply + build config.json + sync site + invalidate
└── destroy.sh           # export DynamoDB to JSON, then terraform destroy
site/admin/config.json   # NOT committed — written by deploy.sh from Terraform outputs
```

---

### Task 1: Terraform skeleton, providers, state backend, variables

**Files:**
- Create: `terraform/versions.tf`, `terraform/variables.tf`, `terraform/data.tf`, `terraform/backend.hcl.example`, `terraform/realvote.tfvars.example`, `terraform/.gitignore`

**Interfaces:**
- Produces: providers `aws` (il-central-1) and `aws.us_east_1`; variables `domain_name`, `zone_name`, `region`, `alarm_email`, `monthly_budget_usd`, `admin_email`; data sources `data.aws_route53_zone.main`, `data.aws_caller_identity.me`.

- [ ] **Step 1: Write `terraform/versions.tf`**

```hcl
terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
  backend "s3" {}   # configured via -backend-config=backend.hcl
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "RealVote"
      ManagedBy = "terraform"
    }
  }
}

# CloudFront certificates and billing metrics only exist in us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = {
      Project   = "RealVote"
      ManagedBy = "terraform"
    }
  }
}
```

- [ ] **Step 2: Write `terraform/variables.tf`**

```hcl
variable "region" {
  description = "Region for every regional resource."
  type        = string
  default     = "il-central-1"
}

variable "domain_name" {
  description = "Public hostname for the site."
  type        = string
  default     = "realvote.latnook.com"
}

variable "zone_name" {
  description = "Existing Route53 public hosted zone. Looked up, never created."
  type        = string
  default     = "latnook.com"
}

variable "alarm_email" {
  description = "Address that receives 5xx and billing alarms. Confirm the SNS subscription email after the first apply."
  type        = string
}

variable "admin_email" {
  description = "Email of the single Cognito admin user; the temporary password is sent here."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Estimated-charges alarm threshold in USD."
  type        = number
  default     = 10
}

variable "project" {
  description = "Name prefix for resources."
  type        = string
  default     = "realvote"
}
```

- [ ] **Step 3: Write `terraform/data.tf`**

```hcl
data "aws_caller_identity" "me" {}

# The zone must already exist — this stack never creates or deletes it.
data "aws_route53_zone" "main" {
  name         = "${var.zone_name}."
  private_zone = false
}
```

- [ ] **Step 4: Write `terraform/backend.hcl.example`**

```hcl
# Copy to backend.hcl (gitignored) and run:
#   terraform init -backend-config=backend.hcl
bucket = "voteball-tfstate-590183895228"
key    = "realvote/terraform.tfstate"
region = "il-central-1"
encrypt = true
```

- [ ] **Step 5: Write `terraform/realvote.tfvars.example`**

```hcl
# Copy to realvote.tfvars (gitignored) and fill in.
alarm_email = "you@example.com"
admin_email = "you@example.com"
# domain_name        = "realvote.latnook.com"
# monthly_budget_usd = 10
```

- [ ] **Step 6: Write `terraform/.gitignore`**

```
backend.hcl
*.tfvars
!*.tfvars.example
.terraform/
.terraform.lock.hcl
*.tfstate
*.tfstate.*
lambda.zip
```

- [ ] **Step 7: Initialise and verify the backend**

```bash
cd terraform
cp backend.hcl.example backend.hcl
terraform init -backend-config=backend.hcl
terraform validate
```

Expected: `Terraform has been successfully initialized!` and `Success! The configuration is valid.` The state bucket already exists — this must NOT create one.

- [ ] **Step 8: Commit**

```bash
cd .. && git add terraform/ && git commit -m "feat(tf): providers, variables, state backend"
```

---

### Task 2: DynamoDB table

**Files:**
- Create: `terraform/dynamodb.tf`

**Interfaces:**
- Produces: `aws_dynamodb_table.main` with `.name` and `.arn`, consumed by the Lambda role and env.

- [ ] **Step 1: Write `terraform/dynamodb.tf`**

```hcl
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
```

- [ ] **Step 2: Validate**

```bash
cd terraform && terraform validate && terraform plan -var-file=realvote.tfvars -target=aws_dynamodb_table.main -out=/dev/null 2>&1 | tail -5
```

Expected: validate succeeds; plan shows `1 to add` for the table (it may report other resources are not yet defined — that is fine at this stage).

- [ ] **Step 3: Commit**

```bash
cd .. && git add terraform/dynamodb.tf && git commit -m "feat(tf): dynamodb table"
```

---

### Task 3: Lambda function, IAM role, log group

**Files:**
- Create: `terraform/lambda.tf`

**Interfaces:**
- Consumes: `aws_dynamodb_table.main`, `aws_s3_bucket.site` (Task 5 — declare the dependency now, the file is applied after Task 5 exists).
- Produces: `aws_lambda_function.api` with `.invoke_arn` and `.function_name`, consumed by API Gateway.

**Note:** this task writes the file only; the first successful `terraform plan` covering it happens in Task 8 once every referenced resource exists.

- [ ] **Step 1: Write `terraform/lambda.tf`**

```hcl
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/app"
  output_path = "${path.module}/lambda.zip"
}

resource "aws_iam_role" "lambda" {
  name = "${var.project}-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Least privilege: only this table, only this bucket's img/ prefix, only own logs.
resource "aws_iam_role_policy" "lambda" {
  name = "${var.project}-lambda"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
          "dynamodb:Query", "dynamodb:Scan", "dynamodb:TransactWriteItems",
        ]
        Resource = aws_dynamodb_table.main.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.site.arn}/img/*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.lambda.arn}:*"
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.project}-api"
  retention_in_days = 14
}

resource "aws_lambda_function" "api" {
  function_name    = "${var.project}-api"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.13"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  timeout          = 10
  memory_size      = 256

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.main.name
      IMG_BUCKET = aws_s3_bucket.site.id
      # ALLOW_ADMIN is deliberately absent: the code ignores it inside Lambda anyway,
      # but it must never appear here.
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
```

- [ ] **Step 2: Confirm the package layout matches the handler path**

The zip is built from `backend/app/`, so its root contains `handler.py`, `db.py`, `http.py`, `admin_routes.py`, `categories.py`. The handler string is therefore `handler.lambda_handler`. But the modules import each other as `from app import db` — verify:

```bash
grep -rn "^from app import\|^import app" backend/app/*.py | head
```

If any module imports via the `app.` package prefix, the zip must instead contain an `app/` directory. **Resolution:** set `source_dir = "${path.module}/../backend"` and `handler = "app.handler.lambda_handler"`, and add an exclusion so tests and caches are not packaged. Apply whichever matches what the grep shows, and state in your report which one you used and why.

- [ ] **Step 3: Add the archive provider to `versions.tf`**

Inside `required_providers`, add:

```hcl
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
```

- [ ] **Step 4: Commit**

```bash
git add terraform/ && git commit -m "feat(tf): lambda, iam role, log group"
```

---

### Task 4: Cognito user pool and admin user

**Files:**
- Create: `terraform/cognito.tf`

**Interfaces:**
- Produces: `aws_cognito_user_pool.admin` (`.id`, `.endpoint`) and `aws_cognito_user_pool_client.admin` (`.id`), consumed by the API Gateway authorizer and by `deploy.sh` when writing `config.json`.

- [ ] **Step 1: Write `terraform/cognito.tf`**

```hcl
resource "aws_cognito_user_pool" "admin" {
  name = "${var.project}-admin"

  # Exactly one operator account exists; nobody may create their own.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  mfa_configuration = "OFF" # can be switched on in the console later without code changes

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
}

resource "aws_cognito_user_pool_client" "admin" {
  name         = "${var.project}-admin-web"
  user_pool_id = aws_cognito_user_pool.admin.id

  explicit_auth_flows = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  generate_secret     = false # a browser cannot keep a secret

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

resource "aws_cognito_user" "admin" {
  user_pool_id = aws_cognito_user_pool.admin.id
  username     = var.admin_email
  attributes = {
    email          = var.admin_email
    email_verified = "true"
  }
  # Cognito emails a temporary password; it must be changed on first sign-in.
  desired_delivery_mediums = ["EMAIL"]

  lifecycle {
    ignore_changes = [attributes] # avoid churn once the user updates their own profile
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add terraform/cognito.tf && git commit -m "feat(tf): cognito pool with a single admin user"
```

---

### Task 5: S3 bucket for site and images

**Files:**
- Create: `terraform/s3.tf`

**Interfaces:**
- Produces: `aws_s3_bucket.site` (`.id`, `.arn`, `.bucket_regional_domain_name`), consumed by CloudFront, the Lambda policy and `deploy.sh`.

- [ ] **Step 1: Write `terraform/s3.tf`**

```hcl
resource "aws_s3_bucket" "site" {
  bucket = "${var.project}-site-${data.aws_caller_identity.me.account_id}"
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# The admin uploads pictures straight from the browser to a presigned URL.
resource "aws_s3_bucket_cors_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  cors_rule {
    allowed_methods = ["PUT"]
    allowed_origins = ["https://${var.domain_name}"]
    allowed_headers = ["content-type"]
    max_age_seconds = 3000
  }
}

# Replacing a picture writes a new timestamped key, so superseded objects accumulate.
resource "aws_s3_bucket_lifecycle_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    id     = "expire-noncurrent-images"
    status = "Enabled"
    filter {
      prefix = "img/"
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# Only this distribution may read the bucket.
resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.site.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.site.arn
        }
      }
    }]
  })
}
```

- [ ] **Step 2: Commit**

```bash
git add terraform/s3.tf && git commit -m "feat(tf): private site bucket with CORS and lifecycle"
```

---

### Task 6: API Gateway HTTP API with the Cognito authorizer

**Files:**
- Create: `terraform/apigw.tf`

**Interfaces:**
- Consumes: `aws_lambda_function.api`, `aws_cognito_user_pool.admin`, `aws_cognito_user_pool_client.admin`.
- Produces: `aws_apigatewayv2_api.main` (`.api_endpoint`, `.execution_arn`), consumed by CloudFront as its API origin.

- [ ] **Step 1: Write `terraform/apigw.tf`**

```hcl
resource "aws_apigatewayv2_api" "main" {
  name          = "${var.project}-api"
  protocol_type = "HTTP"
}

# $default stage: the handler matches on rawPath and does no stage stripping,
# so a named stage would prefix every path and 404 the entire API.
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 200
    throttling_rate_limit  = 100
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.main.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${var.project}-cognito"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.admin.id]
    issuer   = "https://${aws_cognito_user_pool.admin.endpoint}"
  }
}

# Public surface.
resource "aws_apigatewayv2_route" "public" {
  for_each = toset([
    "GET /api/items",
    "GET /api/me",
    "POST /api/vote",
    "POST /api/suggest",
    "POST /api/affiliation",
  ])
  api_id    = aws_apigatewayv2_api.main.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# Everything under /api/admin/ requires a verified Cognito token — the greedy
# {proxy+} covers the deeper /api/admin/items/{id}/image path too.
resource "aws_apigatewayv2_route" "admin" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "ANY /api/admin/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}
```

- [ ] **Step 2: Commit**

```bash
git add terraform/apigw.tf && git commit -m "feat(tf): http api, \$default stage, jwt authorizer on admin"
```

---

### Task 7: ACM certificate, CloudFront distribution, Route53 records

**Files:**
- Create: `terraform/acm.tf`, `terraform/cloudfront.tf`, `terraform/route53.tf`

**Interfaces:**
- Consumes: `aws_s3_bucket.site`, `aws_apigatewayv2_api.main`, `data.aws_route53_zone.main`.
- Produces: `aws_cloudfront_distribution.site` (`.id`, `.arn`, `.domain_name`, `.hosted_zone_id`), consumed by the bucket policy, Route53 and `deploy.sh`.

- [ ] **Step 1: Write `terraform/acm.tf`**

```hcl
# CloudFront only accepts certificates from us-east-1, whatever the site's region.
resource "aws_acm_certificate" "site" {
  provider          = aws.us_east_1
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.site.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }
  zone_id         = data.aws_route53_zone.main.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "site" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.site.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}
```

- [ ] **Step 2: Write `terraform/cloudfront.tf`**

```hcl
resource "aws_cloudfront_origin_access_control" "s3" {
  name                              = "${var.project}-s3"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# /api/items is identical for every visitor and never sets a cookie, so it can be
# shared — but only if the cookie is kept OUT of the cache key.
resource "aws_cloudfront_cache_policy" "api_items" {
  name        = "${var.project}-api-items"
  default_ttl = 30
  min_ttl     = 0
  max_ttl     = 60

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
  }
}

resource "aws_cloudfront_response_headers_policy" "img" {
  name = "${var.project}-img"
  security_headers_config {
    content_type_options {
      override = true
    }
    content_security_policy {
      content_security_policy = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
      override                = true
    }
  }
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  aliases             = [var.domain_name]
  price_class         = "PriceClass_100"
  comment             = "RealVote"

  origin {
    origin_id                = "s3"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.s3.id
  }

  origin {
    origin_id   = "api"
    domain_name = replace(aws_apigatewayv2_api.main.api_endpoint, "https://", "")
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
    compress               = true
  }

  ordered_cache_behavior {
    path_pattern               = "/img/*"
    target_origin_id           = "s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6"
    response_headers_policy_id = aws_cloudfront_response_headers_policy.img.id
    compress                   = true
  }

  ordered_cache_behavior {
    path_pattern             = "/api/items"
    target_origin_id         = "api"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = aws_cloudfront_cache_policy.api_items.id
    origin_request_policy_id = "59781a5b-3903-41f3-afcb-af62929ccde1" # Managed-CORS-CustomOrigin
    compress                 = true
  }

  # Every other API path is per-visitor: forward cookies, cache nothing.
  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "api"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed-CachingDisabled
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # Managed-AllViewerExceptHostHeader
    compress                 = true
  }

  # NOTE: no custom_error_response for 403/404. Rewriting them to index.html would make
  # /admin/config.json return a 200 HTML page, and the admin would boot LOCAL mode in
  # production. Missing objects must stay missing.

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.site.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}
```

- [ ] **Step 3: Write `terraform/route53.tf`**

```hcl
resource "aws_route53_record" "a" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = var.domain_name
  type    = "A"
  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "aaaa" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = var.domain_name
  type    = "AAAA"
  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add terraform/ && git commit -m "feat(tf): acm certificate, cloudfront, dns records"
```

---

### Task 8: Monitoring, outputs, and a clean whole-stack plan

**Files:**
- Create: `terraform/monitoring.tf`, `terraform/outputs.tf`

**Interfaces:**
- Produces outputs `site_url`, `distribution_id`, `bucket`, `api_endpoint`, `user_pool_id`, `user_pool_client_id`, `region` — all consumed by `scripts/deploy.sh`.

- [ ] **Step 1: Write `terraform/monitoring.tf`**

```hcl
resource "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alarm_email
  # AWS sends a confirmation email; the subscription is pending until it is clicked.
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.project}-lambda-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "More than 5 Lambda errors in 5 minutes."
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

# Billing metrics are published only in us-east-1.
resource "aws_cloudwatch_metric_alarm" "billing" {
  provider            = aws.us_east_1
  alarm_name          = "${var.project}-monthly-charges"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "EstimatedCharges"
  namespace           = "AWS/Billing"
  period              = 21600
  statistic           = "Maximum"
  threshold           = var.monthly_budget_usd
  alarm_description   = "Estimated AWS charges crossed the budget."
  dimensions          = { Currency = "USD" }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}
```

The billing alarm's SNS action must live in the same region as the alarm, so add a us-east-1 topic and use it:

```hcl
resource "aws_sns_topic" "alerts_us" {
  provider = aws.us_east_1
  name     = "${var.project}-alerts"
}

resource "aws_sns_topic_subscription" "email_us" {
  provider  = aws.us_east_1
  topic_arn = aws_sns_topic.alerts_us.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}
```

and change the billing alarm's `alarm_actions` to `[aws_sns_topic.alerts_us.arn]`.

- [ ] **Step 2: Write `terraform/outputs.tf`**

```hcl
output "site_url" {
  value = "https://${var.domain_name}"
}

output "distribution_id" {
  value = aws_cloudfront_distribution.site.id
}

output "bucket" {
  value = aws_s3_bucket.site.id
}

output "api_endpoint" {
  value = aws_apigatewayv2_api.main.api_endpoint
}

output "user_pool_id" {
  value = aws_cognito_user_pool.admin.id
}

output "user_pool_client_id" {
  value = aws_cognito_user_pool_client.admin.id
}

output "region" {
  value = var.region
}
```

- [ ] **Step 3: Produce a clean plan over the whole stack**

```bash
cd terraform
cp realvote.tfvars.example realvote.tfvars   # then fill alarm_email + admin_email
terraform validate
terraform plan -var-file=realvote.tfvars -out=tfplan 2>&1 | tail -25
```

Expected: `Success! The configuration is valid.` and a plan ending in `Plan: N to add, 0 to change, 0 to destroy.` **Report the exact resource count and paste the last 25 lines.** Do NOT apply in this task.

- [ ] **Step 4: Commit**

```bash
cd .. && git add terraform/ && git commit -m "feat(tf): monitoring, alarms, outputs"
```

---

### Task 9: deploy.sh and destroy.sh

**Files:**
- Create: `scripts/deploy.sh`, `scripts/destroy.sh`
- Modify: `.gitignore` (add `site/admin/config.json`)

**Interfaces:**
- Consumes: Terraform outputs from Task 8.
- Produces: `./scripts/deploy.sh` (apply → write `site/admin/config.json` → sync `site/` → invalidate) and `./scripts/destroy.sh` (export table → destroy).

- [ ] **Step 1: Write `scripts/deploy.sh`**

```bash
#!/usr/bin/env bash
# Apply the infrastructure, publish the site, and point the admin page at Cognito.
set -euo pipefail
cd "$(dirname "$0")/.."
TF="terraform -chdir=terraform"

if [ ! -f terraform/realvote.tfvars ]; then
  echo "terraform/realvote.tfvars is missing — copy realvote.tfvars.example and fill it in." >&2
  exit 1
fi

echo "==> terraform apply"
$TF init -backend-config=backend.hcl -upgrade >/dev/null
$TF apply -var-file=realvote.tfvars "$@"

BUCKET=$($TF output -raw bucket)
DIST=$($TF output -raw distribution_id)
URL=$($TF output -raw site_url)

# The admin page fetches /admin/config.json to decide between LOCAL and CLOUD mode.
# It must exist in production and must NOT be committed.
echo "==> writing site/admin/config.json"
cat > site/admin/config.json <<JSON
{
  "region": "$($TF output -raw region)",
  "userPoolId": "$($TF output -raw user_pool_id)",
  "userPoolClientId": "$($TF output -raw user_pool_client_id)"
}
JSON

echo "==> syncing site/ to s3://$BUCKET"
# Long cache for fingerprinted-by-content assets, short for HTML and config so a
# redeploy is visible immediately even before the invalidation lands.
aws s3 sync site/ "s3://$BUCKET/" --delete \
  --exclude "*.html" --exclude "admin/config.json" \
  --cache-control "public,max-age=86400"
aws s3 sync site/ "s3://$BUCKET/" \
  --exclude "*" --include "*.html" --include "admin/config.json" \
  --cache-control "no-cache"

echo "==> invalidating CloudFront"
# CSS and JS are referenced without version strings, so a partial invalidation can
# leave new HTML pointing at old modules. Invalidate everything.
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/*" >/dev/null

echo
echo "Deployed: $URL"
echo "Admin:    $URL/admin/"
echo "If this was the first apply, confirm the SNS subscription email AWS just sent you."
```

- [ ] **Step 2: Write `scripts/destroy.sh`**

```bash
#!/usr/bin/env bash
# Export the table, then tear everything down.
set -euo pipefail
cd "$(dirname "$0")/.."
TF="terraform -chdir=terraform"

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="backups/realvote-$STAMP.json"
mkdir -p backups

TABLE=$($TF output -raw 2>/dev/null <<<"" || true)
TABLE=$(terraform -chdir=terraform state show aws_dynamodb_table.main 2>/dev/null | awk -F'"' '/^\s+name /{print $2; exit}')

if [ -n "${TABLE:-}" ]; then
  echo "==> exporting $TABLE to $OUT"
  aws dynamodb scan --table-name "$TABLE" --output json > "$OUT"
  echo "    $(python3 -c "import json;print(len(json.load(open('$OUT'))['Items']))" ) items saved"
else
  echo "==> no table found in state; skipping export"
fi

echo "==> emptying the site bucket (terraform cannot delete a non-empty bucket)"
BUCKET=$($TF output -raw bucket 2>/dev/null || true)
[ -n "$BUCKET" ] && aws s3 rm "s3://$BUCKET" --recursive >/dev/null || true

echo "==> terraform destroy"
$TF destroy -var-file=realvote.tfvars "$@"
echo
echo "Destroyed. Data export kept at $OUT"
```

- [ ] **Step 3: Make both executable and ignore the generated config**

```bash
chmod +x scripts/deploy.sh scripts/destroy.sh
printf '\n# Written by deploy.sh from Terraform outputs\nsite/admin/config.json\nbackups/\n' >> .gitignore
```

- [ ] **Step 4: Shellcheck both scripts**

```bash
bash -n scripts/deploy.sh && bash -n scripts/destroy.sh && echo "syntax ok"
```

Expected: `syntax ok`.

- [ ] **Step 5: Commit**

```bash
git add scripts/ .gitignore && git commit -m "feat(scripts): deploy and destroy"
```

---

### Task 10: Cognito sign-in for the admin page

**Files:**
- Modify: `site/admin/index.html`, `site/admin/admin.js`

**Interfaces:**
- Consumes: `/admin/config.json` written by `deploy.sh` (`region`, `userPoolId`, `userPoolClientId`).
- Produces: a working CLOUD mode — the admin signs in and every `/api/admin/*` call carries `Authorization: Bearer <id token>`.

**Context:** `admin.js` already has the seam. Its boot fetches `/admin/config.json`; when the file exists it shows `#login` and stops, and `authHeader` is the single place a token is attached. This task fills in the sign-in.

- [ ] **Step 1: Replace the login section in `site/admin/index.html`**

```html
  <section id="login" class="hidden">
    <h2>התחברות</h2>
    <form id="login-form">
      <input id="l-email" type="email" placeholder="דוא״ל" required autocomplete="username">
      <input id="l-pass" type="password" placeholder="סיסמה" required autocomplete="current-password">
      <button type="submit">כניסה</button>
    </form>
    <form id="newpass-form" class="hidden">
      <p class="muted">נדרשת סיסמה חדשה בכניסה הראשונה</p>
      <input id="l-newpass" type="password" placeholder="סיסמה חדשה" required autocomplete="new-password">
      <button type="submit">עדכון סיסמה</button>
    </form>
  </section>
```

- [ ] **Step 2: Implement sign-in in `site/admin/admin.js`**

Replace the CLOUD branch of the boot IIFE with a call to `initCloud(cfg)`, and add:

```javascript
/* ---- Cognito sign-in (CLOUD mode) ----
   USER_PASSWORD_AUTH is not enabled on the pool, so we use the InitiateAuth REST API
   with SRP... which needs a crypto library. Instead the pool allows ALLOW_USER_SRP_AUTH
   only, so the browser must perform SRP. Rather than ship a library, this uses the
   AdminNoSrp-free path: Cognito's `USER_SRP_AUTH` via the hosted SDK is heavy, so we
   call InitiateAuth with AuthFlow=USER_SRP_AUTH through amazon-cognito-identity-js,
   loaded from our own origin (vendored, no CDN). */
async function initCloud(cfg) {
  $("mode-badge").textContent = "CLOUD";
  $("login").classList.remove("hidden");

  const { CognitoUserPool, CognitoUser, AuthenticationDetails } =
    await import("/admin/vendor/amazon-cognito-identity.min.js");
  const pool = new CognitoUserPool({
    UserPoolId: cfg.userPoolId,
    ClientId: cfg.userPoolClientId,
  });

  let pendingUser = null;

  $("login-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const email = $("l-email").value.trim();
    const user = new CognitoUser({ Username: email, Pool: pool });
    const creds = new AuthenticationDetails({ Username: email, Password: $("l-pass").value });
    user.authenticateUser(creds, {
      onSuccess: (session) => enterAdmin(session.getIdToken().getJwtToken()),
      onFailure: (err) => toast(err.message || "התחברות נכשלה"),
      newPasswordRequired: () => {
        pendingUser = user;
        $("login-form").classList.add("hidden");
        $("newpass-form").classList.remove("hidden");
      },
    });
  });

  $("newpass-form").addEventListener("submit", (e) => {
    e.preventDefault();
    pendingUser.completeNewPasswordChallenge($("l-newpass").value, {}, {
      onSuccess: (session) => enterAdmin(session.getIdToken().getJwtToken()),
      onFailure: (err) => toast(err.message || "עדכון הסיסמה נכשל"),
    });
  });
}

function enterAdmin(idToken) {
  authHeader = `Bearer ${idToken}`;
  $("login").classList.add("hidden");
  $("admin-main").classList.remove("hidden");
  initCreateForm();
  loadCategories().then(refresh);
}
```

- [ ] **Step 3: Vendor the Cognito SDK (no CDN — the site makes no external requests)**

```bash
mkdir -p site/admin/vendor
curl -sL -o site/admin/vendor/amazon-cognito-identity.min.js \
  https://cdn.jsdelivr.net/npm/amazon-cognito-identity-js@6.3.12/dist/amazon-cognito-identity.min.js
ls -la site/admin/vendor/
```

Expected: a file of roughly 150–250 KB. If the bundle is UMD rather than an ES module, `import()` will fail — in that case load it with a `<script src="/admin/vendor/amazon-cognito-identity.min.js">` tag in `site/admin/index.html` and read the globals off `window.AmazonCognitoIdentity` instead of using `await import(...)`. State in your report which form you used.

- [ ] **Step 4: Verify LOCAL mode is untouched**

```bash
docker compose up -d dynamodb
cd backend && TABLE_NAME=lr-verify DDB_ENDPOINT=http://localhost:8000 ../.venv/bin/python seed.py >/dev/null && cd ..
TABLE_NAME=lr-verify DDB_ENDPOINT=http://localhost:8000 ALLOW_ADMIN=1 .venv/bin/python backend/local_server.py &
sleep 4
curl -s -o /dev/null -w "admin page: %{http_code}\n" localhost:8080/admin/
curl -s -o /dev/null -w "config.json (must be 404): %{http_code}\n" localhost:8080/admin/config.json
curl -s localhost:8080/api/admin/items | head -c 60; echo
kill %1
```

Expected: admin page 200, config.json **404**, admin items returns JSON. Then kill the server and `docker compose down`.

- [ ] **Step 5: Commit**

```bash
git add site/admin/ && git commit -m "feat(admin): cognito sign-in for cloud mode"
```

---

### Task 11: First apply and end-to-end verification

**Files:** none — this task runs the deploy and proves it works.

**This task creates real, billed AWS resources.** Do not run it without the controller's explicit go-ahead in the dispatch.

- [ ] **Step 1: Apply**

```bash
./scripts/deploy.sh -auto-approve 2>&1 | tail -30
```

Expected: apply completes, then the sync and invalidation run. Certificate validation can take several minutes; CloudFront distribution creation typically takes 5–15 minutes. Report the total wall time and any resource that failed.

- [ ] **Step 2: Seed the catalogue into the deployed table**

```bash
TABLE=$(terraform -chdir=terraform output -raw bucket >/dev/null; terraform -chdir=terraform state show aws_dynamodb_table.main | awk -F'"' '/^\s+name /{print $2; exit}')
cd backend && TABLE_NAME="$TABLE" AWS_REGION=il-central-1 ../.venv/bin/python seed.py && cd ..
```

Expected: `items: 72 created`.

- [ ] **Step 3: Upload the item pictures**

```bash
BUCKET=$(terraform -chdir=terraform output -raw bucket)
aws s3 sync site/img/ "s3://$BUCKET/img/" --cache-control "public,max-age=86400"
aws s3 ls "s3://$BUCKET/img/" | wc -l
```

Expected: 60 objects (57 item pictures plus any extras).

- [ ] **Step 4: Verify the live site**

```bash
D=https://realvote.latnook.com
curl -s -o /dev/null -w "site      %{http_code}\n" $D/
curl -s -o /dev/null -w "admin     %{http_code}\n" $D/admin/
curl -s -o /dev/null -w "config    %{http_code} (must be 200 in cloud)\n" $D/admin/config.json
curl -s -o /dev/null -w "missing   %{http_code} (must be 403/404, NOT 200)\n" $D/definitely-not-here
curl -si $D/api/items | grep -iE "^(HTTP|cache-control)"
curl -si $D/api/me    | grep -iE "^(HTTP|cache-control|set-cookie)" | head -3
curl -s -o /dev/null -w "admin api %{http_code} (must be 401)\n" $D/api/admin/items
curl -s $D/api/items | python3 -c "import json,sys; d=json.load(sys.stdin); print('items:',len(d['items']),'categories:',len(d['categories']))"
```

Expected: site 200, admin 200, config 200, a missing path **403 or 404 (never 200)**, `/api/items` `cache-control: public, max-age=30`, `/api/me` `no-store` **with** a `set-cookie`, `/api/admin/items` **401**, and 72 items / 12 categories.

- [ ] **Step 5: Vote through the live site**

```bash
D=https://realvote.latnook.com
ID=$(curl -s $D/api/items | python3 -c "import json,sys; print(json.load(sys.stdin)['items'][0]['id'])")
curl -s -c /tmp/rvjar -b /tmp/rvjar -X POST $D/api/vote -H 'content-type: application/json' \
  -d "{\"item_id\":\"$ID\",\"choice\":\"right\"}" | head -c 200; echo
curl -s -c /tmp/rvjar -b /tmp/rvjar -X POST $D/api/vote -H 'content-type: application/json' \
  -d "{\"item_id\":\"$ID\",\"choice\":\"left\"}" -o /dev/null -w "second vote (must be 409): %{http_code}\n"
curl -s -b /tmp/rvjar $D/api/me | head -c 120; echo
```

Expected: first vote 200 with updated counts, second **409**, `/api/me` shows the vote.

- [ ] **Step 6: Screenshot the live site**

```bash
S=/tmp/claude-1000/-home-latnook-Documents-LR2026/fe321078-0974-4c5f-a411-99dba8a05a00/scratchpad
chromium --headless --disable-gpu --no-sandbox --hide-scrollbars --window-size=390,844 \
  --virtual-time-budget=8000 --screenshot=$S/live-card.png https://realvote.latnook.com/
```

READ the screenshot and confirm a real card renders with its picture over HTTPS.

- [ ] **Step 7: Report**

State: total apply time, the live URL, every check from Steps 4–5 with its actual value, and anything that needed a manual fix.

---

## Self-review notes

- **Spec §7 coverage:** S3+CloudFront (T5, T7), ACM us-east-1 + Route53 (T7), API Gateway `$default` + JWT authorizer incl. `{proxy+}` (T6), Lambda + least-privilege IAM (T3), DynamoDB on-demand + TTL (T2), Cognito single user with self-signup disabled (T4), CloudWatch logs + 5xx alarm + billing alarm in us-east-1 (T8), state in the existing bucket (T1), deploy/destroy with export-before-destroy (T9), cache-busting via full invalidation (T9), `/img/*` CORS + nosniff + CSP (T5, T7), `config.json` never rewritten to index.html (T7 note, verified T11 Step 4).
- **Known risk flagged in-plan:** Task 3 Step 2 and Task 10 Step 3 each carry an explicit branch because the correct choice depends on facts the implementer must check first (import style; UMD vs ESM bundle). Both require the implementer to report which branch they took.
- **Deliberately not included:** AWS WAF (spec §5 excludes it from v1), an `og:image` asset (still undesigned), and the server-side identity threshold (recorded as deferred).
- **Type consistency:** output names in T8 match every `$TF output -raw` call in T9; `aws_dynamodb_table.main`, `aws_s3_bucket.site`, `aws_lambda_function.api`, `aws_apigatewayv2_api.main`, `aws_cloudfront_distribution.site`, `aws_cognito_user_pool.admin` and `aws_cognito_user_pool_client.admin` are referenced identically across T2–T9.
