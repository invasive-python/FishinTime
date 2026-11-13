output "aws_region" {
  value = var.aws_region
}

output "account_id" {
  value = data.aws_caller_identity.current.account_id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_express_gateway_service.backend.cluster
}

output "ecs_service_name" {
  value = aws_ecs_express_gateway_service.backend.service_name
}

output "ecs_express_service_arn" {
  value = aws_ecs_express_gateway_service.backend.service_arn
}

output "ecs_express_service_revision_arn" {
  value = aws_ecs_express_gateway_service.backend.service_revision_arn
}

output "ecs_express_endpoint" {
  value = one([
    for ingress_path in aws_ecs_express_gateway_service.backend.ingress_paths :
    ingress_path.endpoint
  ])
}

output "ecs_express_ingress_paths" {
  value = [
    for ingress_path in aws_ecs_express_gateway_service.backend.ingress_paths :
    ingress_path.endpoint
  ]
}

output "load_balancer_url" {
  description = "Public application hostname; configure it on the Express-managed ALB before DNS cutover."
  value       = var.app_base_url
}

output "api_load_balancer_url" {
  description = "API hostname; configure it on the Express-managed ALB before DNS cutover."
  value       = "https://${local.api_domain}"
}

output "api_domain_name" {
  value = local.api_domain
}

output "openai_secret_name" {
  value = var.secret_openai_name
}

output "agent_id_secret_name" {
  value = var.secret_agent_id_name
}
