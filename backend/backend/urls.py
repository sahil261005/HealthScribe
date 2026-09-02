from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse

def health_check(request):
    return JsonResponse({"status": "ok", "service": "django_backend"})

urlpatterns = [
    path('', health_check, name='root_health'),
    path('health/', health_check, name='health_slash'),
    path('health', health_check, name='health'),
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
]

