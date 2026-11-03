import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError


class SecretsManagerError(RuntimeError):
    """Raised when the application cannot retrieve its configured secret."""


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
    return secret_string
