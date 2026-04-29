from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import IdempotencyKey, Payout
from .services import complete_payout, fail_payout, mark_payout_processing, simulate_bank_settlement


@shared_task
def process_payouts_batch(batch_size: int = 10) -> int:
    processed = 0
    while processed < batch_size:
        payout_id = _claim_next_payout_id()
        if not payout_id:
            break

        payout = Payout.objects.get(id=payout_id)
        outcome = simulate_bank_settlement()
        if outcome == "success":
            complete_payout(payout.id)
        elif outcome == "failure":
            fail_payout(payout.id, failure_code="bank_declined", failure_reason="Simulated bank failure.")
        else:
            payout.refresh_from_db()
            if payout.attempt_count >= 3:
                fail_payout(payout.id, failure_code="bank_timeout", failure_reason="Payout timed out after max retries.")
        processed += 1
    return processed


def _claim_next_payout_id():
    now = timezone.now()
    with transaction.atomic():
        payout = (
            Payout.objects.select_for_update(skip_locked=True)
            .filter(status=Payout.Status.PENDING)
            .order_by("created_at")
            .first()
        )
        if payout is None:
            payout = (
                Payout.objects.select_for_update(skip_locked=True)
                .filter(status=Payout.Status.PROCESSING, next_retry_at__lte=now, attempt_count__lt=3)
                .order_by("next_retry_at", "created_at")
                .first()
            )
        if payout is None:
            return None
        mark_payout_processing(payout)
        return payout.id


@shared_task
def cleanup_expired_idempotency_keys() -> int:
    deleted, _ = IdempotencyKey.objects.filter(expires_at__lt=timezone.now()).delete()
    return deleted
