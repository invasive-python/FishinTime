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

resource "aws_dynamodb_table" "billing_live" {
  name         = "${local.name}-billing-live"
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

  schema {
    name                     = "stripe_customer_id"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = false
    string_attribute_constraints {}
  }

  schema {
    name                     = "subscription_status"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = false
    string_attribute_constraints {}
  }

  schema {
    name                     = "subscription_tier"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = false
    string_attribute_constraints {}
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  tags = local.common_tags
}

resource "aws_cognito_user_pool_client" "website" {
  name         = "${local.name}-website"
  user_pool_id = aws_cognito_user_pool.users.id

  generate_secret = false

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes = [
    "openid",
    "email",
    "profile",
    "aws.cognito.signin.user.admin"
  ]
  supported_identity_providers = ["COGNITO"]

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

resource "aws_cognito_user_pool_ui_customization" "website" {
  user_pool_id = aws_cognito_user_pool_domain.website.user_pool_id
  client_id    = aws_cognito_user_pool_client.website.id

  css = <<-CSS
    .background-customizable {
      background-color: #e8f4f2;
    }

    .banner-customizable {
      background-color: #ffffff;
      padding: 16px 16px 0 16px;
    }

    .label-customizable {
      color: #173b42;
      font-weight: 700;
    }

    .inputField-customizable {
      width: 100%;
      height: 44px;
      color: #173b42;
      background-color: #f1f8f6;
      border: 1px solid #c7deda;
    }

    .inputField-customizable:focus {
      border-color: #087e83;
      outline: 2px;
    }

    .submitButton-customizable {
      width: 100%;
      height: 44px;
      color: #ffffff;
      background-color: #087e83;
      font-size: 16px;
      font-weight: bold;
      margin: 16px 0 0 0;
    }

    .submitButton-customizable:hover {
      color: #ffffff;
      background-color: #05666b;
    }

    .textDescription-customizable {
      color: #56747a;
      font-size: 15px;
    }
  CSS
}

data "aws_secretsmanager_secret" "stripe_secret_key" {
  name = "FishinSecret_Stripe_API"
}

resource "aws_secretsmanager_secret" "stripe_webhook_secret" {
  name                    = "FishinTime_Stripe_Webhook_Secret"
  description             = "FishinTime Stripe webhook signing secret"
  recovery_window_in_days = 7
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret" "stripe_webhook_secret_live" {
  name                    = "FishinTime_Stripe_Webhook_Secret_Live"
  description             = "FishinTime Stripe live webhook signing secret"
  recovery_window_in_days = 7
  tags                    = local.common_tags
}

# IAM permissions used by the ECS task role.
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
      Resource = aws_dynamodb_table.billing_live.arn
    }]
  })
}

resource "aws_iam_role_policy" "task_read_stripe_secrets" {
  name = "${local.name}-read-stripe-secrets"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        data.aws_secretsmanager_secret.stripe_secret_key.arn,
        aws_secretsmanager_secret.stripe_webhook_secret_live.arn
      ]
    }]
  })
}

output "billing_table_name" {
  value = aws_dynamodb_table.billing.name
}

output "billing_live_table_name" {
  value = aws_dynamodb_table.billing_live.name
}

output "stripe_live_webhook_secret_name" {
  value = aws_secretsmanager_secret.stripe_webhook_secret_live.name
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
