# FishinTime AWS infrastructure (Terraform)

This Terraform project reconstructs the FishinTime infrastructure from the prior deployment chats:

- Region `us-east-2` (Ohio)
- Public Application Load Balancer on HTTP port 80 (redirects to HTTPS) and HTTPS port 443
- ACM-managed public TLS certificate for `api.<domain_name>`, validated through Route 53
- Route 53 alias records for the apex application hostname and the API compatibility hostname
- ECS Fargate service with one task by default, 256 CPU / 512 MiB
- FastAPI/Uvicorn container on port 8000; ALB health check `/health`, HTTP 200
- ECR repository `fishintime-backend`
- CloudWatch log group `/ecs/fishintime-backend`
- Separate ECS execution and application task roles
- Secrets Manager secrets for OpenAI, Cognito billing, and Stripe
- Separate DynamoDB billing tables for live and sandbox Stripe customers and subscriptions

The live Stripe subscription prices are configurable with
`stripe_monthly_amount_cents` (default `99`) and
`stripe_annual_amount_cents` (default `999`). The application creates monthly
and annual recurring prices directly at Stripe Checkout from these values.
The app and Cognito callback/logout URLs use the apex hostname
`${app_base_url}/` (by default `https://tidalfishintime.com/`). The API
compatibility hostname `https://api.tidalfishintime.com` remains available for
existing integrations. Keep
`${app_base_url}/billing/account` in the lists as well for compatibility with
older sign-in links.

## Before you start

1. This creates resources in the AWS account selected by your CLI credentials. Verify the account first.
2. The OpenAI, agent ID, and Stripe webhook secret containers are created without values. Add values outside Terraform so secrets are not embedded in configuration or state.
3. OpenAI, agent ID, and live Stripe API secrets may be JSON objects with `OPENAI_API_KEY`, `AGENT_ID`, and `FishinSecret_Stripe_API_Key` fields, respectively. The live secret is named `FishinSecret_Stripe_API`; the retained sandbox secret is named `FishinSecret_Stripe_API_Key` and stores its key under the `FishinSecret_Stripe_API` field.
4. Set `route53_zone_id` to the public Route 53 hosted zone that is authoritative for the registered domain. Confirm its name servers match `dig +short NS <domain>`; ACM validation records must be created in that delegated zone.
5. Fargate tasks receive public IPs so they can call OpenAI, NOAA, and USNO without a NAT gateway. The task security group only allows inbound app traffic from the ALB.
6. If a secret name is pending deletion from a prior attempt, AWS may prevent immediate reuse. Restore it or wait until its recovery window expires.
7. Check that the selected account's organization policies allow these resources and actions.

## 1. Verify CLI identity and set region

Install the Terraform CLI for your operating system and ensure `terraform` is
available on your `PATH`. See the
[official Terraform installation instructions](https://developer.hashicorp.com/terraform/install).
Verify the installation before continuing:

```bash
terraform version
```

If this prints `terraform: command not found`, Terraform is not installed or
its executable directory is not on your `PATH`.

```bash
aws sts get-caller-identity --profile fishintime-757
export AWS_PROFILE=fishintime-757
export AWS_REGION=us-east-2
export AWS_DEFAULT_REGION=us-east-2
```

Do not proceed unless the account ID is `757266935832`. The Terraform AWS
provider is pinned to this profile and account as an additional safety check.

## 2. Initialize Terraform and create bootstrap resources

From this directory:

```bash
terraform init
terraform fmt -check
terraform validate
terraform apply -target=aws_ecr_repository.backend \
  -target=aws_secretsmanager_secret.openai \
  -target=aws_secretsmanager_secret.agent_id \
  -target=aws_secretsmanager_secret.stripe_webhook_secret
```

Terraform will warn that `-target` is for exceptional/partial operations; here it is used only to bootstrap the ECR repository and secret containers before the service is created. Use a normal full plan/apply for later changes.

## 3. Build and push the application image

Run these commands from the directory containing your Dockerfile and `api.py`:

```bash
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
REPO="${REGISTRY}/fishintime-backend"

aws ecr get-login-password --region "$AWS_REGION" \
  | sudo docker login --username AWS --password-stdin "$REGISTRY"

sudo docker build -t fishintime-backend:latest .
sudo docker tag fishintime-backend:latest "${REPO}:latest"
sudo docker push "${REPO}:latest"
```

The prior Linux environment sometimes required `sudo docker` because the user did not have permission to access `/var/run/docker.sock`.

## 4. Deploy the pushed image

Pushing the `latest` tag does not automatically replace the image used by
running ECS tasks. Force a new deployment so ECS pulls the latest image, then
wait for the service to become stable:

```bash
aws ecs update-service \
  --cluster fishintime-cluster \
  --service fishintime-backend-service \
  --force-new-deployment \
  --region "$AWS_REGION"

aws ecs wait services-stable \
  --cluster fishintime-cluster \
  --services fishintime-backend-service \
  --region "$AWS_REGION"
```

## 5. Add secret values outside Terraform

Enter each complete JSON object at its hidden prompt, not as part of the
command. The application expects the OpenAI secret to have an
`OPENAI_API_KEY` field and the agent secret to have an `AGENT_ID` field. For
example, enter `{"OPENAI_API_KEY":"your actual key"}` at the first prompt and
`{"AGENT_ID":"your actual agent ID"}` at the second. Do not enter the angle
brackets shown in this explanation. Do not commit these values or paste them
into chat.

```bash
read -rsp "OpenAI secret JSON: " OPENAI_SECRET_JSON
printf '\n'
aws secretsmanager put-secret-value \
  --secret-id FishinSecret_OpenAI \
  --secret-string "$OPENAI_SECRET_JSON" \
  --region "$AWS_REGION"
unset OPENAI_SECRET_JSON

read -rsp "Agent secret JSON: " AGENT_SECRET_JSON
printf '\n'
aws secretsmanager put-secret-value \
  --secret-id FishinSecret_Agent_Id \
  --secret-string "$AGENT_SECRET_JSON" \
  --region "$AWS_REGION"
unset AGENT_SECRET_JSON
```

The prompts do not echo what you type or put the values directly in shell
history. The AWS CLI receives each value as a command-line argument, so avoid
running this on a shared machine. AWS Secrets Manager stores the JSON object as
the secret string; the application parses the expected field from it.

The live API key is read from `FishinSecret_Stripe_API`; local `--sandbox` runs
use the retained `FishinSecret_Stripe_API_Key` secret. Stripe API keys start
with `sk_live_` or `rk_live_` in live mode and `sk_test_` or `rk_test_` in a
sandbox. A value starting with `prod_` is a Product ID, not an API key.

Terraform creates a new live webhook secret container named
`FishinTime_Stripe_Webhook_Secret_Live`; populate it with the signing secret
from the live Stripe webhook endpoint. Keep the existing
`FishinTime_Stripe_Webhook_Secret` for sandbox runs. Configure separate
endpoints in Stripe, both sending
`customer.subscription.created`, `customer.subscription.updated`, and
`customer.subscription.deleted` events to
`https://api.<domain_name>/api/billing/webhook`.

```bash
read -rsp "Live Stripe webhook signing secret: " STRIPE_WEBHOOK_SECRET
printf '\n'
aws secretsmanager put-secret-value \
  --secret-id FishinTime_Stripe_Webhook_Secret_Live \
  --secret-string "$STRIPE_WEBHOOK_SECRET" \
  --region "$AWS_REGION"
unset STRIPE_WEBHOOK_SECRET
```

In your Terraform variables, set both `cognito_callback_urls` and
`cognito_logout_urls` to include the exact `app_base_url` with a trailing `/`
and `${app_base_url}/billing/account`. For local development, also include
`http://localhost:8000/` and `http://localhost:8000/billing/account` in both
lists. Configure the Stripe amounts in cents as needed. For example, `99` is
$0.99 and `999` is $9.99.

Terraform also applies a Cognito classic hosted UI theme using FishinTime's
teal and light backgrounds. Cognito only permits a limited set of CSS
selectors and properties for this page, so it can match the app's palette and
controls but not its full layout. The classic hosted UI does not provide a
password-visibility toggle, and its CSS customization cannot add interactive
behavior. A show-password control would require replacing the hosted page with
a custom sign-in UI.

## 6. Plan and create the full stack

Confirm that the AWS CLI profile `fishintime-757` selects account
`757266935832`. The default API hostname is
`tidalfishintime.com`; override `domain_name` and `route53_zone_id` if your
registered apex domain or authoritative hosted zone differs. The Terraform
plan will add an apex A-alias to the load balancer while preserving the
`api.` alias. If an apex A record already exists outside Terraform, reconcile
that record before applying to avoid a Route 53 record conflict.

```bash
aws sts get-caller-identity --profile fishintime-757
dig +short NS tidalfishintime.com
```

Verify that the public nameservers match the nameservers for the zone selected
by `route53_zone_id`. If they do not, correct the zone ID or configure
delegation before requesting the certificate. Then review the full plan before
applying:

```bash
terraform plan -out fishintime.tfplan
```

Review the plan carefully, especially the account, public networking, and any resource replacements. If it is correct:

```bash
terraform apply fishintime.tfplan
```

## 7. Verify the deployment

```bash
terraform output -raw load_balancer_url
curl -i "$(terraform output -raw load_balancer_url)/health"

aws ecs describe-services \
  --cluster fishintime-cluster \
  --services fishintime-backend-service \
  --region "$AWS_REGION" \
  --query 'services[0].{status:status,desired:desiredCount,running:runningCount,events:events[0:5]}'

aws elbv2 describe-target-health \
  --target-group-arn "$(terraform output -raw target_group_arn)" \
  --region "$AWS_REGION"

aws logs tail /ecs/fishintime-backend --follow --region "$AWS_REGION"
```

The `load_balancer_url` output is the HTTPS API URL. Configure mobile frontend
builds to use that origin in `config.js`. The HTTP listener redirects to HTTPS;
clients should use the HTTPS URL directly.

After applying, copy the Cognito and DynamoDB outputs into the ignored
workspace `.env` file for local development:

```bash
terraform output -raw cognito_user_pool_id
terraform output -raw cognito_client_id
terraform output -raw cognito_issuer
terraform output -raw cognito_login_domain
terraform output -raw billing_table_name
terraform output -raw billing_live_table_name
```

Set those values as `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`,
`COGNITO_ISSUER`, `COGNITO_LOGIN_DOMAIN`, and `BILLING_TABLE_NAME` (the sandbox
table). For local live runs, set `BILLING_TABLE_NAME_LIVE` to the live table
output; the application defaults to appending `-live` to `BILLING_TABLE_NAME`
when this variable is absent. Keep `APP_BASE_URL=http://localhost:8000` for
local runs; the VS Code launch configuration loads `.env`. For deployed tasks,
Terraform sets the public `app_base_url` and live resource outputs directly.

## What this template reconstructs—and what it cannot know

- It recreates a VPC (`10.40.0.0/16`), two public subnets, internet gateway/routes, security groups, ALB/listener/target group, ECR, ECS cluster/service/task definition, IAM roles/policies, log group, and secret containers.
- Original VPC/subnet/security-group IDs and exact subnet CIDRs were not present in the chat history, so the template uses a new non-overlapping example VPC range. Check that `10.40.0.0/16` does not overlap with networks you need to connect.
- The prior ECS image was `fishintime-backend:latest`; the task definition expects the Docker image's default startup command to launch `api:app` on `0.0.0.0:8000`.
- `AWS_REGION`, `AWS_DEFAULT_REGION`, and the old `AWS_SECRET_NAME=FishinSecret` environment variable are included. The known code paths directly fetch the two named secrets, so verify the current `get_secret()` implementation.
- If the code instead expects `OPENAI_API_KEY` and `AGENT_ID` as environment variables, update the task definition to inject the secret values rather than fetching them in Python. Avoid maintaining two competing secret-loading mechanisms.
- The template has not been applied to a live account. Review `terraform plan` and fix any account-specific restrictions before applying.
- `terraform destroy` deletes the stack and should only be used intentionally. Secret deletion uses a recovery window.
