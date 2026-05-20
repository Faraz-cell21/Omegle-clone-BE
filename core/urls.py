from django.urls import path

from core.views import LoginView, LogoutView, RegisterAdminView


urlpatterns = [
    path("auth/register-admin/", RegisterAdminView.as_view(), name="register-admin"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
]
