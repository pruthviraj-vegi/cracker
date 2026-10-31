"""
Utility and views for direct raw socket TCP network receipt printing.
"""

import socket
import logging
import textwrap
from num2words import num2words

logger = logging.getLogger(__name__)


def send_to_network_printer(ip_address, port, data_bytes):
    """
    Sends raw bytes directly to a network printer at the given IP and port.
    Returns (success: bool, error_message: str)
    """
    try:
        # Establish connection with a 5-second timeout
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5.0)
            s.connect((ip_address, int(port)))
            s.sendall(data_bytes)
            return True, ""
    except socket.timeout:
        msg = f"Connection timed out. Please check if the printer is on and connected at IP {ip_address}."
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"Could not connect to printer at {ip_address}:{port}. Error: {str(e)}"
        logger.error(msg)
        return False, msg


def get_amount_in_words(amount):
    """
    Converts a numeric amount to Indian Rupees in words.
    """
    try:
        words = num2words(
            float(amount), lang="en_IN", to="currency", currency="INR"
        ).title()
        return words
    except Exception as e:
        logger.error(f"Error converting amount {amount} to words: {e}")
        return ""


def format_two_columns(left_str, right_str, width):
    """
    Formats two strings to fit side-by-side in a line of the given width.
    """
    left_str = left_str or ""
    right_str = right_str or ""

    half_width = width // 2
    left_max = half_width - 1
    right_max = width - half_width - 1

    left_part = left_str[:left_max].ljust(left_max)
    right_part = right_str[:right_max].ljust(right_max)

    return f"{left_part}  {right_part}"


def format_table_row(name, qty, price, total, width):
    """
    Formats item details into a single row of the given width.
    """
    name = name or ""
    qty = qty or ""
    price = price or ""
    total = total or ""

    if width == 32:
        # Narrow format
        name_part = name[:11].ljust(11)
        qty_part = qty.rjust(5)
        price_part = price.rjust(7)
        total_part = total.rjust(6)
        return f"{name_part} {qty_part} {price_part} {total_part}"
    else:
        # Standard 80mm format (width = 48)
        name_part = name[:20].ljust(20)
        qty_part = qty.rjust(6)
        price_part = price.rjust(9)
        total_part = total.rjust(10)
        return f"{name_part} {qty_part} {price_part} {total_part}"


def format_tax_row(rate, taxable, cgst, sgst, total, width):
    """
    Formats a row of CGST/SGST tax details.
    """
    if width == 32:
        # Rate: 5, Taxable: 8, CGST: 6, SGST: 6, Total: 7 -> 32 chars
        return f"{rate:<5}{taxable:>8}{cgst:>6}{sgst:>6}{total:>7}"
    else:
        # Rate: 8, Taxable: 12, CGST: 9, SGST: 9, Total: 10 -> 48 chars
        return f"{rate:<8}{taxable:>12}{cgst:>9}{sgst:>9}{total:>10}"


def format_tax_row_igst(rate, taxable, igst, total, width):
    """
    Formats a row of IGST tax details.
    """
    if width == 32:
        # Rate: 6, Taxable: 10, IGST: 8, Total: 8 -> 32 chars
        return f"{rate:<6}{taxable:>10}{igst:>8}{total:>8}"
    else:
        # Rate: 10, Taxable: 14, IGST: 12, Total: 12 -> 48 chars
        return f"{rate:<10}{taxable:>14}{igst:>12}{total:>12}"


def make_escpos_qr_code(data):
    """
    Generates ESC/POS commands to print a QR code with the given data.
    """
    GS = b"\x1d"
    buf = bytearray()

    # 1. Set QR Code model to Model 2
    buf.extend(GS + b"(k\x04\x00\x31\x41\x32\x00")

    # 2. Set module size to 6 dots
    buf.extend(GS + b"(k\x03\x00\x31\x43\x06")

    # 3. Set error correction level to M
    buf.extend(GS + b"(k\x03\x00\x31\x44\x31")

    # 4. Store data in symbol storage area
    data_bytes = data.encode("ascii", errors="ignore")
    len_data = len(data_bytes) + 3
    pL = len_data & 0xFF
    pH = (len_data >> 8) & 0xFF
    buf.extend(GS + b"(k" + bytes([pL, pH]) + b"\x31\x50\x30" + data_bytes)

    # 5. Print QR Code symbol
    buf.extend(GS + b"(k\x03\x00\x31\x51\x30")

    return bytes(buf)


def format_invoice_for_direct_print(invoice, shop_details, report_config, width=48):
    """
    Formats an invoice into ESC/POS bytes for thermal printing.
    """
    ESC = b"\x1b"
    GS = b"\x1d"

    init = ESC + b"@"  # Initialize printer
    center = ESC + b"a\x01"  # Centered alignment
    left = ESC + b"a\x00"  # Left alignment
    right = ESC + b"a\x02"  # Right alignment
    bold_on = ESC + b"E\x01"  # Bold text on
    bold_off = ESC + b"E\x00"  # Bold text off
    normal_size = ESC + b"!\x00"  # Normal size
    bold_double_size = ESC + b"!\x38"  # Bold + Double Width + Double Height

    buf = bytearray()
    buf.extend(init)

    # 1. Shop Header
    if report_config.show_shop_name and shop_details:
        buf.extend(center + bold_double_size)
        buf.extend(shop_details.shop_name.encode("ascii", errors="ignore") + b"\n")
        buf.extend(normal_size)

    if report_config.show_address and shop_details:
        buf.extend(center + normal_size)
        buf.extend(
            shop_details.address_line_one.encode("ascii", errors="ignore") + b"\n"
        )
        buf.extend(
            shop_details.address_line_two.encode("ascii", errors="ignore") + b"\n"
        )

    if report_config.show_contact and shop_details:
        buf.extend(center)
        buf.extend(
            f"Ph: {shop_details.contact_info}".encode("ascii", errors="ignore") + b"\n"
        )

    if report_config.show_gst and shop_details and shop_details.gst_no:
        buf.extend(center)
        buf.extend(
            f"GST: {shop_details.gst_no}".encode("ascii", errors="ignore") + b"\n"
        )

    # Divider
    buf.extend(left + normal_size)
    buf.extend((b"-" * width) + b"\n")

    # 2. Invoice & Customer Details in Two Columns
    left_lines = [
        f"Bill No: {invoice.invoice_number}",
        f"Date: {invoice.invoice_date.strftime('%Y-%m-%d %H:%M')}",
        f"Type: {invoice.get_payment_type_display()}",
    ]

    right_lines = []
    if report_config.show_customer_details and invoice.customer:
        right_lines.append(f"Cust: {invoice.customer.name}")
        if invoice.customer.phone_number:
            right_lines.append(f"Mob: {invoice.customer.phone_number}")

    max_lines = max(len(left_lines), len(right_lines))
    for i in range(max_lines):
        l_text = left_lines[i] if i < len(left_lines) else ""
        r_text = right_lines[i] if i < len(right_lines) else ""
        line_str = format_two_columns(l_text, r_text, width)
        buf.extend(line_str.encode("ascii", errors="ignore") + b"\n")

    # Divider
    buf.extend((b"-" * width) + b"\n")

    # 3. Items Table Header
    header_str = format_table_row("Item Name", "Qty", "Price", "Total", width)
    buf.extend(header_str.encode("ascii", errors="ignore") + b"\n")
    buf.extend((b"-" * width) + b"\n")

    # Items List
    for item in invoice.invoice_items.all():
        variant_name = item.product_variant.product.brand
        if item.product_variant.simple_name:
            variant_name += f" - {item.product_variant.simple_name}"

        qty_str = f"{item.quantity:.2f}"
        price_str = f"{item.unit_price:.2f}"
        amount_str = f"{item.amount:.2f}"

        row_str = format_table_row(variant_name, qty_str, price_str, amount_str, width)
        buf.extend(row_str.encode("ascii", errors="ignore") + b"\n")

    # Divider
    buf.extend((b"-" * width) + b"\n")

    # 4. Summary Calculations (Right Aligned)
    def add_summary_line(label, value_str):
        line_label = f"{label}:"
        space_needed = width - len(line_label) - len(value_str)
        if space_needed > 0:
            line = line_label + (" " * space_needed) + value_str
        else:
            line = line_label + " " + value_str
        return line.encode("ascii", errors="ignore") + b"\n"

    if invoice.discount_amount > 0:
        buf.extend(add_summary_line("Sub Total", f"{invoice.amount:.2f}"))
        buf.extend(add_summary_line("Discount", f"-{invoice.discount_amount:.2f}"))
    else:
        buf.extend(add_summary_line("Total", f"{invoice.amount:.2f}"))

    if invoice.advance_amount > 0:
        buf.extend(
            add_summary_line("Advance Received", f"-{invoice.advance_amount:.2f}")
        )

    # Final Balance (Highlighted next line as AMOUNT)
    # Divider
    buf.extend((b"-" * width) + b"\n")

    buf.extend(center + bold_double_size)
    buf.extend(
        f"AMOUNT: {invoice.net_amount_due:.2f}\n".encode("ascii", errors="ignore")
    )
    buf.extend(normal_size + left)

    # Divider
    buf.extend((b"-" * width) + b"\n")

    # Amount in Words
    amt_words = get_amount_in_words(invoice.total_payable)
    if amt_words:
        buf.extend(f"Words: {amt_words}\n".encode("ascii", errors="ignore"))
        buf.extend((b"-" * width) + b"\n")

    # Tax Details (Compact inline list)
    tax_data = invoice.tax_values_by_gst
    if tax_data and tax_data.get("details"):
        is_cgst_sgst = invoice.gst_type == "CGST_SGST"
        lines = []
        for gst, vals in tax_data["details"].items():
            taxable = vals["tax_value"]
            tax_amt = vals["total_tax_value"]
            if is_cgst_sgst:
                cgst = tax_amt / 2
                sgst = tax_amt / 2
                lines.append(
                    f"GST {gst:.1f}% (Txbl:{taxable:.2f} CGST:{cgst:.2f} SGST:{sgst:.2f})"
                )
            else:
                lines.append(f"GST {gst:.1f}% (Txbl:{taxable:.2f} IGST:{tax_amt:.2f})")
        if lines:
            buf.extend(b"Tax Details:\n")
            for line in lines:
                buf.extend(line.encode("ascii", errors="ignore") + b"\n")
            buf.extend((b"-" * width) + b"\n")

    # 5. UPI QR Code
    if report_config.show_qr_code and shop_details:
        upi_method = shop_details.payment_methods.filter(
            is_active=True, payment_type="UPI"
        ).first()
        if upi_method and upi_method.upi_id:
            upi_uri = f"upi://pay?pa={upi_method.upi_id}&pn={shop_details.shop_name}&am={invoice.net_amount_due:.2f}&cu=INR"
            buf.extend(center)
            buf.extend(b"Scan to Pay:\n")
            buf.extend(make_escpos_qr_code(upi_uri))
            buf.extend(upi_method.upi_id.encode("ascii", errors="ignore") + b"\n")
            buf.extend(left)

    # 6. Terms & Conditions
    if report_config.show_terms_conditions:
        terms = report_config.terms_conditions or report_config.default_terms_conditions
        buf.extend(center + normal_size)
        buf.extend(b"Terms & Conditions:\n")
        for line in terms.split("\n"):
            line = line.strip()
            if line:
                buf.extend(line.encode("ascii", errors="ignore") + b"\n")
        buf.extend(left)

    # 7. Thank You Note
    if report_config.show_thank_you:
        thank_you = (
            report_config.thank_you_message or report_config.default_thank_you_message
        )
        buf.extend(center + bold_on)
        buf.extend(thank_you.encode("ascii", errors="ignore") + b"\n")
        buf.extend(bold_off + left)

    # Line feeds and cut
    buf.extend(b"\n\n\n")
    buf.extend(GS + b"V\x42\x00")  # Feed paper and cut

    return bytes(buf)


def format_estimate_for_direct_print(cart, shop_details, report_config, width=48):
    """
    Formats a cart/estimate into ESC/POS bytes for thermal printing.
    """
    ESC = b"\x1b"
    GS = b"\x1d"

    init = ESC + b"@"
    center = ESC + b"a\x01"
    left = ESC + b"a\x00"
    right = ESC + b"a\x02"
    bold_on = ESC + b"E\x01"
    bold_off = ESC + b"E\x00"
    normal_size = ESC + b"!\x00"
    bold_double_size = ESC + b"!\x38"

    buf = bytearray()
    buf.extend(init)

    # Shop Header
    if report_config.show_shop_name and shop_details:
        buf.extend(center + bold_double_size)
        buf.extend(shop_details.shop_name.encode("ascii", errors="ignore") + b"\n")
        buf.extend(normal_size)

    if report_config.show_address and shop_details:
        buf.extend(center + normal_size)
        buf.extend(
            shop_details.address_line_one.encode("ascii", errors="ignore") + b"\n"
        )
        buf.extend(
            shop_details.address_line_two.encode("ascii", errors="ignore") + b"\n"
        )

    # Divider
    buf.extend(left + normal_size)
    buf.extend((b"-" * width) + b"\n")

    # Title
    buf.extend(center + bold_on)
    buf.extend(f"ESTIMATE - {cart.name}\n".encode("ascii", errors="ignore"))
    buf.extend(bold_off + left)

    # Details in Two Columns
    left_lines = [
        f"Est No: EST-{cart.id}",
        f"Date: {cart.created_at.strftime('%Y-%m-%d %H:%M')}",
    ]

    max_lines = len(left_lines)
    for i in range(max_lines):
        line_str = format_two_columns(left_lines[i], "", width)
        buf.extend(line_str.encode("ascii", errors="ignore") + b"\n")

    # Divider
    buf.extend((b"-" * width) + b"\n")

    # Table Header
    header_str = format_table_row("Item Name", "Qty", "Price", "Total", width)
    buf.extend(header_str.encode("ascii", errors="ignore") + b"\n")
    buf.extend((b"-" * width) + b"\n")

    # Items List
    for item in cart.cart_items.all():
        variant_name = item.product_variant.product.brand
        if item.product_variant.simple_name:
            variant_name += f" - {item.product_variant.simple_name}"

        qty_str = f"{item.quantity:.2f}"
        price_str = f"{item.price:.2f}"
        amount_str = f"{item.amount():.2f}"

        row_str = format_table_row(variant_name, qty_str, price_str, amount_str, width)
        buf.extend(row_str.encode("ascii", errors="ignore") + b"\n")

    # Divider
    buf.extend((b"-" * width) + b"\n")

    # Summary
    def add_summary_line(label, value_str):
        line_label = f"{label}:"
        space_needed = width - len(line_label) - len(value_str)
        if space_needed > 0:
            line = line_label + (" " * space_needed) + value_str
        else:
            line = line_label + " " + value_str
        return line.encode("ascii", errors="ignore") + b"\n"

    buf.extend(add_summary_line("Sub Total", f"{cart.total_amount:.2f}"))
    if cart.advance_payment > 0:
        buf.extend(add_summary_line("Advance Received", f"{cart.advance_payment:.2f}"))

    # Final Balance (Highlighted next line as AMOUNT)
    buf.extend(b"\n")
    buf.extend(center + bold_double_size)
    buf.extend(f"AMOUNT: {cart.net_amount:.2f}\n".encode("ascii", errors="ignore"))
    buf.extend(normal_size + left)

    # Divider
    buf.extend((b"-" * width) + b"\n")

    # Thank you note
    if report_config.show_thank_you:
        thank_you = (
            report_config.thank_you_message or report_config.default_thank_you_message
        )
        buf.extend(center + bold_on)
        buf.extend(thank_you.encode("ascii", errors="ignore") + b"\n")
        buf.extend(bold_off + left)

    # Line feeds and cut
    buf.extend(b"\n\n\n\n")
    buf.extend(GS + b"V\x42\x00")

    return bytes(buf)
