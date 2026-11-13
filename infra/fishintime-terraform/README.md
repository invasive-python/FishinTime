# FishinTime AWS infrastructure (Terraform)

This configuration deploys the FastAPI application to Amazon ECS Express Mode
in `us-east-2`:

- ECS Express service using Fargate and the existing `fishintime-backend` ECR
  repository.
- Express-managed Application Load Balancer, listeners, target group, task
  security groups, scaling, and service infrastructure.
- A VPC with two public subnets so the application can reach external APIs.
- Separate ECS execution, infrastructure, and application task roles.
- CloudWatch logging, Secrets Manager access, Cognito, and billing resources.

The container listens on port 8000 and exposes `/health`. The minimum and
maximum task counts both default to one to preserve the previous capacity;
increase `max_task_count` only after deciding on the desired scaling and cost
limits.

## Migration notes

- ECS Express Mode is not the former standalone ECS service/ALB configuration.
  Express provisions and manages its own ALB and related resources; do not
  declare a second Terraform-managed ALB for this service.
- The Express Terraform resource does not configure custom domains or expose
  the generated ALB DNS name. `express_domains.tf` manages the ACM certificate,
  DNS validation records, HTTPS listener certificate association, host-header
  rule, and Route 53 alias records. Import blocks adopt the existing resources
  on the first apply. Follow the
  [AWS custom-domain procedure](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-advanced-customization.html).
- The active Terraform state currently contains App Runner-specific IAM
  resources. A plan may remove those roles and policies and create the ECS
  Express roles/service. Review every proposed deletion and replacement before
  applying; do not restore or apply an old state backup as part of this change.
- The VPC uses `10.40.0.0/16`, matching the original ECS configuration. Confirm
  this range does not overlap with networks you need to connect.
- The configuration does not create secret values. Keep the existing
  application secrets populated in Secrets Manager.

## 1. Verify account and initialize Terraform

The AWS provider uses the temporary `fishintime-nonroot` profile and account
`757266935832`. Confirm the identity and set the service Region:

```bash
aws sts get-caller-identity --profile fishintime-nonroot
export AWS_PROFILE=fishintime-nonroot
export AWS_REGION=us-east-2
export AWS_DEFAULT_REGION=us-east-2
```

The Express listener and target-group ARNs in `variables.tf` default to the
currently deployed service. Override them if the Express-managed ALB or its
listener rule is replaced.

The ECS Express Terraform resource requires AWS provider 6.23 or later.
Initialize with the updated constraint, then format and validate:

```bash
terraform init -upgrade
terraform fmt -check
terraform validate
```

## 2. Build and push an image

Use an immutable tag for each deployment so Terraform can detect image
changes. Run from the repository root:

```bash
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
REPO="${REGISTRY}/fishintime-backend"
IMAGE_TAG="$(git rev-parse --short HEAD)"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

docker build -t "${REPO}:${IMAGE_TAG}" .
docker push "${REPO}:${IMAGE_TAG}"
```

If Docker cannot access its socket in your environment, use `sudo docker` for
the Docker commands. Set `container_image_tag` to the pushed tag when planning.

## 3. Plan the migration

The new service creates managed ECS/ALB resources. Review the full plan,
especially the App Runner IAM role removals, the new VPC, and any changes to
existing Cognito, DynamoDB, ECR, or Secrets Manager resources:

```bash
terraform plan \
  -var="container_image_tag=${IMAGE_TAG}" \
  -out fishintime.tfplan
```

Do not apply until the plan is understood and the account and Region are
correct. Applying the plan is intentionally not part of this setup.

## 4. Configure custom domains and DNS

The Express service publishes a default endpoint as the
`ecs_express_endpoint` output. Test that endpoint before cutover:

```bash
terraform output -raw ecs_express_endpoint
curl -i "$(terraform output -raw ecs_express_endpoint)/health"
```

To keep `tidalfishintime.com` and `api.tidalfishintime.com`, the certificate
request, DNS validation records, certificate association, host-header rule,
and Route 53 alias records are managed by `express_domains.tf`. Import blocks
adopt the already-configured resources on the first apply. Review the plan
before applying; it should import existing resources without changing live
traffic.

## 5. Verify the service

After an approved apply and custom-domain cutover:

```bash
aws ecs describe-express-gateway-service \
  --service-arn "$(terraform output -raw ecs_express_service_arn)" \
  --region "$AWS_REGION"

curl -i "$(terraform output -raw load_balancer_url)/health"
aws logs tail /ecs/fishintime-backend --follow --region "$AWS_REGION"
```

`load_balancer_url` is the configured application hostname; it will serve
traffic only after its listener rule, certificate, and DNS record have been
configured as described above.

The existing Terraform outputs for Cognito and DynamoDB remain available from
`billing.tf`. Use them for local development as documented in the project
README. `APP_BASE_URL` for the deployed service continues to come from
`app_base_url`.

`terraform destroy` removes the ECS Express service and its managed supporting
infrastructure. Use it only when that teardown is intentional.
