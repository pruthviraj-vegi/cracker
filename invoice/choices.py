"""
Invoice-related choices and constants
"""

from django.db import models


class GstTypeChoices(models.TextChoices):
    """GST type choices"""

    CGST_SGST = "CGST_SGST", "CGST/SGST"
    IGST = "IGST", "IGST"


class InvoiceTypeChoices(models.TextChoices):
    """Invoice type choices"""

    GST = "GST", "Gst"
    CASH = "CASH", "Cash"


class PaymentTypeChoices(models.TextChoices):
    """Payment type choices"""

    CASH = "CASH", "Cash"
    CREDIT = "CREDIT", "Credit"


class PaymentStatusChoices(models.TextChoices):
    """Payment status choices"""

    UNPAID = "UNPAID", "Unpaid"
    PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
    PAID = "PAID", "Paid"
    VOID = "VOID", "Void"
    CANCELLED = "CANCELLED", "Cancelled"


class PaymentMethodChoices(models.TextChoices):
    """Payment method choices"""

    CASH = "CASH", "Cash"
    UPI = "UPI", "UPI"


class AuditTypeChoices(models.TextChoices):
    """Audit type choices"""

    CONVERSION = "CONVERSION", "Invoice Conversion"
    RENUMBER = "RENUMBER", "Invoice Renumbering"


class AuditStatusChoices(models.TextChoices):
    """Audit status choices"""

    PENDING = "PENDING", "Pending"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class ChangeTypeChoices(models.TextChoices):
    """Change type choices for audit trail"""

    CONVERSION = "CONVERSION", "Type Conversion"
    RENUMBER = "RENUMBER", "Number Change"
    MODIFICATION = "MODIFICATION", "General Modification"


class RefundTypeChoices(models.TextChoices):
    """Refund type choices for return invoices"""

    STORE_CREDIT = "STORE_CREDIT", "Store Credit"
    CASH_REFUND = "CASH_REFUND", "Cash Refund"
    VOUCHER = "VOUCHER", "Voucher"
    EXCHANGE = "EXCHANGE", "Exchange"
    OTHER = "OTHER", "Other"


class RefundStatusChoices(models.TextChoices):
    """Refund status choices for return invoices"""

    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    PROCESSING = "PROCESSING", "Processing"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"
    REJECTED = "REJECTED", "Rejected"


class RefundReasonChoices(models.TextChoices):
    """Refund reason choices for return invoices"""

    CUSTOMER_REQUEST = "CUSTOMER_REQUEST", "Customer Request"
    STORE_POLICY = "STORE_POLICY", "Store Policy"
    DEFECTIVE_PRODUCT = "DEFECTIVE_PRODUCT", "Defective Product"
    WRONG_PRODUCT = "WRONG_PRODUCT", "Wrong Product"
    WRONG_SIZE = "WRONG_SIZE", "Wrong Size"
    DAMAGED_IN_TRANSIT = "DAMAGED_IN_TRANSIT", "Damaged in Transit"
    QUALITY_ISSUE = "QUALITY_ISSUE", "Quality Issue"
    OTHER = "OTHER", "Other"


class ItemConditionChoices(models.TextChoices):
    """Item condition choices for returned items"""

    NEW = "NEW", "New/Unused"
    LIKE_NEW = "LIKE_NEW", "Like New"
    GOOD = "GOOD", "Good"
    FAIR = "FAIR", "Fair"
    DAMAGED = "DAMAGED", "Damaged"
    DEFECTIVE = "DEFECTIVE", "Defective"


class ItemReturnReasonChoices(models.TextChoices):
    """Item-specific return reason choices"""

    CUSTOMER_REQUEST = "CUSTOMER_REQUEST", "Customer Request"
    DEFECTIVE = "DEFECTIVE", "Defective Product"
    WRONG_ITEM = "WRONG_ITEM", "Wrong Item"
    WRONG_SIZE = "WRONG_SIZE", "Wrong Size"
    DAMAGED = "DAMAGED", "Damaged in Transit"
    QUALITY_ISSUE = "QUALITY_ISSUE", "Quality Issue"
    OTHER = "OTHER", "Other"
