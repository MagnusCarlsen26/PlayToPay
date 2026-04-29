import threading
import uuid

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from unittest import skipUnless

from payouts.models import LedgerEntry, MerchantBalance, Payout
from payouts.services import request_payout
from payouts.tests.test_helpers import create_merchant_with_balance


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row-level locking semantics.")
class ConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.merchant, self.bank_account = create_merchant_with_balance(amount_paise=10000)

    def tearDown(self):
        connections.close_all()
        super().tearDown()

    def test_two_parallel_payouts_only_allow_one_hold(self):
        barrier = threading.Barrier(2)
        results = []

        def submit():
            close_old_connections()
            barrier.wait(timeout=5)
            try:
                response = request_payout(
                    merchant=self.merchant,
                    idempotency_key=str(uuid.uuid4()),
                    amount_paise=6000,
                    bank_account_id=self.bank_account.id,
                    request_method="POST",
                    request_path="/api/v1/payouts",
                )
                results.append((response.status_code, response.body))
            finally:
                close_old_connections()
                connections.close_all()

        threads = [threading.Thread(target=submit) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        close_old_connections()
        connections.close_all()

        statuses = sorted(status for status, _body in results)
        self.assertEqual(len(statuses), 2)
        self.assertEqual(statuses, [201, 400])
        self.assertEqual(Payout.objects.count(), 1)
        self.assertEqual(LedgerEntry.objects.filter(entry_type=LedgerEntry.EntryType.PAYOUT_HOLD).count(), 1)

        balance = MerchantBalance.objects.get(merchant=self.merchant)
        self.assertEqual(balance.available_balance_paise, 4000)
        self.assertEqual(balance.held_balance_paise, 6000)
