# billing/router.py
import os

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/billing", tags=["billing"])

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

PRICE_IDS = {
    "plus_monthly": os.environ["STRIPE_PRICE_MONTHLY"],
    "plus_annual": os.environ["STRIPE_PRICE_ANNUAL"],
}

# TODO: implement error handling, timesouts

class CheckoutRequest(BaseModel):
    plan: str


@router.post("/checkout")
def create_checkout(
    request: CheckoutRequest,
    user=Depends(require_authenticated_user),
):
    price_id = PRICE_IDS.get(request.plan)
    if not price_id:
        raise HTTPException(400, "Invalid subscription plan")

    customer_id = get_or_create_stripe_customer(user)

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=(
            "https://YOUR_DOMAIN/billing/success"
            "?session_id={CHECKOUT_SESSION_ID}"
        ),
        cancel_url="https://YOUR_DOMAIN/pricing",
        client_reference_id=user.id,
        metadata={"user_id": user.id},
        subscription_data={
            "metadata": {"user_id": user.id}
        },
    )
    return {"checkout_url": session.url}