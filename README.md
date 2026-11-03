# fishin_time

Static files used by the page belong in `static/`. The Docker image copies this
directory and FastAPI serves it under `/static`; for example,
`static/mermaid-diagram.png` is available at `/static/mermaid-diagram.png`.

## Frontend backend URL

The frontend reads `window.FISHINTIME_API_BASE_URL` from `config.js` and uses it
for all API requests. Leave it empty to use the current origin, which keeps the
website's same-origin behavior. For a mobile app build, set it to the HTTPS
origin serving the API (for example, `https://api.example.com`, without a path).
Do not use the current HTTP-only load balancer URL for a released mobile app;
configure HTTPS for the API first. This URL is public configuration, not a place
to store API keys or other secrets.

## OpenAI agent and AWS Secrets Manager setup

Install the project dependencies with `pip install -r requirements.txt`. Store
the OpenAI API key as the plain-text secret value of the
`FishinSecret_OpenAI` secret in AWS Secrets Manager. The app reads that
secret's `SecretString` directly; it does not expect JSON. The AWS region
defaults to `us-east-2` and can be overridden with `AWS_REGION`. The app also
reads the agent ID from the plain-text `FishinSecret_Agent_Id` secret.

The application reads the secret once during FastAPI startup and keeps it in
memory for that process. If AWS Secrets Manager cannot return a valid secret,
startup fails rather than allowing forecast requests to fail later. Restart or
redeploy the app after rotating the secret so the new value is loaded.

When running on AWS, grant the application's IAM role
`secretsmanager:GetSecretValue` for this secret. For local development,
configure an AWS CLI profile with access to both secrets. In the AWS console,
create an IAM principal for local development (do not create access keys for
the root account), grant it `secretsmanager:GetSecretValue` for the two
application secrets, and create an access key. Use least-privilege permissions;
the resource ARNs are listed in `fishintime-task-secrets-policy.json`.

```sh
aws configure --profile fishintime
AWS_PROFILE=fishintime AWS_REGION=us-east-2 uvicorn api:app --reload
```

The application calls Secrets Manager directly in both local development and
AWS deployments. boto3 uses the configured AWS profile/credentials locally and
the task's IAM role on AWS. It does not load the secret values from `.env`.
Check the local credentials with `aws sts get-caller-identity
--profile fishintime`. Do not commit AWS credentials or secret values; `.env`
is excluded from Git.

## Stripe subscriptions and AI recommendations

The monthly and annual prices are Terraform variables measured in USD cents:
`stripe_monthly_amount_cents` defaults to `99`, and
`stripe_annual_amount_cents` defaults to `999`. For example, override either
value in your Terraform variables file or with `-var` when applying Terraform.
Checkout creates recurring Stripe prices from these amounts, so no Stripe
Price IDs need to be created or copied into the application. Remove any older
`stripe_price_monthly` / `stripe_price_annual` Price ID entries from
`terraform.tfvars`; use the new `stripe_monthly_amount_cents` /
`stripe_annual_amount_cents` values instead.

Set the `FishinSecret_Stripe_API_Key` Secrets Manager secret to your Stripe secret
API key. Configure a Stripe webhook at
`https://api.tidalfishintime.com/api/billing/webhook` for
`customer.subscription.created`, `customer.subscription.updated`, and
`customer.subscription.deleted`, then store that endpoint's signing secret in
`FishinTime_Stripe_Webhook_Secret`. The application reads the API key with
`get_secret("_Key_")` at startup and retrieves the webhook
signing secret from Secrets Manager when webhook requests arrive. The ECS task
role needs access to both secrets and to the billing DynamoDB table; Terraform
configures those permissions.

The Cognito callback allow-list must contain the exact subscription page URL
`${app_base_url}/billing/subscribe` (by default,
`https://api.tidalfishintime.com/billing/subscribe`). The subscription page
uses Cognito's public authorization-code flow with PKCE. Users can access
forecast and environmental data without signing in; an active or trialing
subscription is required only to start or retrieve an AI fishing evaluation.
The checkout and billing-portal endpoints require a Cognito access token.
