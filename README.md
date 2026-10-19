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
configure AWS credentials through the AWS CLI/profile or standard AWS
environment variables; do not commit credentials or a `.env` file containing
the API key. `.env` is excluded from Git.
