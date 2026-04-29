import uuid
from datetime import timedelta

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


def idempotency_expiry_default():
    return timezone.now() + timedelta(hours=24)


class Merchant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class BankAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="bank_accounts")
    label = models.CharField(max_length=255)
    account_number_masked = models.CharField(max_length=32)
    ifsc = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.label} ({self.account_number_masked})"


class MerchantBalance(models.Model):
    merchant = models.OneToOneField(Merchant, on_delete=models.CASCADE, primary_key=True, related_name="balance")
    available_balance_paise = models.BigIntegerField(default=0)
    held_balance_paise = models.BigIntegerField(default=0)
    version = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.merchant_id}: {self.available_balance_paise}/{self.held_balance_paise}"


class Payout(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="payouts")
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="payouts")
    amount_paise = models.BigIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempt_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=64, blank=True)
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["merchant", "status", "-created_at"]),
        ]


class LedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        CREDIT = "credit", "Credit"
        PAYOUT_HOLD = "payout_hold", "Payout Hold"
        PAYOUT_RELEASE = "payout_release", "Payout Release"
        PAYOUT_COMPLETED = "payout_completed", "Payout Completed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="ledger_entries")
    entry_type = models.CharField(max_length=32, choices=EntryType.choices)
    amount_paise = models.BigIntegerField()
    payout = models.ForeignKey(Payout, null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entries")
    reference = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["merchant", "-created_at"]),
        ]


class IdempotencyKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="idempotency_keys")
    key = models.UUIDField()
    request_fingerprint = models.CharField(max_length=64)
    request_method = models.CharField(max_length=16)
    request_path = models.CharField(max_length=255)
    status_code = models.PositiveIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    payout = models.ForeignKey(Payout, null=True, blank=True, on_delete=models.SET_NULL, related_name="idempotency_keys")
    is_in_progress = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=idempotency_expiry_default)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["merchant", "key"], name="uniq_merchant_idempotency_key"),
        ]
        indexes = [
            models.Index(fields=["expires_at"]),
        ]
