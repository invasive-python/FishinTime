# fishin_time

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
