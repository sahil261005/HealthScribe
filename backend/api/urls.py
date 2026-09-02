from django.urls import path
from django.http import JsonResponse
from rest_framework_simplejwt.views import TokenRefreshView
from .views import SaveRecordView, RegisterView, ProfileView, GenerateShareLinkView, SharedReportView, CustomTokenObtainPairView

def api_health(request):
    return JsonResponse({"status": "ok", "service": "django_api"})

urlpatterns = [
    path('health/', api_health, name='api_health_slash'),
    path('health', api_health, name='api_health'),

    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/profile/', ProfileView.as_view(), name='profile'),

    path('save_record/', SaveRecordView.as_view(), name='save_record'),

    path('share/generate/', GenerateShareLinkView.as_view(), name='generate_share_link'),
    path('share/<uuid:token>/', SharedReportView.as_view(), name='shared_report'),
]

