locals {
  express_hostname = trimprefix(
    one([
      for ingress_path in aws_ecs_express_gateway_service.backend.ingress_paths :
      ingress_path.endpoint
    ]),
    "https://"
  )

  acm_validation_options = {
    for option in aws_acm_certificate.custom_domains.domain_validation_options :
    option.domain_name => option
  }
}

data "aws_lb" "express" {
  name = var.express_load_balancer_name
}

resource "aws_acm_certificate" "custom_domains" {
  domain_name               = var.domain_name
  subject_alternative_names = [local.api_domain]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

import {
  to = aws_acm_certificate.custom_domains
  id = var.express_custom_domain_certificate_arn
}

resource "aws_route53_record" "acm_validation" {
  for_each = toset([var.domain_name, local.api_domain])

  zone_id = var.route53_zone_id
  name    = local.acm_validation_options[each.key].resource_record_name
  type    = local.acm_validation_options[each.key].resource_record_type
  records = [local.acm_validation_options[each.key].resource_record_value]
  ttl     = 300
}

import {
  to = aws_route53_record.acm_validation["tidalfishintime.com"]
  id = "Z095566824HCVZH7AIR9D__51f94100c128433bacc4ab9d55d0ab39.tidalfishintime.com_CNAME"
}

import {
  to = aws_route53_record.acm_validation["api.tidalfishintime.com"]
  id = "Z095566824HCVZH7AIR9D__ab77ce6c27d81394d3ad1d241b91cb0b.api.tidalfishintime.com_CNAME"
}

resource "aws_acm_certificate_validation" "custom_domains" {
  certificate_arn = aws_acm_certificate.custom_domains.arn
  validation_record_fqdns = [
    for record in aws_route53_record.acm_validation : record.fqdn
  ]
}

resource "aws_route53_record" "apex" {
  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = "dualstack.${data.aws_lb.express.dns_name}"
    zone_id                = data.aws_lb.express.zone_id
    evaluate_target_health = false
  }
}

import {
  to = aws_route53_record.apex
  id = "Z095566824HCVZH7AIR9D_tidalfishintime.com_A"
}

resource "aws_route53_record" "api" {
  zone_id = var.route53_zone_id
  name    = local.api_domain
  type    = "A"

  alias {
    name                   = "dualstack.${data.aws_lb.express.dns_name}"
    zone_id                = data.aws_lb.express.zone_id
    evaluate_target_health = false
  }
}

import {
  to = aws_route53_record.api
  id = "Z095566824HCVZH7AIR9D_api.tidalfishintime.com_A"
}

resource "aws_lb_listener_certificate" "express_custom_domains" {
  listener_arn    = var.express_https_listener_arn
  certificate_arn = aws_acm_certificate.custom_domains.arn
}

import {
  to = aws_lb_listener_certificate.express_custom_domains
  id = "${var.express_https_listener_arn}_${var.express_custom_domain_certificate_arn}"
}

resource "aws_lb_listener_rule" "express_custom_domains" {
  listener_arn = var.express_https_listener_arn
  priority     = 44990

  action {
    type = "forward"

    forward {
      target_group {
        arn    = var.express_zero_weight_target_group_arn
        weight = 0
      }

      target_group {
        arn    = var.express_active_target_group_arn
        weight = 100
      }
    }
  }

  condition {
    host_header {
      values = [
        local.express_hostname,
        var.domain_name,
        local.api_domain,
      ]
    }
  }

  tags = merge(local.common_tags, {
    AmazonECSManaged = "true"
  })
}

import {
  to = aws_lb_listener_rule.express_custom_domains
  id = var.express_listener_rule_arn
}
