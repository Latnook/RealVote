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
