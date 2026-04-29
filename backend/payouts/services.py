# TODO: Many functions in this file are utility functions. They should be imported in the file.
import hashlib
import json
import random
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import BankAccount, IdempotencyKey, LedgerEntry, Merchant, MerchantBalance, Payout
# TODO: These Errors should be placed in a seperate file
# Probably backend/payout/errors/
class PayoutError(Exception):
    status_code = 400
    error_code = "payout_error"
    message = "Payout error"

    def __init__(self, message: str | None = None):
        # TODO: not sure why there is an ambiguity in choosing what should be used - message or self.message. If possible remove the ambiguity
        super().__init__(message or self.message)
        self.message = message or self.message

    def as_response(self) -> dict:
        return {"error": self.message, "code": self.error_code}


class InvalidMerchantContext(PayoutError):
    status_code = 400
    error_code = "invalid_merchant"
    message = "Missing or invalid X-Merchant-Id header."


class BankAccountNotFound(PayoutError):
    status_code = 404
    error_code = "bank_account_not_found"
    message = "Bank account not found for merchant."


class IdempotencyConflict(PayoutError):
    status_code = 409
    error_code = "idempotency_in_progress"
    message = "Request in progress."


class IdempotencyPayloadMismatch(PayoutError):
    status_code = 422
    error_code = "idempotency_payload_mismatch"
    message = "Idempotency key has already been used with a different payload."


class InvalidIdempotencyKey(PayoutError):
    status_code = 400
    error_code = "invalid_idempotency_key"
    message = "Idempotency-Key header must be a valid UUID."


class InsufficientFunds(PayoutError):
    status_code = 400
    error_code = "insufficient_funds"
    message = "Insufficient funds."


class InvalidPayoutTransition(Exception):
    pass


VALID_TRANSITIONS = {
    Payout.Status.PENDING: {Payout.Status.PROCESSING},
    Payout.Status.PROCESSING: {Payout.Status.COMPLETED, Payout.Status.FAILED},
    Payout.Status.COMPLETED: set(),
    Payout.Status.FAILED: set(),
}


@dataclass
class ServiceResponse:
    status_code: int
    body: dict


def fingerprint_request(method: str, path: str, payload: dict) -> str:
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{method.upper()}|{path}|{canonical_payload}".encode("utf-8"))
    return digest.hexdigest()


def get_retry_delay(attempt_count: int) -> int:
    delays = settings.PAYOUT_RETRY_DELAYS_SECONDS
    index = min(max(attempt_count - 1, 0), len(delays) - 1)
    return delays[index]


def assert_transition(current_status: str, new_status: str) -> None:
    if new_status not in VALID_TRANSITIONS[current_status]:
        raise InvalidPayoutTransition(f"Cannot transition payout from {current_status} to {new_status}.")


def get_merchant_from_header(raw_merchant_id: str | None) -> Merchant:
    if not raw_merchant_id:
        raise InvalidMerchantContext
    try:
        merchant_uuid = uuid.UUID(raw_merchant_id)
    except (ValueError, TypeError) as exc:
        raise InvalidMerchantContext from exc
    try:
        return Merchant.objects.get(id=merchant_uuid)
    except Merchant.DoesNotExist as exc:
        raise InvalidMerchantContext from exc

# TODO: This function is too long. Try to break this down into smaller functions.
def request_payout(
    *,
    merchant: Merchant,
    idempotency_key: str,
    amount_paise: int,
    bank_account_id,
    request_method: str,
    request_path: str,
    after_claim_hook=None,
) -> ServiceResponse:
    try:
        parsed_key = uuid.UUID(str(idempotency_key))
    except (ValueError, TypeError) as exc:
        raise InvalidIdempotencyKey from exc

    payload = {"amount_paise": amount_paise, "bank_account_id": str(bank_account_id)}
    fingerprint = fingerprint_request(request_method, request_path, payload)

    # TODO: Probably this transaction.atomic() is not needed.
    # because there is already transaction.atomic() inside _claim_idempotency_key()
    with transaction.atomic():
        key_record, created = _claim_idempotency_key(
            merchant=merchant,
            parsed_key=parsed_key,
            fingerprint=fingerprint,
            request_method=request_method,
            request_path=request_path,
        )
        if not created:
            if key_record.request_fingerprint != fingerprint:
                raise IdempotencyPayloadMismatch
            if key_record.is_in_progress:
                raise IdempotencyConflict
            return ServiceResponse(status_code=key_record.status_code, body=key_record.response_body)

    if after_claim_hook is not None:
        after_claim_hook()

    try:
        with transaction.atomic():
            key_record = IdempotencyKey.objects.select_for_update().get(id=key_record.id)
            bank_account = _lock_bank_account(merchant=merchant, bank_account_id=bank_account_id)
            MerchantBalance.objects.select_for_update().get(merchant=merchant)
            updated_rows = (
                MerchantBalance.objects.filter(merchant=merchant, available_balance_paise__gte=amount_paise)
                .update(
                    available_balance_paise=F("available_balance_paise") - amount_paise,
                    held_balance_paise=F("held_balance_paise") + amount_paise,
                    version=F("version") + 1,
                )
            )
            if updated_rows != 1:
                response = {"error": InsufficientFunds.message, "code": InsufficientFunds.error_code}
                _finalize_idempotency(key_record, status_code=InsufficientFunds.status_code, body=response)
                return ServiceResponse(status_code=InsufficientFunds.status_code, body=response)

            payout = Payout.objects.create(
                merchant=merchant,
                bank_account=bank_account,
                amount_paise=amount_paise,
                status=Payout.Status.PENDING,
            )
            LedgerEntry.objects.create(
                merchant=merchant,
                entry_type=LedgerEntry.EntryType.PAYOUT_HOLD,
                amount_paise=-amount_paise,
                payout=payout,
                reference=f"hold:{payout.id}",
                metadata={"bank_account_id": str(bank_account.id)},
            )
            response = serialize_payout(payout)
            _finalize_idempotency(key_record, status_code=201, body=response, payout=payout)
            return ServiceResponse(status_code=201, body=response)
    except PayoutError as exc:
        _mark_idempotency_failed(key_record.id, exc)
        raise
    except Exception:
        raise


def _claim_idempotency_key(*, merchant: Merchant, parsed_key: uuid.UUID, fingerprint: str, request_method: str, request_path: str) -> tuple[IdempotencyKey, bool]:
    try:
        with transaction.atomic():
            return (
                IdempotencyKey.objects.create(
                    merchant=merchant,
                    key=parsed_key,
                    request_fingerprint=fingerprint,
                    request_method=request_method.upper(),
                    request_path=request_path,
                    expires_at=timezone.now() + timedelta(hours=24),
                ),
                True,
            )
    except IntegrityError:
        key_record = IdempotencyKey.objects.select_for_update().get(merchant=merchant, key=parsed_key)
        if key_record.expires_at <= timezone.now():
            raise IdempotencyConflict("Idempotency key has expired and cannot be reused until cleanup.")
        return key_record, False


def _lock_bank_account(*, merchant: Merchant, bank_account_id) -> BankAccount:
    try:
        return BankAccount.objects.select_for_update().get(merchant=merchant, id=bank_account_id, is_active=True)
    except BankAccount.DoesNotExist as exc:
        raise BankAccountNotFound from exc


def _finalize_idempotency(key_record: IdempotencyKey, *, status_code: int, body: dict, payout: Payout | None = None) -> None:
    key_record.status_code = status_code
    key_record.response_body = body
    key_record.payout = payout
    key_record.is_in_progress = False
    key_record.save(update_fields=["status_code", "response_body", "payout", "is_in_progress"])


def _mark_idempotency_failed(key_record_id, exc: PayoutError) -> None:
    with transaction.atomic():
        key_record = IdempotencyKey.objects.select_for_update().get(id=key_record_id)
        if key_record.is_in_progress:
            _finalize_idempotency(key_record, status_code=exc.status_code, body=exc.as_response())


def serialize_payout(payout: Payout) -> dict:
    return {
        "id": str(payout.id),
        "status": payout.status,
        "amount_paise": payout.amount_paise,
        "bank_account_id": str(payout.bank_account_id),
        "created_at": payout.created_at.isoformat().replace("+00:00", "Z"),
    }


def mark_payout_processing(payout: Payout) -> Payout:
    if payout.status == Payout.Status.PENDING:
        assert_transition(payout.status, Payout.Status.PROCESSING)
    elif payout.status != Payout.Status.PROCESSING:
        raise InvalidPayoutTransition(f"Cannot transition payout from {payout.status} to {Payout.Status.PROCESSING}.")
    payout.status = Payout.Status.PROCESSING
    payout.attempt_count += 1
    payout.last_attempted_at = timezone.now()
    payout.next_retry_at = payout.last_attempted_at + timedelta(seconds=get_retry_delay(payout.attempt_count))
    payout.failure_code = ""
    payout.failure_reason = ""
    payout.save(update_fields=["status", "attempt_count", "last_attempted_at", "next_retry_at", "failure_code", "failure_reason", "updated_at"])
    return payout


def complete_payout(payout_id) -> Payout:
    with transaction.atomic():
        payout = Payout.objects.select_for_update().select_related("merchant", "bank_account").get(id=payout_id)
        assert_transition(payout.status, Payout.Status.COMPLETED)
        payout.status = Payout.Status.COMPLETED
        payout.save(update_fields=["status", "updated_at"])
        MerchantBalance.objects.select_for_update().filter(merchant=payout.merchant).update(
            held_balance_paise=F("held_balance_paise") - payout.amount_paise,
            version=F("version") + 1,
        )
        LedgerEntry.objects.create(
            merchant=payout.merchant,
            entry_type=LedgerEntry.EntryType.PAYOUT_COMPLETED,
            amount_paise=0,
            payout=payout,
            reference=f"completed:{payout.id}",
            metadata={"bank_account_id": str(payout.bank_account_id)},
        )
        return payout


def fail_payout(payout_id, *, failure_code: str, failure_reason: str) -> Payout:
    with transaction.atomic():
        payout = Payout.objects.select_for_update().select_related("merchant", "bank_account").get(id=payout_id)
        assert_transition(payout.status, Payout.Status.FAILED)
        payout.status = Payout.Status.FAILED
        payout.failure_code = failure_code
        payout.failure_reason = failure_reason
        payout.save(update_fields=["status", "failure_code", "failure_reason", "updated_at"])
        MerchantBalance.objects.select_for_update().filter(merchant=payout.merchant).update(
            held_balance_paise=F("held_balance_paise") - payout.amount_paise,
            available_balance_paise=F("available_balance_paise") + payout.amount_paise,
            version=F("version") + 1,
        )
        LedgerEntry.objects.create(
            merchant=payout.merchant,
            entry_type=LedgerEntry.EntryType.PAYOUT_RELEASE,
            amount_paise=payout.amount_paise,
            payout=payout,
            reference=f"release:{payout.id}",
            metadata={"reason": failure_reason},
        )
        return payout


def simulate_bank_settlement() -> str:
    roll = random.random()
    if roll < 0.7:
        return "success"
    if roll < 0.9:
        return "failure"
    return "hang"
