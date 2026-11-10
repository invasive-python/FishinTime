import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import stripe
from fastapi import HTTPException
from starlette.requests import Request

from billing.router import (
    ChangePasswordRequest,
    CheckoutRequest,
    ConfirmEmailRequest,
    _store_subscription_event,
    change_account_password,
    create_checkout,
    get_account_profile,
    get_billing_config,
    get_plans,
    handle_stripe_webhook,
    update_account_email,
    verify_account_email,
    UpdateEmailRequest,
)


class BillingRouteTests(unittest.TestCase):
    def test_plans_use_configurable_amounts_in_cents(self):
        with patch.dict(
            "os.environ",
            {
                "STRIPE_MONTHLY_AMOUNT_CENTS": "125",
                "STRIPE_ANNUAL_AMOUNT_CENTS": "1200",
            },
            clear=True,
        ):
            plans = get_plans()

        self.assertEqual(plans["monthly"]["amount_cents"], 125)
        self.assertEqual(plans["monthly"]["interval"], "month")
        self.assertEqual(plans["annual"]["amount_cents"], 1200)
        self.assertEqual(plans["annual"]["interval"], "year")

    def test_plans_default_to_the_requested_prices(self):
        with patch.dict("os.environ", {}, clear=True):
            plans = get_plans()

        self.assertEqual(plans["monthly"]["amount_cents"], 99)
        self.assertEqual(plans["annual"]["amount_cents"], 999)

    def test_billing_config_returns_public_cognito_values(self):
        with patch.dict(
            "os.environ",
            {
                "COGNITO_LOGIN_DOMAIN": "https://fishin.auth.us-east-2.amazoncognito.com/",
                "COGNITO_CLIENT_ID": "public-client-id",
                "COGNITO_REGION": "us-east-2",
                "APP_BASE_URL": "https://api.example.com/",
            },
            clear=True,
        ):
            config = get_billing_config()

        self.assertEqual(
            config,
            {
                "login_domain": "https://fishin.auth.us-east-2.amazoncognito.com",
                "client_id": "public-client-id",
                "redirect_uri": "https://api.example.com/billing/account",
                "logout_uri": "https://api.example.com/billing/account",
            },
        )

    @patch("billing.router.boto3.client")
    def test_account_profile_returns_cognito_email(self, cognito_client):
        cognito_client.return_value.get_user.return_value = {
            "Username": "angler",
            "UserAttributes": [
                {"Name": "email", "Value": "angler@example.com"},
                {"Name": "email_verified", "Value": "true"},
            ],
        }

        result = get_account_profile(
            user={"id": "user-123"},
            credentials=Mock(credentials="access-token"),
        )

        self.assertEqual(
            result,
            {
                "username": "angler",
                "email": "angler@example.com",
                "email_verified": True,
            },
        )
        cognito_client.assert_called_once_with(
            "cognito-idp", region_name="us-east-2"
        )

    @patch("billing.router.boto3.client")
    def test_account_profile_uses_friendly_name_instead_of_uuid(
        self, cognito_client
    ):
        cognito_client.return_value.get_user.return_value = {
            "Username": "123e4567-e89b-12d3-a456-426614174000",
            "UserAttributes": [
                {"Name": "email", "Value": "angler@example.com"},
            ],
        }

        result = get_account_profile(
            user={"id": "user-123"},
            credentials=Mock(credentials="access-token"),
        )

        self.assertEqual(result["username"], "angler")

    @patch("billing.router.boto3.client")
    def test_account_email_update_and_verification_use_access_token(
        self, cognito_client
    ):
        credentials = Mock(credentials="access-token")

        result = update_account_email(
            UpdateEmailRequest(email="new@example.com"),
            user={"id": "user-123"},
            credentials=credentials,
        )
        self.assertIn("confirmation code", result["message"])
        cognito_client.return_value.update_user_attributes.assert_called_once_with(
            AccessToken="access-token",
            UserAttributes=[{"Name": "email", "Value": "new@example.com"}],
        )

        verify_account_email(
            ConfirmEmailRequest(code="123456"),
            user={"id": "user-123"},
            credentials=credentials,
        )
        cognito_client.return_value.verify_user_attribute.assert_called_once_with(
            AccessToken="access-token",
            AttributeName="email",
            Code="123456",
        )

    @patch("billing.router.boto3.client")
    def test_account_password_change_uses_access_token(self, cognito_client):
        result = change_account_password(
            ChangePasswordRequest(
                current_password="OldPassword123",
                new_password="NewPassword123",
            ),
            user={"id": "user-123"},
            credentials=Mock(credentials="access-token"),
        )

        self.assertIn("password has been changed", result["message"])
        cognito_client.return_value.change_password.assert_called_once_with(
            AccessToken="access-token",
            PreviousPassword="OldPassword123",
            ProposedPassword="NewPassword123",
        )

    @patch("billing.router.stripe.checkout.Session.create")
    @patch("billing.router._get_billing_table")
    def test_checkout_creates_recurring_inline_price(
        self, get_table, create_session
    ):
        table = get_table.return_value
        table.get_item.return_value = {"Item": {"customer_id": "cus_123"}}
        create_session.return_value = Mock(url="https://checkout.stripe.test/cs_123")
        with (
            patch.object(stripe, "api_key", "test-key"),
            patch.dict(
                "os.environ",
                {
                    "APP_BASE_URL": "https://api.example.com",
                    "STRIPE_MONTHLY_AMOUNT_CENTS": "99",
                    "STRIPE_ANNUAL_AMOUNT_CENTS": "999",
                },
                clear=True,
            ),
        ):
            result = create_checkout(
                checkout_request=CheckoutRequest(plan="annual"),
                user={"id": "user-123", "email": "angler@example.com"},
            )

        self.assertEqual(
            result,
            {"checkout_url": "https://checkout.stripe.test/cs_123"},
        )
        params = create_session.call_args.kwargs
        self.assertEqual(params["line_items"][0]["price_data"]["unit_amount"], 999)
        self.assertEqual(
            params["line_items"][0]["price_data"]["recurring"],
            {"interval": "year"},
        )
        self.assertEqual(
            params["line_items"][0]["price_data"]["product_data"]["tax_code"],
            "txcd_10105001",
        )
        self.assertEqual(params["client_reference_id"], "user-123")
        self.assertEqual(
            params["subscription_data"]["metadata"]["user_id"],
            "user-123",
        )
        self.assertEqual(
            params["success_url"],
            "https://api.example.com/billing/success"
            "?session_id={CHECKOUT_SESSION_ID}",
        )

    @patch(
        "billing.router.stripe.checkout.Session.create",
        side_effect=stripe.InvalidRequestError(
            "No such customer", "customer", code="resource_missing"
        ),
    )
    @patch("billing.router._get_billing_table")
    def test_checkout_reports_customer_mode_mismatch(
        self, get_table, create_session
    ):
        get_table.return_value.get_item.return_value = {
            "Item": {"customer_id": "cus_existing"}
        }
        with patch.object(stripe, "api_key", "test-key"), patch.dict(
            "os.environ", {}, clear=True
        ):
            with self.assertLogs("billing.router", level="ERROR"):
                with self.assertRaises(HTTPException) as raised:
                    create_checkout(
                        checkout_request=CheckoutRequest(plan="monthly"),
                        user={"id": "user-123", "email": "angler@example.com"},
                    )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("saved billing customer", raised.exception.detail)
        create_session.assert_called_once()

    @patch("billing.router._get_billing_table")
    def test_subscription_webhook_persists_entitlement(self, get_table):
        event = {
            "id": "evt_123",
            "type": "customer.subscription.created",
            "created": 123,
            "data": {
                "object": {
                    "id": "sub_123",
                    "customer": "cus_123",
                    "status": "active",
                    "current_period_end": 456,
                    "metadata": {"user_id": "user-123", "plan": "monthly"},
                }
            },
        }
        event = stripe.Event.construct_from(event, None)

        _store_subscription_event(event)

        item = get_table.return_value.put_item.call_args.kwargs["Item"]
        self.assertEqual(item["PK"], "USER#user-123")
        self.assertEqual(item["SK"], "SUBSCRIPTION")
        self.assertEqual(item["status"], "active")
        self.assertEqual(item["plan"], "monthly")

    def test_webhook_rejects_bad_signature(self):
        request = Mock(spec=Request)
        request.body = AsyncMock(return_value=b"{}")
        with (
            patch("billing.router.get_secret", return_value="whsec_test"),
            patch(
                "billing.router.stripe.Webhook.construct_event",
                side_effect=stripe.SignatureVerificationError(
                    "invalid signature", "sig"
                ),
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            asyncio.run(handle_stripe_webhook(request, "sig"))

        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
