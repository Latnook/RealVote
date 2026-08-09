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
