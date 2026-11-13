variable "aws_region" { type = string }
variable "aws_secret_name" { type = string }
variable "stripe_mode" { type = string }
variable "stripe_annual_amount_cents" { type = string }
variable "stripe_monthly_amount_cents" { type = string }
variable "billing_table_name" { type = string }
variable "billing_table_name_live" { type = string }
variable "cognito_issuer" { type = string }
variable "cognito_user_pool_id" { type = string }
variable "cognito_region" { type = string }
variable "cognito_login_domain" { type = string }
variable "cognito_client_id" { type = string }
variable "app_base_url" { type = string }
variable "project_name" { type = string }
variable "domain_name" { type = string }
variable "cognito_domain_prefix" { type = string }
variable "cognito_callback_urls" { type = list(string) }
variable "cognito_logout_urls" { type = list(string) }
variable "route53_zone_id" {
  description = "Public Route 53 hosted zone containing the custom domains."
  type        = string
  default     = "Z095566824HCVZH7AIR9D"
}

variable "express_load_balancer_name" {
  description = "Name of the ALB created by the deployed ECS Express service."
  type        = string
  default     = "ecs-express-gateway-alb-8880ca06"
}

variable "express_https_listener_arn" {
  description = "HTTPS listener ARN managed by the deployed ECS Express service."
  type        = string
  default     = "arn:aws:elasticloadbalancing:us-east-2:757266935832:listener/app/ecs-express-gateway-alb-8880ca06/9b875a09628b6e51/b6811da502b61878"
}

variable "express_custom_domain_certificate_arn" {
  description = "Issued ACM certificate ARN covering the apex and API hostnames."
  type        = string
  default     = "arn:aws:acm:us-east-2:757266935832:certificate/6a65965d-5b54-40f7-be38-72c013106d2e"
}

variable "express_listener_rule_arn" {
  description = "Existing Express listener rule to import and manage."
  type        = string
  default     = "arn:aws:elasticloadbalancing:us-east-2:757266935832:listener-rule/app/ecs-express-gateway-alb-8880ca06/9b875a09628b6e51/b6811da502b61878/dedd104d95ec9b2d"
}

variable "express_zero_weight_target_group_arn" {
  description = "Existing Express listener rule target group with weight zero."
  type        = string
  default     = "arn:aws:elasticloadbalancing:us-east-2:757266935832:targetgroup/ecs-gateway-tg-ac28266a63b7ef9f3/047da1d1376a3f5c"
}

variable "express_active_target_group_arn" {
  description = "Existing active Express listener rule target group."
  type        = string
  default     = "arn:aws:elasticloadbalancing:us-east-2:757266935832:targetgroup/ecs-gateway-tg-52d946b667364ecbb/4387585bd0d8ceaa"
}

variable "container_image_tag" {
  description = "Immutable ECR image tag deployed by ECS Express Mode."
  type        = string
  default     = "latest"
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "task_cpu" {
  description = "Fargate CPU units for the Express service."
  type        = number
  default     = 256
}

variable "task_memory" {
  description = "Fargate memory in MiB for the Express service."
  type        = number
  default     = 512
}

variable "health_check_path" {
  type    = string
  default = "/health"
}

variable "min_task_count" {
  description = "Minimum number of Express service tasks."
  type        = number
  default     = 1
}

variable "max_task_count" {
  description = "Maximum number of Express service tasks. Kept at one by default to preserve current capacity."
  type        = number
  default     = 1
}

variable "secret_openai_name" {
  type    = string
  default = "FishinSecret_OpenAI"
}

variable "secret_agent_id_name" {
  type    = string
  default = "FishinSecret_Agent_Id"
}
