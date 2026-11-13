provider "aws" {
  region              = var.aws_region
  profile             = "fishintime-nonroot"
  allowed_account_ids = ["757266935832"]
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

locals {
  name       = var.project_name
  api_domain = "api.${var.domain_name}"
  common_tags = {
    Project   = "FishinTime"
    ManagedBy = "Terraform"
  }
}

# ECS Express Mode manages its own load balancer, listener, target group, task
# security groups, service, and scaling resources.
resource "aws_vpc" "main" {
  cidr_block           = "10.40.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.common_tags, { Name = "${local.name}-vpc" })
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = merge(local.common_tags, { Name = "${local.name}-igw" })
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = count.index == 0 ? "10.40.1.0/24" : "10.40.2.0/24"
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true
  tags = merge(local.common_tags, {
    Name = "${local.name}-public-${count.index + 1}"
  })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = merge(local.common_tags, { Name = "${local.name}-public-rt" })
}

resource "aws_route" "internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_ecr_repository" "backend" {
  name                 = "${local.name}-backend"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${local.name}-backend"
  retention_in_days = 14
  tags              = local.common_tags
}

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "infrastructure" {
  name = "${local.name}-express-infrastructure-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "infrastructure_managed" {
  role       = aws_iam_role.infrastructure.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "task_read_application_secrets" {
  name = "${local.name}-read-application-secrets"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ]
      Resource = [
        "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.secret_openai_name}-*",
        "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.secret_agent_id_name}-*"
      ]
    }]
  })
}

resource "aws_ecs_express_gateway_service" "backend" {
  service_name            = "${local.name}-backend"
  execution_role_arn      = aws_iam_role.execution.arn
  infrastructure_role_arn = aws_iam_role.infrastructure.arn
  task_role_arn           = aws_iam_role.task.arn
  cpu                     = tostring(var.task_cpu)
  memory                  = tostring(var.task_memory)
  health_check_path       = var.health_check_path
  wait_for_steady_state   = true
  tags                    = local.common_tags

  network_configuration {
    subnets = aws_subnet.public[*].id
  }

  primary_container {
    image          = "${aws_ecr_repository.backend.repository_url}:${var.container_image_tag}"
    container_port = var.container_port

    aws_logs_configuration {
      log_group         = aws_cloudwatch_log_group.backend.name
      log_stream_prefix = "ecs"
    }

    environment {
      name  = "AWS_REGION"
      value = var.aws_region
    }

    environment {
      name  = "AWS_DEFAULT_REGION"
      value = var.aws_region
    }

    environment {
      name  = "AWS_SECRET_NAME"
      value = var.aws_secret_name
    }

    environment {
      name  = "STRIPE_MODE"
      value = var.stripe_mode
    }

    environment {
      name  = "STRIPE_ANNUAL_AMOUNT_CENTS"
      value = var.stripe_annual_amount_cents
    }

    environment {
      name  = "STRIPE_MONTHLY_AMOUNT_CENTS"
      value = var.stripe_monthly_amount_cents
    }

    environment {
      name  = "BILLING_TABLE_NAME"
      value = var.billing_table_name
    }

    environment {
      name  = "BILLING_TABLE_NAME_LIVE"
      value = var.billing_table_name_live
    }

    environment {
      name  = "COGNITO_ISSUER"
      value = var.cognito_issuer
    }

    environment {
      name  = "COGNITO_USER_POOL_ID"
      value = var.cognito_user_pool_id
    }

    environment {
      name  = "COGNITO_REGION"
      value = var.cognito_region
    }

    environment {
      name  = "COGNITO_LOGIN_DOMAIN"
      value = var.cognito_login_domain
    }

    environment {
      name  = "COGNITO_CLIENT_ID"
      value = var.cognito_client_id
    }

    environment {
      name  = "APP_BASE_URL"
      value = var.app_base_url
    }
  }

  scaling_target {
    auto_scaling_metric       = "AVERAGE_CPU"
    auto_scaling_target_value = 60
    min_task_count            = var.min_task_count
    max_task_count            = var.max_task_count
  }

  depends_on = [
    aws_route.internet,
    aws_route_table_association.public,
    aws_iam_role_policy_attachment.execution_managed,
    aws_iam_role_policy_attachment.infrastructure_managed,
    aws_iam_role_policy.task_read_application_secrets,
    aws_iam_role_policy.task_billing_table,
    aws_iam_role_policy.task_read_stripe_secrets,
  ]
}
