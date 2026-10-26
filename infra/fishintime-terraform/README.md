# FishinTime AWS infrastructure (Terraform)

This Terraform project reconstructs the FishinTime infrastructure from the prior deployment chats:

- Region `us-east-2` (Ohio)
- Public Application Load Balancer on HTTP port 80
- ECS Fargate service with one task by default, 256 CPU / 512 MiB
- FastAPI/Uvicorn container on port 8000; ALB health check `/health`, HTTP 200
- ECR repository `fishintime-backend`
- CloudWatch log group `/ecs/fishintime-backend`
- Separate ECS execution and application task roles
- Secrets Manager secrets `FishinSecret_OpenAI` and `FishinSecret_Agent_Id`

## Before you start

1. This creates resources in the AWS account selected by your CLI credentials. Verify the account first.
2. The secret resources are created without values. Add the values outside Terraform so the secret contents are not embedded in configuration/state.
3. The app code in the prior chats calls `get_secret("FishinSecret_OpenAI")` and `get_secret("FishinSecret_Agent_Id")`; check your current helper to confirm whether it expects raw strings or JSON.
4. This recreates the prior public HTTP demo architecture, not HTTPS/custom-domain support.
5. Fargate tasks receive public IPs so they can call OpenAI, NOAA, and USNO without a NAT gateway. The task security group only allows inbound app traffic from the ALB.
6. If a secret name is pending deletion from a prior attempt, AWS may prevent immediate reuse. Restore it or wait until its recovery window expires.
7. The old account had Organizations policy complications. If the new account belongs to an organization, check its service control policies allow these resources/actions.

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
aws sts get-caller-identity
export AWS_REGION=us-east-2
export AWS_DEFAULT_REGION=us-east-2
```

Do not proceed until the account ID shown by `get-caller-identity` is the account you intend to use.

## 2. Initialize Terraform and create bootstrap resources

From this directory:

```bash
terraform init
terraform fmt -check
terraform validate
terraform apply -target=aws_ecr_repository.backend \
  -target=aws_secretsmanager_secret.openai \
  -target=aws_secretsmanager_secret.agent_id
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

## 4. Add secret values outside Terraform

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

## 5. Plan and create the full stack

```bash
terraform plan -out fishintime.tfplan
```

Review the plan carefully, especially the account, public networking, and any resource replacements. If it is correct:

```bash
terraform apply fishintime.tfplan
```

## 6. Verify the deployment

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

## What this template reconstructs—and what it cannot know

- It recreates a VPC (`10.40.0.0/16`), two public subnets, internet gateway/routes, security groups, ALB/listener/target group, ECR, ECS cluster/service/task definition, IAM roles/policies, log group, and secret containers.
- Original VPC/subnet/security-group IDs and exact subnet CIDRs were not present in the chat history, so the template uses a new non-overlapping example VPC range. Check that `10.40.0.0/16` does not overlap with networks you need to connect.
- The prior ECS image was `fishintime-backend:latest`; the task definition expects the Docker image's default startup command to launch `api:app` on `0.0.0.0:8000`.
- `AWS_REGION`, `AWS_DEFAULT_REGION`, and the old `AWS_SECRET_NAME=FishinSecret` environment variable are included. The known code paths directly fetch the two named secrets, so verify the current `get_secret()` implementation.
- If the code instead expects `OPENAI_API_KEY` and `AGENT_ID` as environment variables, update the task definition to inject the secret values rather than fetching them in Python. Avoid maintaining two competing secret-loading mechanisms.
- The template has not been applied to a live account. Review `terraform plan` and fix any account-specific restrictions before applying.
- `terraform destroy` deletes the stack and should only be used intentionally. Secret deletion uses a recovery window.
