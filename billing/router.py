import logging
import os
import time
from typing import Annotated, Any, Literal

import boto3
import stripe
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
)
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from billing.auth import bearer, require_authenticated_user
from services.secrets_manager import SecretsManagerError, get_secret

router = APIRouter(prefix="/api/billing", tags=["billing"])
logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {"active", "trialing"}
CUSTOMER_SK = "STRIPE_CUSTOMER"
SUBSCRIPTION_SK = "SUBSCRIPTION"


class CheckoutRequest(BaseModel):
    plan: Literal["monthly", "annual"]


class UpdateEmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ConfirmEmailRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=12)


def _app_base_url() -> str:
    return os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")


def _cognito_region() -> str:
    return (
        os.getenv("COGNITO_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-2"
    )


def _cognito_error(exc: ClientError) -> HTTPException:
    error_code = exc.response.get("Error", {}).get("Code")
    client_errors = {
        "AliasExistsException": (409, "That email address is already in use."),
        "CodeMismatchException": (400, "The email verification code is incorrect."),
        "ExpiredCodeException": (400, "The email verification code has expired."),
        "InvalidPasswordException": (
            400,
            "The new password does not meet the password requirements.",
        ),
        "InvalidParameterException": (400, "The account information is invalid."),
        "LimitExceededException": (
            429,
            "Too many attempts. Please wait before trying again.",
        ),
        "NotAuthorizedException": (
            401,
            "The current password is incorrect or your sign-in has expired.",
        ),
        "UserNotFoundException": (404, "The account was not found."),
        "UsernameExistsException": (409, "That email address is already in use."),
    }
    if error_code in client_errors:
        status_code, detail = client_errors[error_code]
        return HTTPException(status_code=status_code, detail=detail)
    logger.exception("Cognito account operation failed.")
    return HTTPException(
        status_code=502,
        detail="The account service could not complete the request.",
    )


def _cognito_api_error(exc: BotoCoreError) -> HTTPException:
    logger.exception("Cognito account service is unavailable.")
    return HTTPException(
        status_code=503,
        detail="The account service is temporarily unavailable.",
    )


def _get_billing_table():
    table_name = os.getenv("BILLING_TABLE_NAME")
    if not table_name:
        raise HTTPException(
            status_code=503,
            detail="Billing storage is not configured.",
        )
    region = (
        os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-2"
    )
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _get_subscription(user_id: str) -> dict[str, Any] | None:
    table = _get_billing_table()
    try:
        result = table.get_item(
            Key={"PK": f"USER#{user_id}", "SK": SUBSCRIPTION_SK},
            ConsistentRead=True,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Could not read the subscription record.")
        raise HTTPException(
            status_code=503,
            detail="Subscription status is temporarily unavailable.",
        ) from exc
    return result.get("Item")


def _subscription_is_active(subscription: dict[str, Any] | None) -> bool:
    if not subscription or subscription.get("status") not in ACTIVE_STATUSES:
        return False
    period_end = int(subscription.get("current_period_end") or 0)
    return not period_end or period_end > int(time.time())


def has_active_subscription(user_id: str) -> bool:
    return _subscription_is_active(_get_subscription(user_id))


def _plan_config() -> dict[str, dict[str, Any]]:
    plans: dict[str, dict[str, Any]] = {}
    for plan, env_name, interval, label, default in (
        ("monthly", "STRIPE_MONTHLY_AMOUNT_CENTS", "month", "Monthly", "99"),
        ("annual", "STRIPE_ANNUAL_AMOUNT_CENTS", "year", "Annual", "999"),
    ):
        try:
            amount_cents = int(os.getenv(env_name, default))
        except ValueError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"{env_name} must be a whole number of cents.",
            ) from exc
        if amount_cents <= 0:
            raise HTTPException(
                status_code=503,
                detail=f"{env_name} must be greater than zero.",
            )
        plans[plan] = {
            "amount_cents": amount_cents,
            "interval": interval,
            "label": label,
        }
    return plans


def _stripe_ready() -> None:
    if not stripe.api_key:
        raise HTTPException(
            status_code=503,
            detail="Stripe payments are not configured.",
        )


def _get_or_create_customer(user: dict[str, Any]) -> str:
    user_id = str(user["id"])
    table = _get_billing_table()
    key = {"PK": f"USER#{user_id}", "SK": CUSTOMER_SK}
    try:
        result = table.get_item(Key=key, ConsistentRead=True)
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Could not read the Stripe customer record.")
        raise HTTPException(
            status_code=503,
            detail="Billing is temporarily unavailable.",
        ) from exc

    customer_id = (result.get("Item") or {}).get("customer_id")
    if customer_id:
        return str(customer_id)

    _stripe_ready()
    try:
        customer = stripe.Customer.create(
            email=user.get("email"),
            metadata={"user_id": user_id},
            idempotency_key=f"fishintime-customer-{user_id}",
        )
    except stripe.StripeError as exc:
        logger.exception("Stripe could not create a customer.")
        raise HTTPException(
            status_code=502,
            detail="Stripe could not create a billing customer.",
        ) from exc

    customer_id = str(customer.id)
    try:
        table.put_item(
            Item={**key, "customer_id": customer_id},
        )
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Could not save the Stripe customer record.")
        raise HTTPException(
            status_code=503,
            detail="Billing is temporarily unavailable.",
        ) from exc
    return customer_id


@router.get("/config")
def get_billing_config() -> dict[str, str]:
    login_domain = os.getenv("COGNITO_LOGIN_DOMAIN", "").rstrip("/")
    client_id = os.getenv("COGNITO_CLIENT_ID")
    if not login_domain or not client_id:
        raise HTTPException(
            status_code=503,
            detail="Sign-in is not configured.",
        )
    return {
        "login_domain": login_domain,
        "client_id": client_id,
        "redirect_uri": f"{_app_base_url()}/billing/account",
        "logout_uri": f"{_app_base_url()}/billing/account",
    }


@router.get("/plans")
def get_plans() -> dict[str, dict[str, Any]]:
    return _plan_config()


@router.get("/status")
def get_subscription_status(
    user: Annotated[dict[str, Any], Depends(require_authenticated_user)],
) -> dict[str, Any]:
    subscription = _get_subscription(str(user["id"]))
    status = (subscription or {}).get("status", "inactive")
    return {
        "active": _subscription_is_active(subscription),
        "status": status,
        "plan": (subscription or {}).get("plan"),
    }


@router.get("/account")
def get_account_profile(
    user: Annotated[dict[str, Any], Depends(require_authenticated_user)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer)
    ],
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Sign-in required.")
    try:
        response = boto3.client(
            "cognito-idp", region_name=_cognito_region()
        ).get_user(AccessToken=credentials.credentials)
    except ClientError as exc:
        raise _cognito_error(exc) from exc
    except BotoCoreError as exc:
        raise _cognito_api_error(exc) from exc

    attributes = {
        attribute["Name"]: attribute["Value"]
        for attribute in response.get("UserAttributes", [])
        if "Name" in attribute and "Value" in attribute
    }
    return {
        "username": response.get("Username", ""),
        "email": attributes.get("email", ""),
        "email_verified": attributes.get("email_verified") == "true",
    }


@router.post("/account/email")
def update_account_email(
    email_request: UpdateEmailRequest,
    user: Annotated[dict[str, Any], Depends(require_authenticated_user)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer)
    ],
) -> dict[str, str]:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Sign-in required.")
    email = email_request.email.strip()
    if not email:
        raise HTTPException(status_code=422, detail="Email address is required.")
    try:
        boto3.client(
            "cognito-idp", region_name=_cognito_region()
        ).update_user_attributes(
            AccessToken=credentials.credentials,
            UserAttributes=[{"Name": "email", "Value": email}],
        )
    except ClientError as exc:
        raise _cognito_error(exc) from exc
    except BotoCoreError as exc:
        raise _cognito_api_error(exc) from exc
    return {"message": "A confirmation code was sent to the new email address."}


@router.post("/account/email/verify")
def verify_account_email(
    confirmation: ConfirmEmailRequest,
    user: Annotated[dict[str, Any], Depends(require_authenticated_user)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer)
    ],
) -> dict[str, str]:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Sign-in required.")
    try:
        boto3.client(
            "cognito-idp", region_name=_cognito_region()
        ).verify_user_attribute(
            AccessToken=credentials.credentials,
            AttributeName="email",
            Code=confirmation.code,
        )
    except ClientError as exc:
        raise _cognito_error(exc) from exc
    except BotoCoreError as exc:
        raise _cognito_api_error(exc) from exc
    return {"message": "Your email address has been verified."}


@router.post("/account/password")
def change_account_password(
    password_request: ChangePasswordRequest,
    user: Annotated[dict[str, Any], Depends(require_authenticated_user)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer)
    ],
) -> dict[str, str]:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Sign-in required.")
    try:
        boto3.client(
            "cognito-idp", region_name=_cognito_region()
        ).change_password(
            AccessToken=credentials.credentials,
            PreviousPassword=password_request.current_password,
            ProposedPassword=password_request.new_password,
        )
    except ClientError as exc:
        raise _cognito_error(exc) from exc
    except BotoCoreError as exc:
        raise _cognito_api_error(exc) from exc
    return {"message": "Your password has been changed."}


@router.post("/checkout")
def create_checkout(
    checkout_request: CheckoutRequest,
    user: Annotated[dict[str, Any], Depends(require_authenticated_user)],
) -> dict[str, str]:
    _stripe_ready()
    if has_active_subscription(str(user["id"])):
        raise HTTPException(
            status_code=409,
            detail="An active subscription already exists.",
        )

    customer_id = _get_or_create_customer(user)
    plan = _plan_config()[checkout_request.plan]
    product_name = f"FishinTime {plan['label']} Subscription"

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": plan["amount_cents"],
                        "recurring": {"interval": plan["interval"]},
                        "product_data": {"name": product_name},
                    },
                    "quantity": 1,
                }
            ],
            success_url=(
                f"{_app_base_url()}/billing/success"
                "?session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=f"{_app_base_url()}/billing/cancel",
            client_reference_id=str(user["id"]),
            metadata={"user_id": str(user["id"]), "plan": checkout_request.plan},
            subscription_data={
                "metadata": {
                    "user_id": str(user["id"]),
                    "plan": checkout_request.plan,
                }
            },
        )
    except stripe.StripeError as exc:
        logger.exception("Stripe could not create a checkout session.")
        raise HTTPException(
            status_code=502,
            detail="Stripe could not start checkout.",
        ) from exc

    if not session.url:
        raise HTTPException(
            status_code=502,
            detail="Stripe returned no checkout URL.",
        )
    return {"checkout_url": session.url}


@router.post("/portal")
def create_portal_session(
    user: Annotated[dict[str, Any], Depends(require_authenticated_user)],
) -> dict[str, str]:
    _stripe_ready()
    table = _get_billing_table()
    try:
        result = table.get_item(
            Key={"PK": f"USER#{user['id']}", "SK": CUSTOMER_SK},
            ConsistentRead=True,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Could not read the Stripe customer record.")
        raise HTTPException(
            status_code=503,
            detail="Billing is temporarily unavailable.",
        ) from exc

    customer_id = (result.get("Item") or {}).get("customer_id")
    if not customer_id:
        raise HTTPException(
            status_code=404,
            detail="No billing customer exists for this account.",
        )

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{_app_base_url()}/billing/account",
        )
    except stripe.StripeError as exc:
        logger.exception("Stripe could not create a billing portal session.")
        raise HTTPException(
            status_code=502,
            detail="Stripe could not open the billing portal.",
        ) from exc

    return {"portal_url": session.url}


def _store_subscription_event(event: Any) -> None:
    subscription = event["data"]["object"]
    metadata = subscription.get("metadata") or {}
    user_id = metadata.get("user_id")
    if not user_id:
        logger.warning(
            "Ignoring Stripe subscription event without a user ID (event %s).",
            event["id"],
        )
        return

    customer = subscription.get("customer")
    customer_id = customer.get("id") if isinstance(customer, dict) else customer
    status = (
        "canceled"
        if event["type"] == "customer.subscription.deleted"
        else subscription.get("status", "inactive")
    )
    event_created = int(event.get("created", 0))
    item = {
        "PK": f"USER#{user_id}",
        "SK": SUBSCRIPTION_SK,
        "customer_id": str(customer_id or ""),
        "subscription_id": str(subscription["id"]),
        "status": str(status),
        "plan": metadata.get("plan", ""),
        "current_period_end": int(subscription.get("current_period_end", 0)),
        "last_event_created": event_created,
    }
    table = _get_billing_table()
    try:
        table.put_item(
            Item=item,
            ConditionExpression=(
                Attr("last_event_created").not_exists()
                | Attr("last_event_created").lte(event_created)
            ),
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            logger.info("Ignoring stale Stripe subscription event %s.", event["id"])
            return
        logger.exception("Could not save Stripe subscription status.")
        raise HTTPException(
            status_code=503,
            detail="Subscription updates are temporarily unavailable.",
        ) from exc
    except BotoCoreError as exc:
        logger.exception("Could not save Stripe subscription status.")
        raise HTTPException(
            status_code=503,
            detail="Subscription updates are temporarily unavailable.",
        ) from exc


@router.post("/webhook")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
) -> dict[str, bool]:
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe signature.")

    try:
        webhook_secret = await run_in_threadpool(
            get_secret, "FishinTime_Stripe_Webhook_Secret"
        )
    except SecretsManagerError as exc:
        logger.exception("Could not load the Stripe webhook signing secret.")
        raise HTTPException(
            status_code=503,
            detail="Webhook verification is temporarily unavailable.",
        ) from exc

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook.") from exc

    if event["type"] in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        await run_in_threadpool(_store_subscription_event, event)

    return {"received": True}
