# My_Billing (Billing Software)

A comprehensive Django 5.1-based billing, inventory, and point-of-sale (POS) system tailored for retail and wholesale operations. It handles everything from stock tracking to compliant GST/Non-GST invoicing, customer/supplier management, barcode-driven cart checkouts, and cloud-integrated PDF generation.

---

## Key Features

### Inventory Management

- **Product Catalog**: Manage products, categories, cloth types, and HSN codes
- **Variants Support**: Handle complex stock types using size, color, and dynamic pricing (MRP, Purchase Price, Selling Price)
- **FIFO Costing**: First-In-First-Out inventory costing with automatic COGS calculation
- **Mutations & Tracking**: Full audit trail for Stock In, Stock Out, Adjustments, and Damages using atomic database locks (`select_for_update`) to prevent negative stock
- **Barcode Generation**: Auto-generated structured barcode tags using `python-barcode`
- **Media Management**: Product images/videos with auto-generated WebP thumbnails
- **Low Stock Alerts**: Configurable minimum quantity thresholds
- **Master Data**: Categories (hierarchical), Colors (with hex codes), Sizes, UOM (with conversion factors), GST HSN codes

### Supplier & Purchasing

- **Supplier Management**: Contact details, GSTIN, address tracking
- **Purchase Invoices**: Track supplier invoices with CGST/SGST or IGST tax structures
- **Payment Processing**: Record and allocate payments to supplier invoices
- **Media Attachments**: Attach PDFs and documents to supplier invoices

### Customer Management

- **Customer Database**: Comprehensive customer records with referral linkage
- **Credit Management**: Track credit limits, payments, and outstanding balances
- **Payment Allocation**: Automatic allocation of payments to invoices
- **Customer Statements**: Generate detailed account statements (PDF)
- **Denormalized Summary**: `CustomerCreditSummary` for fast credit balance queries

### Point of Sale (Cart)

- **High-Efficiency Cart**: Session-bound temporary order states for fast checkout
- **Multi-Word Search**: Fuzzy matching using `RapidFuzz` for product suggestions
- **Barcode Scanning**: Direct barcode input for quick item lookup
- **Dynamic Discounting**: Per-item and cart-level discounts
- **Tax Calculations**: Automatic CGST/SGST or IGST calculation
- **Advance Payments**: Track advance payments against future invoices

### Invoicing & Auditing

- **Compliant Invoicing**: Separate GST and CASH invoice sequences by financial year
- **Multi-Tax Support**: CGST/SGST and IGST tax structures
- **Flexible Payment Types**: Cash and Credit payment handling
- **Payment Status Tracking**: Unpaid, Partially Paid, Paid, Void, Cancelled
- **Returns & Cancellations**: Partial/full returns with stock replenishment, different refund types (Store Credit, Cash, Voucher)
- **Invoice Cancellation**: Cancel and resequence invoices for chronological accuracy
- **Comprehensive Audit Trail**: Invoice conversions and renumbering tracking

### Reporting & PDF Generation

- **Pixel-Perfect PDFs**: Generate invoices and statements using `WeasyPrint`
- **Cloud Storage**: Upload PDFs to Cloudflare R2 (S3-compatible storage)
- **Async Generation**: Celery-based async PDF job queue
- **Excel Exports**: Data extraction using `XlsxWriter` and `tablib`
- **Dashboard Metrics**: Real-time sales, inventory, and customer metrics

### Notifications

- **Generic Notifications**: Type-based notification system using Django's GenericForeignKey
- **Registry Pattern**: Extensible notification types without migrations

### Settings & Customization

- **Shop Details**: Business information for invoices/reports
- **Report Configuration**: Per-report display settings (paper size, currency, toggles)
- **Payment Methods**: Multiple payment methods (UPI, Bank, QR) per shop
- **Barcode Configuration**: Label printing preferences

### Security & Sessions

- **Phone-Based Authentication**: Custom user model with phone number as username
- **Inactivity Timeout**: Auto-logout after 3 hours of inactivity
- **Session Management**: Redis-backed session storage
- **Permission System**: Function-based and class-based permission decorators
- **Audit Logging**: Login events and unauthorized access tracking
- **Security Middleware**: CSRF, SSL redirect, HSTS, X-Frame options

---

## Technology Stack

### Backend

- **Framework**: Django 5.1
- **Database**: PostgreSQL with connection pooling
- **Task Queue**: Celery with Redis broker
- **Cache**: Redis (database cache backend)
- **Security**: Strict CSRF handling, session hijacking protection

### Frontend & Assets

- **Styling**: Bootstrap 5 with CSS variables (Light/Dark mode support)
- **Interactivity**: Vanilla JavaScript, jQuery, Select2
- **Charts**: Chart.js for dashboard visualizations

### Key Python Libraries

- `psycopg2-binary`: PostgreSQL adapter
- `celery`: Async task queue
- `redis`: Cache and message broker
- `boto3`: Cloudflare R2 (S3-compatible) integration
- `weasyprint`: PDF generation (63+)
- `python-barcode`: Barcode generation
- `qrcode`: QR code generation for UPI payments
- `num2words`: Number to word conversion (currency)
- `RapidFuzz`: Fuzzy matching for search suggestions
- `XlsxWriter` & `tablib`: Excel exports
- `python-decouple`: Environment variable management
- `django-redis`: Redis cache backend
- `brotli`: Brotli compression for static files

---

## Architecture Overview

```
My_Billing/
├── Billing/           # Django project config (settings, urls, celery, wsgi/asgi)
├── base/              # Shared utilities (currency formatting, pagination, decorators, signals, suggestions)
├── user/               # CustomUser (phone-based auth), Salary, Transaction
├── security/           # LoginEvent, UnauthorizedAccess audit logs
├── customer/           # Customer, Payment, CustomerCreditSummary (denormalized)
├── supplier/           # Supplier, SupplierInvoice, SupplierPayment, SupplierPaymentAllocation, MediaFile
├── inventory/          # Product, ProductVariant, Category, Color, Size, UOM, GSTHsnCode, InventoryLog, services (FIFO)
├── cart/               # Cart, CartItem (temporary pre-invoice collections)
├── invoice/            # Invoice, InvoiceItem, InvoiceSequence, AuditTable, InvoiceAudit, PaymentAllocation, ReturnInvoice, ReturnInvoiceItem, InvoiceCancellation
├── report/             # InvoicePDF, CustomerStatementPDF, PdfJob (async PDF generation)
├── notification/       # Notification (GenericForeignKey), registry, services
├── setting/            # ShopDetails, ReportConfiguration, PaymentDetails, BarcodeConfiguration
├── api/                # External API endpoints (WhatsApp, balance check), Cloudflare R2 integration, PDF services
├── templates/          # Global templates (base, navbar, common, model_forms)
└── static/             # CSS (~156KB), JavaScript modules, icons, images
```

### Design Patterns

- **Fat Models**: Business logic lives in Model definitions; views handle routing only
- **Signal-Driven Side Effects**: Automatic cache invalidation, credit recalculation, audit logging
- **Service Layer**: Dedicated service classes for inventory operations, PDF generation, cloud storage
- **Soft Delete**: All major models support soft delete via `SoftDeleteModel`
- **Mixins**: Reusable behavior (naming, stock, pricing) for ProductVariant

---

## Setup & Development

### Prerequisites

- Python 3.10+
- PostgreSQL
- Redis
- GTK3 Runtime (Required for WeasyPrint on Windows)

### Installation

```bash
# Clone and navigate
git clone <repository-url>
cd My_Billing

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install dependencies
pip install -r require.txt
```

### Environment Configuration

Create a `.env` file:

```env
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=your_db_name
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=127.0.0.1
DB_PORT=5432

CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
REDIS_CACHE_URL=redis://127.0.0.1:6379/1

R2_ACCESS_KEY=your-r2-access-key
R2_SECRET_KEY=your-r2-secret-key
R2_ENDPOINT=your-r2-endpoint
R2_INVOICE_BUCKET=invoices
R2_STATEMENT_BUCKET=statements
R2_INVOICE_PUBLIC_URL=https://your-bucket.cloudflarestorage.com
R2_STATEMENT_PUBLIC_URL=https://your-bucket.cloudflarestorage.com
```

### Database Setup

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createcachetable
```

### Running the Application

```bash
# Start Django server
python manage.py runserver

# Start Celery worker (separate terminal)
celery -A Billing worker -l info
```

Navigate to `http://127.0.0.1:8000`

---

## URL Structure

| Namespace | Description |
|-----------|-------------|
| `""` | Base app (login, dashboard, home) |
| `user/` | User management |
| `security/` | Security audit logs |
| `customer/` | Customer & payment management |
| `supplier/` | Supplier & purchase management |
| `inventory/` | Products, variants, stock |
| `cart/` | POS cart |
| `invoice/` | Invoicing & returns |
| `report/` | PDF reports & exports |
| `setting/` | Configuration |
| `api/` | External API endpoints |
| `notifications/` | Notification system |

---

## Development Guidelines

- **URL Namespacing**: Always namespace app URLs (e.g., `invoice:detail`)
- **Fat Models**: Keep business logic in Models; restrict views to routing
- **Decimal for Money**: Never use `float` for financial calculations
- **Atomic Transactions**: Wrap multi-model writes in `transaction.atomic()`
- **Query Optimization**: Use `select_related`/`prefetch_related` for N+1 prevention
- **Theme Variables**: Use CSS variables for theming instead of hardcoded colors

---

## License

MIT License