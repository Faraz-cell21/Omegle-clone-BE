from django.urls import path

from moderation.views import AdminDashboardView, SoftBanIPView


urlpatterns = [
    path("admin/dashboard/", AdminDashboardView.as_view(), name="admin-dashboard"),
    path("admin/soft-ban/", SoftBanIPView.as_view(), name="admin-soft-ban"),
]
