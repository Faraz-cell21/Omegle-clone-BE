from django.urls import path

from core.views import (
    CaptchaVerifyView,
    HealthCheckView,
    LoginView,
    LogoutView,
    RegisterAdminView,
)


urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("captcha/verify/", CaptchaVerifyView.as_view(), name="captcha-verify"),
    path("auth/register-admin/", RegisterAdminView.as_view(), name="register-admin"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
]
