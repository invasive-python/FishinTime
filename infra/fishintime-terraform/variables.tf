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

variable "container_image_tag" {
  description = "ECR image tag to deploy. Push this tag before applying if the service is being created for the first time."
  type        = string
  default     = "latest"
}

variable "container_port" {
  type        = number
  default     = 8000
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
  description = "CIDR allowed to access the public HTTP load balancer. Use 0.0.0.0/0 for a public demo site."
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
