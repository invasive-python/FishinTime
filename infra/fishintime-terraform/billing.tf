resource "aws_dynamodb_table" "billing" {
  name         = "fishintime-billing"
  billing_mode = "PAY_PER_REQUEST"
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

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = local.common_tags
}

resource "aws_cognito_user_pool" "users" {
  name = "${local.name}-users"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  tags = local.common_tags
}

resource "aws_cognito_user_pool_client" "website" {
  name         = "${local.name}-website"
  user_pool_id = aws_cognito_user_pool.users.id

  generate_secret = false

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  callback_urls = var.cognito_callback_urls
  logout_urls   = var.cognito_logout_urls

  explicit_auth_flows = [
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH"
  ]

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

resource "aws_cognito_user_pool_domain" "website" {
  domain       = var.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.users.id
}

resource "aws_secretsmanager_secret" "stripe_secret_key" {
  name                    = "FishinTime_Stripe_Secret_Key"
  description             = "FishinTime Stripe API secret key"
  recovery_window_in_days = 7
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret" "stripe_webhook_secret" {
  name                    = "FishinTime_Stripe_Webhook_Secret"
  description             = "FishinTime Stripe webhook signing secret"
  recovery_window_in_days = 7
  tags                    = local.common_tags
}

resource "aws_iam_role_policy" "task_billing_table" {
  name = "${local.name}-billing-table"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:TransactWriteItems"
      ]
      Resource = aws_dynamodb_table.billing.arn
    }]
  })
}

resource "aws_iam_role_policy" "execution_read_stripe_secrets" {
  name = "${local.name}-read-stripe-secrets"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        aws_secretsmanager_secret.stripe_secret_key.arn,
        aws_secretsmanager_secret.stripe_webhook_secret.arn
      ]
    }]
  })
}

output "billing_table_name" {
  value = aws_dynamodb_table.billing.name
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.users.id
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.website.id
}

output "cognito_issuer" {
  value = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.users.id}"
}

output "cognito_login_domain" {
  value = "https://${aws_cognito_user_pool_domain.website.domain}.auth.${var.aws_region}.amazoncognito.com"
}