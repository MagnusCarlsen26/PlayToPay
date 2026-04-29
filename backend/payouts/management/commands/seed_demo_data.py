from datetime import timedelta
import os
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from payouts.models import BankAccount, LedgerEntry, Merchant, MerchantBalance, Payout


def sync_balance(merchant: Merchant) -> None:
    available = (
        LedgerEntry.objects.filter(merchant=merchant)
        .aggregate(total=Coalesce(Sum("amount_paise"), 0))
        .get("total", 0)
    )
    held = (
        Payout.objects.filter(merchant=merchant, status__in=[Payout.Status.PENDING, Payout.Status.PROCESSING])
        .aggregate(total=Coalesce(Sum("amount_paise"), 0))
        .get("total", 0)
    )
    MerchantBalance.objects.update_or_create(
        merchant=merchant,
        defaults={"available_balance_paise": available, "held_balance_paise": held},
    )


class Command(BaseCommand):
    help = "Seed merchants, balances, bank accounts, ledger entries, and payout history."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-if-exists",
            action="store_true",
            help="Leave existing data untouched when merchants already exist.",
        )
        parser.add_argument(
            "--demo-merchant-id",
            default=os.getenv("DEMO_MERCHANT_ID", ""),
            help="Optional UUID to use for the primary seeded merchant.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["skip_if_exists"] and Merchant.objects.exists():
            self.stdout.write("Demo merchants already exist; skipping seed.")
            return

        merchant_a_id = None
        if options["demo_merchant_id"]:
            try:
                merchant_a_id = uuid.UUID(options["demo_merchant_id"])
            except ValueError:
                raise CommandError("DEMO_MERCHANT_ID must be a valid UUID.")

        MerchantBalance.objects.all().delete()
        LedgerEntry.objects.all().delete()
        Payout.objects.all().delete()
        BankAccount.objects.all().delete()
        Merchant.objects.all().delete()

        merchant_a_kwargs = {"name": "Nimbus Studio", "email": "ops@nimbus.example"}
        if merchant_a_id is not None:
            merchant_a_kwargs["id"] = merchant_a_id
        merchant_a = Merchant.objects.create(**merchant_a_kwargs)
        merchant_b = Merchant.objects.create(name="Cedar Freelance", email="hello@cedar.example")
        merchant_c = Merchant.objects.create(name="Atlas Growth", email="finance@atlas.example")

        accounts = {
            merchant_a: BankAccount.objects.create(
                merchant=merchant_a,
                label="HDFC Primary",
                account_number_masked="xxxx4321",
                ifsc="HDFC0001234",
            ),
            merchant_b: BankAccount.objects.create(
                merchant=merchant_b,
                label="ICICI Settlement",
                account_number_masked="xxxx2468",
                ifsc="ICIC0005678",
            ),
            merchant_c: BankAccount.objects.create(
                merchant=merchant_c,
                label="Axis Ops",
                account_number_masked="xxxx1357",
                ifsc="UTIB0009876",
            ),
        }

        for index, amount in enumerate([1000000, 800000, 600000, 500000, 200000], start=1):
            LedgerEntry.objects.create(
                merchant=merchant_a,
                entry_type=LedgerEntry.EntryType.CREDIT,
                amount_paise=amount,
                reference=f"seed-credit-a-{index}",
            )
        completed = Payout.objects.create(
            merchant=merchant_a,
            bank_account=accounts[merchant_a],
            amount_paise=1000000,
            status=Payout.Status.COMPLETED,
            attempt_count=1,
            last_attempted_at=timezone.now(),
        )
        LedgerEntry.objects.create(
            merchant=merchant_a,
            entry_type=LedgerEntry.EntryType.PAYOUT_HOLD,
            amount_paise=-completed.amount_paise,
            payout=completed,
            reference=f"seed-hold-{completed.id}",
        )
        LedgerEntry.objects.create(
            merchant=merchant_a,
            entry_type=LedgerEntry.EntryType.PAYOUT_COMPLETED,
            amount_paise=0,
            payout=completed,
            reference=f"seed-completed-{completed.id}",
        )
        failed = Payout.objects.create(
            merchant=merchant_a,
            bank_account=accounts[merchant_a],
            amount_paise=500000,
            status=Payout.Status.FAILED,
            attempt_count=3,
            last_attempted_at=timezone.now(),
            failure_code="bank_declined",
            failure_reason="Seeded failure.",
        )
        LedgerEntry.objects.create(
            merchant=merchant_a,
            entry_type=LedgerEntry.EntryType.PAYOUT_HOLD,
            amount_paise=-failed.amount_paise,
            payout=failed,
            reference=f"seed-hold-{failed.id}",
        )
        LedgerEntry.objects.create(
            merchant=merchant_a,
            entry_type=LedgerEntry.EntryType.PAYOUT_RELEASE,
            amount_paise=failed.amount_paise,
            payout=failed,
            reference=f"seed-release-{failed.id}",
        )

        for index, amount in enumerate([1500000, 1000000, 500000], start=1):
            LedgerEntry.objects.create(
                merchant=merchant_b,
                entry_type=LedgerEntry.EntryType.CREDIT,
                amount_paise=amount,
                reference=f"seed-credit-b-{index}",
            )

        LedgerEntry.objects.create(
            merchant=merchant_c,
            entry_type=LedgerEntry.EntryType.CREDIT,
            amount_paise=500000,
            reference="seed-credit-c-1",
        )
        processing = Payout.objects.create(
            merchant=merchant_c,
            bank_account=accounts[merchant_c],
            amount_paise=300000,
            status=Payout.Status.PROCESSING,
            attempt_count=1,
            last_attempted_at=timezone.now() - timedelta(minutes=1),
            next_retry_at=timezone.now() - timedelta(seconds=5),
        )
        LedgerEntry.objects.create(
            merchant=merchant_c,
            entry_type=LedgerEntry.EntryType.PAYOUT_HOLD,
            amount_paise=-processing.amount_paise,
            payout=processing,
            reference=f"seed-hold-{processing.id}",
        )

        for merchant in [merchant_a, merchant_b, merchant_c]:
            sync_balance(merchant)

        self.stdout.write(self.style.SUCCESS("Seeded demo merchants."))
        self.stdout.write(f"Primary demo merchant: {merchant_a.name} {merchant_a.id}")
