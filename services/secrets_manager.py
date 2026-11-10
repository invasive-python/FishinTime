import json
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError


class SecretsManagerError(RuntimeError):
    """Raised when the application cannot retrieve its configured secret."""


_SECRET_FIELDS = {
    "FishinSecret_OpenAI": "OPENAI_API_KEY",
    "FishinSecret_Agent_Id": "AGENT_ID",
    "FishinSecret_Stripe_API_Key": "FishinSecret_Stripe_API",
}


def get_secret(secret_name: str) -> str:
    region_name = (
        os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-2"
    )

    try:
        response = boto3.client(
            "secretsmanager", region_name=region_name
        ).get_secret_value(SecretId=secret_name)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "Unknown")
        raise SecretsManagerError(
            f"Could not retrieve secret '{secret_name}' from AWS Secrets Manager "
            f"in region '{region_name}' (AWS error: {error_code})."
        ) from exc
    except BotoCoreError as exc:
        raise SecretsManagerError(
            f"Could not retrieve secret '{secret_name}' from AWS Secrets Manager "
            f"in region '{region_name}' ({type(exc).__name__}). Check the AWS "
            "credentials and configuration available to this process."
        ) from exc

    secret_string = response.get("SecretString")
    if not isinstance(secret_string, str) or not secret_string.strip():
        raise SecretsManagerError(
            f"Secret '{secret_name}' must contain a non-empty SecretString."
        )

    field_name = _SECRET_FIELDS.get(secret_name)
    if field_name is None:
        return secret_string

    try:
        secret_data = json.loads(secret_string)
    except json.JSONDecodeError:
        return secret_string

    if not isinstance(secret_data, dict):
        raise SecretsManagerError(
            f"Secret '{secret_name}' must be a JSON object containing "
            f"a non-empty '{field_name}' field."
        )

    secret_value = secret_data.get(field_name)
    if not isinstance(secret_value, str) or not secret_value.strip():
        raise SecretsManagerError(
            f"Secret '{secret_name}' must contain a non-empty "
            f"'{field_name}' field."
        )

    return secret_value.strip()
