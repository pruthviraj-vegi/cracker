"""
Views for the invoice audit table and related operations.
"""

import json
import logging
from datetime import datetime, time

from django.contrib import messages
from django.db import connection, transaction
from django.db.models import Q, Sum, F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic.edit import CreateView, DeleteView, View

from base.utility import build_search_filter, render_paginated_response, table_sorting
from base.decorators import required_permission, RequiredPermissionMixin

from invoice.form import AuditTableForm
from invoice.models import AuditTable, Invoice, InvoiceAudit, InvoiceSequence


logger = logging.getLogger(__name__)

VALID_SORT_FIELDS = {
    "id",
    "title",
    "audit_type",
    "status",
    "financial_year",
    "created_at",
    "start_date",
    "end_date",
}


@transaction.atomic
def resequence_invoices(
    financial_year, user=None, audit_table=None, reason="Resequence after conversion"
):
    """
    Safe resequence invoices for the given financial year.
    Handles uniqueness constraints properly using a 3-phase approach.
    """
    invoices = list(
        Invoice.objects.filter(financial_year=financial_year)
        .select_for_update()
        .order_by("invoice_date", "id")
        .values("id", "invoice_type", "invoice_number", "original_invoice_no")
    )

    if not invoices:
        raise ValueError("No invoices found for this financial year")

    all_invoice_ids = [inv["id"] for inv in invoices]

    original_numbers = {inv["id"]: inv["invoice_number"] for inv in invoices}
    # --- Phase 1: clear sequence + set temporary invoice_number ---
    with connection.cursor() as cursor:
        # Database-agnostic approach: update each invoice individually
        for invoice_id in all_invoice_ids:
            cursor.execute(
                """
                    UPDATE invoice_invoice
                    SET sequence_no = %s,
                        invoice_number = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                [
                    invoice_id + 1000000,
                    f"TEMP_{invoice_id}",
                    timezone.now(),
                    invoice_id,
                ],
            )

    gst_counter, cash_counter = 0, 0
    gst_updates, cash_updates, audit_records = [], [], []

    # --- Phase 2: prepare new sequences ---
    for inv in invoices:
        # Get the ORIGINAL invoice number (before we changed it to TEMP_)
        original_no = original_numbers[inv["id"]]
        old_type = inv["invoice_type"]

        if inv["invoice_type"] == Invoice.Invoice_type.GST:
            gst_counter += 1
            seq_no = gst_counter
            new_no = f"{financial_year}/{str(seq_no).zfill(3)}"
            gst_updates.append((seq_no, new_no, inv["id"], original_no))
        else:
            cash_counter += 1
            seq_no = cash_counter
            new_no = f"CASH/{financial_year}/{str(seq_no).zfill(3)}"
            cash_updates.append((seq_no, new_no, inv["id"], original_no))

        # Only create audit record if invoice number actually changed
        if original_no != new_no:
            audit_records.append(
                InvoiceAudit(
                    invoice_id=inv["id"],
                    audit_table=audit_table,
                    old_invoice_no=original_no,
                    new_invoice_no=new_no,
                    changed_by_id=user.id if user else None,
                    reason=reason,
                    change_type="RENUMBER",
                    old_invoice_type=old_type,
                    new_invoice_type=inv["invoice_type"],
                )
            )

    # --- Phase 3: apply final updates ---
    with connection.cursor() as cursor:
        # Update GST invoices
        for seq_no, new_no, inv_id, original_no in gst_updates:
            cursor.execute(
                """
                UPDATE invoice_invoice
                SET sequence_no = %s, invoice_number = %s, original_invoice_no = %s, updated_at = %s
                WHERE id = %s
                """,
                [seq_no, new_no, original_no, timezone.now(), inv_id],
            )

        # Update CASH invoices
        for seq_no, new_no, inv_id, original_no in cash_updates:
            cursor.execute(
                """
                UPDATE invoice_invoice
                SET sequence_no = %s, invoice_number = %s, original_invoice_no = %s, updated_at = %s
                WHERE id = %s
                """,
                [seq_no, new_no, original_no, timezone.now(), inv_id],
            )

    # --- Phase 4: bulk insert audits ---
    if audit_records:
        InvoiceAudit.objects.bulk_create(audit_records)

    # --- Phase 5: update sequence trackers ---
    InvoiceSequence.objects.update_or_create(
        invoice_type=Invoice.Invoice_type.GST,
        financial_year=financial_year,
        defaults={"last_number": gst_counter},
    )
    InvoiceSequence.objects.update_or_create(
        invoice_type=Invoice.Invoice_type.CASH,
        financial_year=financial_year,
        defaults={"last_number": cash_counter},
    )

    audit_table.status = AuditTable.Status.COMPLETED
    audit_table.save()

    return {
        "message": f"Resequenced {len(invoices)} invoices successfully",
        "gst_count": gst_counter,
        "cash_count": cash_counter,
        "total_count": len(invoices),
        "audit_records_created": len(audit_records),
    }


def apply_conversion(invoice, conversion_direction):
    """
    Apply GST <-> Cash conversion rules to invoice object.
    """
    sequence_no = invoice.id + 1000000

    if conversion_direction == "gst-to-cash":
        invoice.invoice_type = Invoice.Invoice_type.CASH
        invoice.sequence_no = sequence_no

    elif conversion_direction == "cash-to-gst":
        invoice.invoice_type = Invoice.Invoice_type.GST
        invoice.sequence_no = sequence_no

    return invoice


@required_permission("invoice.view_audittable")
def audit_home(request):
    """
    New audit home page with table view similar to invoice home
    """
    # Get available financial years for filter dropdown
    available_years = (
        AuditTable.objects.values_list("financial_year", flat=True)
        .distinct()
        .filter(financial_year__isnull=False)
        .order_by("-financial_year")
    )
    context = {
        "available_years": available_years,
    }
    return render(request, "invoice_audit/home.html", context)


@required_permission("invoice.view_audittable")
def get_data(request):
    """Get audit data with search and filter parameters"""
    # Get search and filter parameters
    search_query = request.GET.get("search", "")
    audit_type = request.GET.get("audit_type", "")
    status = request.GET.get("status", "")
    financial_year = request.GET.get("financial_year", "")

    # Apply search filter
    filters = build_search_filter(
        search_query,
        [
            "title",
            "description",
            "audit_type",
        ],
    )

    # Apply audit_type filter
    if audit_type:
        filters &= Q(audit_type=audit_type)

    # Apply status filter
    if status:
        filters &= Q(status=status)

    # Apply financial_year filter
    if financial_year:
        filters &= Q(financial_year=financial_year)

    # Apply sorting
    valid_sorts = table_sorting(request, VALID_SORT_FIELDS, "-created_at")
    queryset = (
        AuditTable.objects.select_related("created_by")
        .filter(filters)
        .order_by(*valid_sorts)
    )

    return queryset


def fetch_audit_tables(request):
    """
    AJAX endpoint to fetch audit tables with filtering, sorting, and pagination
    """
    audit_tables = get_data(request)
    search_query = request.GET.get("search", "").strip()

    return render_paginated_response(
        request,
        audit_tables,
        "invoice_audit/fetch.html",
        search_query=search_query,
    )


def audit_suggestions(request):
    """
    AJAX endpoint for search suggestions on audit tables
    """
    try:
        query = request.GET.get("q", "").strip()
        if len(query) < 2:
            return JsonResponse({"suggestions": []})

        # Search in title, description, and audit_type
        suggestions = []

        # Title suggestions
        title_matches = (
            AuditTable.objects.filter(title__icontains=query)
            .values_list("title", flat=True)
            .distinct()[:5]
        )

        for title in title_matches:
            suggestions.append({"text": title, "type": "title", "category": "Title"})

        # Description suggestions
        desc_matches = (
            AuditTable.objects.filter(description__icontains=query)
            .values_list("description", flat=True)
            .distinct()[:3]
        )

        for desc in desc_matches:
            if desc and len(desc) > 10:
                suggestions.append(
                    {
                        "text": desc[:50] + "..." if len(desc) > 50 else desc,
                        "type": "description",
                        "category": "Description",
                    }
                )

        # Audit type suggestions
        type_matches = (
            AuditTable.objects.filter(audit_type__icontains=query)
            .values_list("audit_type", flat=True)
            .distinct()[:3]
        )

        for audit_type in type_matches:
            suggestions.append(
                {"text": audit_type, "type": "audit_type", "category": "Type"}
            )

        return JsonResponse({"suggestions": suggestions})

    except Exception as e:  # pylint: disable=broad-except
        return JsonResponse({"success": False, "error": str(e)}, status=500)


class AuditTableCreateView(RequiredPermissionMixin, CreateView):
    """View to handle the creation of new audit sessions."""

    model = AuditTable
    form_class = AuditTableForm
    template_name = "invoice_audit/form.html"
    required_permission = "invoice.add_audittable"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create New Audit Session"
        return context

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Audit session created successfully!")
        return super().form_valid(form)

    def get_success_url(self):
        """Return URL to redirect to upon successful audit session creation."""
        return self.object.get_absolute_url()


class AuditTableDeleteView(RequiredPermissionMixin, DeleteView):
    """View to handle the deletion of audit sessions."""

    model = AuditTable
    template_name = "invoice_audit/delete.html"
    context_object_name = "audit_table"
    success_url = reverse_lazy("invoice:audit_home")
    required_permission = "invoice.delete_audittable"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["invoice_audits"] = self.object.invoice_audits.select_related(
            "invoice", "changed_by"
        ).order_by("-created_at")
        return context

    def get_success_url(self):
        """Return URL to redirect to after successful deletion."""
        return reverse_lazy("invoice:audit_home")

    def get_success_url_name(self):
        """Helper method occasionally used by custom logic for redirects."""
        return "invoice:audit_detail"


class InvoiceManager(RequiredPermissionMixin, View):
    """View to manage invoices for audit."""

    template = "invoice_audit/invoice_manager.html"
    required_permission = "invoice.view_audittable"

    def get(self, request, pk):
        """Handle GET requests to display invoice manager."""

        audit = get_object_or_404(AuditTable, pk=pk)

        start_date = datetime.combine(audit.start_date, time.min)
        end_date = datetime.combine(audit.end_date, time.max)

        date_range_info = f"From {start_date.strftime('%b %d, %Y')} to {end_date.strftime('%b %d, %Y')}"

        invoices = (
            Invoice.objects.select_related("customer")
            .filter(invoice_date__range=(start_date, end_date))
            .exclude(is_cancelled=True)
            .exclude(return_invoices__isnull=False)
            .order_by("-invoice_date", "-id")
        )

        # Get GST invoices
        gst_invoices = invoices.filter(invoice_type=Invoice.Invoice_type.GST).order_by(
            "-id"
        )

        # Get Cash invoices
        cash_invoices = invoices.filter(
            invoice_type=Invoice.Invoice_type.CASH
        ).order_by("-id")

        # Calculate totals (amount minus discount)
        gst_total = (
            gst_invoices.aggregate(total=Sum(F("amount") - F("discount_amount")))[
                "total"
            ]
            or 0
        )
        cash_total = (
            cash_invoices.aggregate(total=Sum(F("amount") - F("discount_amount")))[
                "total"
            ]
            or 0
        )

        context = {
            "gst_invoices": gst_invoices,
            "cash_invoices": cash_invoices,
            "gst_total": gst_total,
            "cash_total": cash_total,
            "start_date": start_date.strftime("%b %d, %Y"),
            "end_date": end_date.strftime("%b %d, %Y"),
            "date_range_info": date_range_info,
            "audit_data": audit,
        }

        return render(request, self.template, context)

    @transaction.atomic
    def post(self, request, pk):
        """Handle processing of invoice conversion requests."""
        audit = get_object_or_404(AuditTable, pk=pk)

        try:
            data = json.loads(request.body)
            conversions = data.get("conversions", [])
            date_range = data.get("dateRange", {})
            totals = data.get("totals", {})

            # raise Exception("Not implemented")

            if not conversions:
                return JsonResponse(
                    {"success": False, "error": "No conversions provided"}
                )

            conversion_map = {c["id"]: c for c in conversions}
            invoice_ids = list(conversion_map.keys())
            # 🔑 Bulk fetch invoices at once (avoid N+1 queries)
            invoices = {
                inv.id: inv for inv in Invoice.objects.filter(id__in=invoice_ids)
            }

            converted_count = 0
            conversion_log = []

            # # Process each conversion
            for invoice_id, conversion in conversion_map.items():
                invoice = invoices.get(invoice_id)
                if not invoice:
                    conversion_log.append(
                        {
                            "invoice_id": invoice_id,
                            "invoice_number": conversion.get(
                                "invoiceNumber", "Unknown"
                            ),
                            "conversion": conversion["conversionDirection"],
                            "status": "error",
                            "error": "Invoice not found",
                        }
                    )
                    continue

                try:
                    new_invoice_type = (
                        Invoice.Invoice_type.GST
                        if conversion["currentSection"] == "gst"
                        else Invoice.Invoice_type.CASH
                    )

                    if invoice.invoice_type == new_invoice_type:
                        # No change needed, skip
                        continue

                    # Save original details for audit
                    original_invoice_no = invoice.invoice_number
                    original_invoice_type = invoice.invoice_type

                    # Update invoice fields based on conversion direction
                    apply_conversion(invoice, conversion["conversionDirection"])

                    invoice.save()

                    # Audit record
                    InvoiceAudit.objects.create(
                        invoice=invoice,
                        audit_table=audit,
                        old_invoice_no=original_invoice_no,
                        new_invoice_no=invoice.invoice_number,
                        changed_by=request.user,
                        reason=f"Type conversion: {conversion['conversionDirection']}",
                        change_type="CONVERSION",
                        old_invoice_type=original_invoice_type,
                        new_invoice_type=new_invoice_type,
                    )

                    converted_count += 1
                    conversion_log.append(
                        {
                            "invoice_id": invoice_id,
                            "invoice_number": invoice.invoice_number,
                            "conversion": conversion["conversionDirection"],
                            "status": "success",
                        }
                    )

                except Exception as e:  # pylint: disable=broad-except
                    conversion_log.append(
                        {
                            "invoice_id": invoice_id,
                            "invoice_number": invoice.invoice_number,
                            "conversion": conversion["conversionDirection"],
                            "status": "error",
                            "error": str(e),
                        }
                    )

            # get minimum id

            min_id = min(invoice_ids)
            first_invoice = invoices[min_id]
            resequence_result = resequence_invoices(
                first_invoice.financial_year,
                request.user,
                audit,
                "Resequence after conversion",
            )

            # Prepare response
            return JsonResponse(
                {
                    "success": True,
                    "converted_count": converted_count,
                    "total_conversions": len(conversions),
                    "conversion_log": conversion_log,
                    "date_range": date_range,
                    "totals": totals,
                    "resequence": resequence_result,
                    "message": f"Successfully converted {converted_count} out of {len(conversions)} invoices",
                }
            )

        except json.JSONDecodeError as e:
            logger.error("Invalid JSON data: %s", e)
            return JsonResponse({"success": False, "error": "Invalid JSON data"})
        except Exception as e:  # pylint: disable=broad-except
            transaction.set_rollback(True)
            return JsonResponse({"success": False, "error": f"Server error: {str(e)}"})


@required_permission("invoice.view_audittable")
def audit_detail(request, pk):
    """View audit table details"""
    audit_table = get_object_or_404(AuditTable, pk=pk)

    context = {"audit_table": audit_table}
    return render(request, "invoice_audit/detail.html", context)


def fetch_audit_details(request, pk):
    """AJAX endpoint to fetch and sort audit details"""
    audit_table = get_object_or_404(AuditTable, pk=pk)

    sort_fields = [
        "id",
        "-id",
        "invoice__invoice_number",
        "-invoice__invoice_number",
        "created_at",
        "-created_at",
        "old_invoice_no",
        "-old_invoice_no",
        "new_invoice_no",
        "-new_invoice_no",
        "change_type",
        "-change_type",
    ]

    # Apply sorting

    valid_sorts = table_sorting(request, sort_fields, "-id")
    invoice_audits = audit_table.invoice_audits.select_related(
        "invoice", "changed_by"
    ).order_by(*valid_sorts)

    return render_paginated_response(
        request,
        invoice_audits,
        "invoice_audit/fetch_details.html",
    )


@required_permission("invoice.delete_audittable")
def audit_delete(request, pk):
    """Delete audit table"""
    audit_table = get_object_or_404(AuditTable, pk=pk)

    if request.method == "POST":
        audit_table.delete()
        messages.success(request, "Audit session deleted successfully!")
        return redirect("invoice:audit_home")

    context = {
        "audit_table": audit_table,
    }
    return render(request, "invoice_audit/delete.html", context)
