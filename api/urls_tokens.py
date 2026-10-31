from django.urls import path

from . import views_tokens

app_name = "api_tokens"

urlpatterns = [
    path("", views_tokens.home, name="home"),
    path("fetch/", views_tokens.fetch_tokens, name="fetch"),
    path("create/", views_tokens.create_token, name="create"),
    path("<uuid:pk>/", views_tokens.token_detail, name="detail"),
    path("<uuid:pk>/revoke/", views_tokens.revoke_token, name="revoke"),
]
