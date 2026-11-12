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
the OpenAI API key as JSON (`{"OPENAI_API_KEY":"..."}`) in
`FishinSecret_OpenAI` and the agent ID as JSON (`{"AGENT_ID":"..."}`) in
`FishinSecret_Agent_Id`. The application extracts those fields from the JSON.
The AWS region defaults to `us-east-2` and can be overridden with `AWS_REGION`.

The application reads the secret once during FastAPI startup and keeps it in
memory for that process. If AWS Secrets Manager cannot return a valid secret,
startup fails rather than allowing forecast requests to fail later. Restart or
redeploy the app after rotating the secret so the new value is loaded.

When running on AWS, grant the application's IAM role
`secretsmanager:GetSecretValue` for this secret. For local development,
configure the `fishintime-757` AWS CLI profile with access to the application
secrets. Use a non-root IAM principal with least-privilege permissions;
the resource ARNs are listed in
`infra/iam/fishintime-task-secrets-policy.json`.

```sh
aws configure --profile fishintime-757  # only if this profile is not configured
set -a
. ./.env
set +a
./.venv/bin/python run.py
```

Local runs use the live Stripe account by default. To run against the retained
Stripe sandbox instead:

```sh
./.venv/bin/python run.py --sandbox
```

In VS Code, choose **Run API (live)** or **Run API (sandbox)**. Sandbox mode
uses the existing `FishinSecret_Stripe_API_Key` and `fishintime-billing`
resources; live mode uses `FishinSecret_Stripe_API` and a separate
`fishintime-billing-live` table. Apply the Terraform changes before using live
mode locally. Sandbox and live customer IDs, subscriptions, and webhook
signatures are isolated.

Verify the profile points to account `757266935832` before running Terraform or
the app:

```sh
aws sts get-caller-identity --profile fishintime-757
```

The application calls Secrets Manager directly in both local development and
AWS deployments. boto3 uses the `fishintime-757` profile locally and
the task's IAM role on AWS. `.env` supplies local region and Cognito/billing
configuration, but never stores secret values.
Check the local credentials with `aws sts get-caller-identity
--profile fishintime-757`. Do not commit AWS credentials or secret values; `.env`
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
Checkout classifies the AI fishing recommendation subscription with Stripe
Tax code `txcd_10105001` (AIaaS, cloud-based, personal use) to support Stripe
Managed Payments. This assumes the service is sold to individual recreational
anglers; review the tax classification if the intended customer base changes.

The `FishinSecret_Stripe_API` secret contains the live restricted Stripe API
key, either as plain text or in a JSON object under the
`FishinSecret_Stripe_API_Key` field. Sandbox mode uses the retained
`FishinSecret_Stripe_API_Key` secret, whose JSON property is
`FishinSecret_Stripe_API`. The secrets have different names and property names.
Stripe API keys start with `sk_live_` or `rk_live_` in live mode and
`sk_test_` or `rk_test_` in a sandbox; `prod_` is a Stripe Product ID prefix,
not an API key prefix.

Configure separate Stripe webhook endpoints for live and sandbox, both pointed
at
`https://api.tidalfishintime.com/api/billing/webhook` for
`customer.subscription.created`, `customer.subscription.updated`, and
`customer.subscription.deleted`. Store the sandbox endpoint's signing secret
in `FishinTime_Stripe_Webhook_Secret` and the live endpoint's in
`FishinTime_Stripe_Webhook_Secret_Live`. The application selects the key,
webhook secret, and billing table for its Stripe mode.

The Cognito callback and logout allow-lists must contain the exact forecast
URL `${app_base_url}/` (by default, `https://tidalfishintime.com/`). The
`api.tidalfishintime.com` hostname remains an API compatibility alias. The
account page URL `${app_base_url}/billing/account` can remain in these lists
for compatibility. The plans are shown at
`/billing/subscribe`; sign-in and account self-service are at `/billing/account`.
The account page supports email changes with confirmation, password changes,
and subscription management through the Stripe billing portal. With email as
the user-pool sign-in attribute, changing the email also changes the address
used to sign in. The subscription page uses Cognito's authorization-code flow
with PKCE. Users can access forecast and environmental data without signing in;
any signed-in user can request AI fishing evaluations. Subscription status
remains available for billing and account management. Stripe API and webhook
secrets are read from Secrets Manager, and subscription status is updated only
after Stripe webhook events update the billing table.
