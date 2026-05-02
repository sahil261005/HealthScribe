from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import SaveRecordView, RegisterView, ProfileView, GenerateShareLinkView, SharedReportView

urlpatterns = [
    # auth endpoints
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', TokenObtainPairView.as_view(), name='login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/profile/', ProfileView.as_view(), name='profile'),
    
    # medical records
    path('save_record/', SaveRecordView.as_view(), name='save_record'),
    
    # sharing
    path('share/generate/', GenerateShareLinkView.as_view(), name='generate_share_link'),
    path('share/<uuid:token>/', SharedReportView.as_view(), name='shared_report'),
]
