import threading

from django.db import close_old_connections, connections
from django.test import TransactionTestCase

from payouts.models import IdempotencyKey, Payout
from payouts.services import IdempotencyConflict, IdempotencyPayloadMismatch, request_payout
from payouts.tests.test_helpers import create_merchant_with_balance


class IdempotencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.merchant, self.bank_account = create_merchant_with_balance(amount_paise=10000)

    def tearDown(self):
        connections.close_all()
        super().tearDown()

    def test_reuses_same_response_for_same_key(self):
        key = "80e8d638-cb38-4a11-9693-2620d290ca9d"
        first = request_payout(
            merchant=self.merchant,
            idempotency_key=key,
            amount_paise=5000,
            bank_account_id=self.bank_account.id,
            request_method="POST",
            request_path="/api/v1/payouts",
        )
        second = request_payout(
            merchant=self.merchant,
            idempotency_key=key,
            amount_paise=5000,
            bank_account_id=self.bank_account.id,
            request_method="POST",
            request_path="/api/v1/payouts",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.body, second.body)
        self.assertEqual(Payout.objects.count(), 1)

    def test_same_key_with_different_payload_rejected(self):
        key = "80e8d638-cb38-4a11-9693-2620d290ca9d"
        request_payout(
            merchant=self.merchant,
            idempotency_key=key,
            amount_paise=5000,
            bank_account_id=self.bank_account.id,
            request_method="POST",
            request_path="/api/v1/payouts",
        )

        with self.assertRaisesMessage(IdempotencyPayloadMismatch, "different payload"):
            request_payout(
                merchant=self.merchant,
                idempotency_key=key,
                amount_paise=6000,
                bank_account_id=self.bank_account.id,
                request_method="POST",
                request_path="/api/v1/payouts",
            )

    def test_second_request_sees_in_flight_key(self):
        key = "80e8d638-cb38-4a11-9693-2620d290ca9d"
        claimed = threading.Event()
        release = threading.Event()
        errors = []

        def after_claim_hook():
            claimed.set()
            release.wait(timeout=5)

        def first_request():
            close_old_connections()
            try:
                request_payout(
                    merchant=self.merchant,
                    idempotency_key=key,
                    amount_paise=5000,
                    bank_account_id=self.bank_account.id,
                    request_method="POST",
                    request_path="/api/v1/payouts",
                    after_claim_hook=after_claim_hook,
                )
            except Exception as exc:  # pragma: no cover - test surfacing
                errors.append(exc)
            finally:
                close_old_connections()
                connections.close_all()

        thread = threading.Thread(target=first_request)
        thread.start()
        claimed.wait(timeout=5)

        with self.assertRaisesMessage(IdempotencyConflict, "Request in progress."):
            request_payout(
                merchant=self.merchant,
                idempotency_key=key,
                amount_paise=5000,
                bank_account_id=self.bank_account.id,
                request_method="POST",
                request_path="/api/v1/payouts",
            )

        release.set()
        thread.join(timeout=5)
        close_old_connections()
        connections.close_all()
        self.assertFalse(errors)
        self.assertEqual(IdempotencyKey.objects.count(), 1)
