from django.urls import re_path as url
from django.contrib.auth.decorators import login_required
from .views import RedirectToAngular

urlpatterns = [
    url(r'',view= login_required(RedirectToAngular.as_view()), name='ang-app' )
]