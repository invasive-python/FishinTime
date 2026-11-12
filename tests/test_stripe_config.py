import unittest
from unittest.mock import patch

from services.stripe_config import (
    get_billing_table_name,
    get_stripe_api_secret_name,
    get_stripe_mode,
    get_stripe_webhook_secret_name,
)


class StripeConfigTests(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    def test_defaults_to_live_mode_and_resources(self):
        self.assertEqual(get_stripe_mode(), "live")
        self.assertEqual(
            get_stripe_api_secret_name(),
            "FishinSecret_Stripe_API",
        )
        self.assertEqual(
            get_stripe_webhook_secret_name(),
            "FishinTime_Stripe_Webhook_Secret_Live",
        )
        self.assertIsNone(get_billing_table_name())

    @patch.dict(
        "os.environ",
        {
            "STRIPE_MODE": "sandbox",
            "BILLING_TABLE_NAME": "fishintime-billing",
        },
        clear=True,
    )
    def test_sandbox_uses_retained_resources(self):
        self.assertEqual(get_stripe_mode(), "sandbox")
        self.assertEqual(
            get_stripe_api_secret_name(),
            "FishinSecret_Stripe_API_Key",
        )
        self.assertEqual(
            get_stripe_webhook_secret_name(),
            "FishinTime_Stripe_Webhook_Secret",
        )
        self.assertEqual(get_billing_table_name(), "fishintime-billing")

    @patch.dict(
        "os.environ",
        {
            "BILLING_TABLE_NAME": "fishintime-billing",
            "BILLING_TABLE_NAME_LIVE": "fishintime-live-billing",
        },
        clear=True,
    )
    def test_live_table_is_separate_from_legacy_sandbox_table(self):
        self.assertEqual(
            get_billing_table_name(),
            "fishintime-live-billing",
        )

    @patch.dict(
        "os.environ",
        {"BILLING_TABLE_NAME": "fishintime-billing"},
        clear=True,
    )
    def test_live_table_defaults_to_suffix_on_legacy_table_name(self):
        self.assertEqual(
            get_billing_table_name(),
            "fishintime-billing-live",
        )

    @patch.dict("os.environ", {"STRIPE_MODE": "production"}, clear=True)
    def test_rejects_unknown_mode(self):
        with self.assertRaisesRegex(ValueError, "STRIPE_MODE"):
            get_stripe_mode()


if __name__ == "__main__":
    unittest.main()
