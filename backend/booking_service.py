"""Booking state changes shared by routes, account deletion and the maintenance worker."""
import os
from datetime import timedelta
from typing import Optional

import stripe
from starlette.concurrency import run_in_threadpool

from core import (
    CANCEL_FULL_REFUND_HOURS, booking_start_utc, db, logger, now_iso, now_utc,
    push_notification, reverse_platform_fee, tutor_user_id,
)

stripe.api_key = os.environ.get("STRIPE_API_KEY", "")


async def attach_payment_intent(booking: dict, idempotency_prefix: str, extra_metadata: Optional[dict] = None) -> None:
    """Create a Stripe PaymentIntent for the booking, falling back to a mock id when Stripe is unavailable."""
    try:
        intent = await run_in_threadpool(
            lambda: stripe.PaymentIntent.create(
                amount=booking["amount_cents"],
                currency=booking["currency"],
                automatic_payment_methods={"enabled": True},
                metadata={"booking_id": booking["id"], **(extra_metadata or {})},
                idempotency_key=f"{idempotency_prefix}-{booking['id']}",
            )
        )
        booking["stripe_payment_intent_id"] = intent.id
        booking["client_secret"] = intent.client_secret
    except Exception as e:
        logger.warning(f"Stripe PaymentIntent failed: {e}. Falling back to mock.")
        booking["stripe_payment_intent_id"] = f"pi_mock_{booking['id']}"
        booking["client_secret"] = f"pi_mock_secret_{booking['id']}"


async def _refund(booking: dict, amount_cents: int) -> str:
    """Refund through Stripe. Mock payments are 'refunded' without a call."""
    intent = booking.get("stripe_payment_intent_id") or ""
    if not intent or intent.startswith("pi_mock_"):
        return "refunded"
    try:
        await run_in_threadpool(lambda: stripe.Refund.create(
            payment_intent=intent, amount=amount_cents,
            idempotency_key=f"refund-{booking['id']}",
        ))
        return "refunded"
    except Exception as e:
        logger.error(f"Stripe refund for booking {booking['id']} failed: {e}")
        return "failed"


def refund_policy(booking: dict, by_role: str) -> int:
    """How much (in cents) goes back to the parent if the booking is canceled now.

    - Not paid yet → nothing to refund.
    - Tutor, admin or system cancels, or the tutor never accepted the request → full refund.
    - Parent cancels at least CANCEL_FULL_REFUND_HOURS before the start → full refund; later → none.
    """
    if booking.get("payment_status") != "paid":
        return 0
    if by_role in ("tutor", "admin", "system") or booking.get("tutor_response", "accepted") != "accepted":
        return int(booking["amount_cents"])
    start = booking_start_utc(booking)
    if start is None or start - now_utc() >= timedelta(hours=CANCEL_FULL_REFUND_HOURS):
        return int(booking["amount_cents"])
    return 0


async def cancel_booking(booking: dict, by_role: str, reason: str = "", notify: bool = True) -> dict:
    """Cancel a booking (idempotent), refund per policy, free the slot and tell the other side."""
    if booking.get("payment_status") == "canceled":
        return booking
    refund_cents = refund_policy(booking, by_role)
    was_paid = booking.get("payment_status") == "paid"
    refund_status = "none"
    if was_paid:
        refund_status = await _refund(booking, refund_cents) if refund_cents > 0 else "not_refunded"
    update = {
        "payment_status": "canceled", "canceled_at": now_iso(), "canceled_by": by_role,
        "cancel_reason": (reason or "").strip()[:500], "refund_status": refund_status,
        "refund_cents": refund_cents if refund_status == "refunded" else 0,
    }
    if booking.get("tutor_response") == "pending" and by_role == "tutor":
        update["tutor_response"] = "declined"
    res = await db.bookings.update_one(
        {"id": booking["id"], "payment_status": {"$ne": "canceled"}},
        {"$set": update, "$unset": {"slot_key": ""}},
    )
    if res.modified_count == 0:  # someone else canceled it first
        return await db.bookings.find_one({"id": booking["id"]}, {"_id": 0}) or booking
    booking = {**booking, **update}
    booking.pop("slot_key", None)
    if was_paid and refund_status == "refunded" and refund_cents >= int(booking["amount_cents"]):
        await reverse_platform_fee(booking)
    if notify:
        when = f"{booking['date']} at {booking['time']}"
        money = ""
        if refund_status == "refunded":
            money = f" A refund of ${refund_cents / 100:.2f} is on its way."
        elif refund_status == "not_refunded":
            money = f" Cancelled within {CANCEL_FULL_REFUND_HOURS}h of the start, so it isn't refunded."
        tutor_uid = await tutor_user_id(booking["tutor_id"])
        if by_role != "parent":
            await push_notification(booking["parent_id"], "booking", "Booking cancelled",
                                    f"Your session with {booking['tutor_name']} on {when} was cancelled.{money}",
                                    {"booking_id": booking["id"]})
        if tutor_uid and by_role != "tutor":
            await push_notification(tutor_uid, "booking", "Booking cancelled",
                                    f"{booking['parent_name']} cancelled the session on {when}.",
                                    {"booking_id": booking["id"]})
        if by_role == "parent":
            await push_notification(booking["parent_id"], "booking", "You cancelled a booking",
                                    f"Session with {booking['tutor_name']} on {when}.{money}",
                                    {"booking_id": booking["id"]})
    return booking
