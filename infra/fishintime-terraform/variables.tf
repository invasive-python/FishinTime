variable "aws_region" {
  description = "AWS region for the FishinTime deployment."
  type        = string
  default     = "us-east-2"
}

variable "project_name" {
  description = "Prefix used for AWS resource names."
  type        = string
  default     = "fishintime"
}

variable "domain_name" {
  description = "Registered apex domain with a public Route 53 hosted zone."
  type        = string
  default     = "tidalfishintime.com"
}

variable "route53_zone_id" {
  description = "ID of the public Route 53 hosted zone delegated by the registered domain."
  type        = string
}

variable "container_image_tag" {
  description = "ECR image tag to deploy. Push this tag before applying if the service is being created for the first time."
  type        = string
  default     = "latest"
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "task_cpu" {
  description = "Fargate CPU units."
  type        = number
  default     = 256
}

variable "task_memory" {
  description = "Fargate memory in MiB."
  type        = number
  default     = 512
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "allowed_http_cidr" {
  description = "CIDR allowed to reach the HTTP-to-HTTPS redirect listener."
  type        = string
  default     = "0.0.0.0/0"
}

variable "allowed_https_cidr" {
  description = "CIDR allowed to access the public HTTPS API."
  type        = string
  default     = "0.0.0.0/0"
}

variable "health_check_path" {
  type    = string
  default = "/health"
}

variable "secret_openai_name" {
  type    = string
  default = "FishinSecret_OpenAI"
}

variable "secret_agent_id_name" {
  type    = string
  default = "FishinSecret_Agent_Id"
}

variable "cognito_domain_prefix" {
  description = "Globally unique Cognito hosted-domain prefix."
  type        = string
}

variable "cognito_callback_urls" {
  description = "Exact allowed sign-in callback URLs."
  type        = list(string)
}

variable "cognito_logout_urls" {
  description = "Exact allowed sign-out URLs."
  type        = list(string)
}

variable "stripe_monthly_amount_cents" {
  type        = number
  description = "Monthly FishinTime subscription price in USD cents."
  default     = 99

  validation {
    condition     = var.stripe_monthly_amount_cents > 0 && floor(var.stripe_monthly_amount_cents) == var.stripe_monthly_amount_cents
    error_message = "The monthly subscription amount must be a positive whole number of cents."
  }
}

variable "stripe_annual_amount_cents" {
  type        = number
  description = "Annual FishinTime subscription price in USD cents."
  default     = 999

  validation {
    condition     = var.stripe_annual_amount_cents > 0 && floor(var.stripe_annual_amount_cents) == var.stripe_annual_amount_cents
    error_message = "The annual subscription amount must be a positive whole number of cents."
  }
}

variable "app_base_url" {
  type        = string
  description = "Public HTTPS apex URL used for the app, billing redirects, and Cognito callbacks, without a trailing slash."
  default     = "https://tidalfishintime.com"
}
