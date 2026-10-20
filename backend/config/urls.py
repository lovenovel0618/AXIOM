from django.urls import path
from foundation.health import live, ready
from catalog import http

urlpatterns = [path("health/live/", live), path("health/ready/", ready)]

urlpatterns += [
    path("auth/login", http.login_view), path("auth/logout", http.logout_view),
    path("api/v2/datasets", http.datasets), path("api/v2/datasets/<uuid:identity>/uploads", http.uploads),
    path("api/v2/uploads/<uuid:identity>/complete", http.complete), path("storage/uploads/<uuid:identity>", http.upload_bytes),
]

handler400 = "catalog.http.bad_request"
handler404 = "catalog.http.not_found"
handler500 = "catalog.http.server_error"
