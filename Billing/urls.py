"""
URL configuration for Billing project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("user/", include("user.urls")),
    path("security/", include("security.urls")),
    path("", include("base.urls")),
    path("customer/", include("customer.urls")),
    path("supplier/", include("supplier.urls")),
    path("inventory/", include("inventory.urls")),
    path("inventory/products/", include("inventory.urls_products")),
    path("inventory/products/variants/", include("inventory.urls_variant")),
    path("inventory/bulk-upload/", include("inventory.urls_bulk_upload")),
    path("cart/", include("cart.urls")),
    path("invoice/", include("invoice.urls")),
    path("report/", include("report.urls")),
    path("setting/", include("setting.urls")),
    path("suggestions/", include("base.urls_suggestions")),
    path("api/", include("api.urls")),
    path("api-tokens/", include("api.urls_tokens")),
    path("notifications/", include("notification.urls")),
]

handler404 = "base.views.custom_404_view"

# Serve media files during development
# Static files from STATICFILES_DIRS are automatically served by django.contrib.staticfiles
# when DEBUG=True and using 'runserver'. No collectstatic needed in development!
# In production (DEBUG=False), run collectstatic to gather files into STATIC_ROOT
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
