import os
from typing import Literal


StripeMode = Literal["live", "sandbox"]


def get_stripe_mode() -> StripeMode:
    mode = os.getenv("STRIPE_MODE", "live").strip().lower()
    if mode == "live":
        return "live"
    if mode == "sandbox":
        return "sandbox"
    raise ValueError("STRIPE_MODE must be either 'live' or 'sandbox'.")


def get_stripe_api_secret_name() -> str:
    if get_stripe_mode() == "sandbox":
        return "FishinSecret_Stripe_API_Key"
    return "FishinSecret_Stripe_API"


def get_stripe_webhook_secret_name() -> str:
    if get_stripe_mode() == "sandbox":
        return "FishinTime_Stripe_Webhook_Secret"
    return "FishinTime_Stripe_Webhook_Secret_Live"


def get_billing_table_name() -> str | None:
    mode = get_stripe_mode()
    if mode == "sandbox":
        return (
            os.getenv("BILLING_TABLE_NAME_SANDBOX")
            or os.getenv("BILLING_TABLE_NAME")
        )

    live_table_name = os.getenv("BILLING_TABLE_NAME_LIVE")
    if live_table_name:
        return live_table_name

    base_table_name = os.getenv("BILLING_TABLE_NAME")
    if base_table_name:
        return f"{base_table_name}-live"
    return None
