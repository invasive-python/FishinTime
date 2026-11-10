import unittest
from unittest.mock import patch

from botocore.exceptions import ClientError

from services.secrets_manager import SecretsManagerError, get_secret


class SecretsManagerTests(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {"AWS_REGION": "us-east-2"},
        clear=True,
    )
    @patch("services.secrets_manager.boto3.client")
    def test_reads_plain_secret_string(self, create_client):
        secrets_client = create_client.return_value
        secrets_client.get_secret_value.return_value = {
            "SecretString": "test-key"
        }

        self.assertEqual(get_secret("FishinSecret_OpenAI"), "test-key")
        create_client.assert_called_once_with(
            "secretsmanager", region_name="us-east-2"
        )
        secrets_client.get_secret_value.assert_called_once_with(
            SecretId="FishinSecret_OpenAI"
        )

    @patch("services.secrets_manager.boto3.client")
    def test_reads_expected_value_from_json_secret(self, create_client):
        secrets_client = create_client.return_value
        secrets_client.get_secret_value.return_value = {
            "SecretString": '{"FishinSecret_Stripe_API":"sk_test_value"}'
        }

        self.assertEqual(
            get_secret("FishinSecret_Stripe_API_Key"),
            "sk_test_value",
        )

    @patch("services.secrets_manager.boto3.client")
    def test_reports_missing_expected_json_field(self, create_client):
        create_client.return_value.get_secret_value.return_value = {
            "SecretString": '{"OTHER_KEY":"value"}'
        }

        with self.assertRaisesRegex(
            SecretsManagerError, "non-empty 'FishinSecret_Stripe_API' field"
        ):
            get_secret("FishinSecret_Stripe_API_Key")

    @patch("services.secrets_manager.boto3.client")
    def test_reports_missing_secret_string(self, create_client):
        create_client.return_value.get_secret_value.return_value = {}

        with self.assertRaisesRegex(SecretsManagerError, "non-empty SecretString"):
            get_secret("FishinSecret_OpenAI")

    @patch("services.secrets_manager.boto3.client")
    def test_wraps_aws_access_errors_without_exposing_details(self, create_client):
        create_client.return_value.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "access denied"}},
            "GetSecretValue",
        )

        with self.assertRaises(SecretsManagerError) as raised:
            get_secret("OPENAI_API_KEY")

        self.assertNotIn("access denied", str(raised.exception))
        self.assertIn("AccessDeniedException", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
