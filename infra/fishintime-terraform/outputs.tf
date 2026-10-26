output "aws_region" {
  value = var.aws_region
}

output "account_id" {
  value = data.aws_caller_identity.current.account_id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "load_balancer_url" {
  value = "http://${aws_lb.main.dns_name}"
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  value = aws_ecs_service.backend.name
}

output "task_definition_family" {
  value = aws_ecs_task_definition.backend.family
}

output "openai_secret_name" {
  value = aws_secretsmanager_secret.openai.name
}

output "agent_id_secret_name" {
  value = aws_secretsmanager_secret.agent_id.name
}

output "target_group_arn" {
  value = aws_lb_target_group.backend.arn
}
