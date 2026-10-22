from django.urls import path
from foundation.health import live, ready
from catalog import http, read_http, research_http, control_http

urlpatterns = [path("health/live/", live), path("health/ready/", ready)]

urlpatterns += [
    path("api/v2/runs/<uuid:identity>/cancel", control_http.cancel_run),
    path("api/v2/runs/<uuid:identity>/events", control_http.run_events),
    path("api/v2/research-versions/<uuid:identity>/events", control_http.research_events),
    path("api/v2/research-versions/<uuid:identity>/runs", research_http.runs),
    path("api/v2/researches", research_http.researches),
    path("api/v2/researches/<uuid:identity>", research_http.research_detail),
    path("api/v2/researches/<uuid:identity>/versions", research_http.versions),
    path("api/v2/research-versions/<uuid:identity>", research_http.version_detail),
    path("api/v2/research-versions/<uuid:identity>/validate", research_http.validate_draft),
    path("api/v2/datasets/<uuid:identity>/versions", read_http.versions),
    path("api/v2/runs/<uuid:identity>", read_http.run_detail),
    path("api/v2/evidence-bundles/<uuid:identity>", read_http.evidence_bundle_detail),
    path("api/v2/frozen-submissions/<uuid:identity>", read_http.frozen_submission_detail),
    path("api/v2/artifacts/<uuid:identity>", read_http.artifact_detail),
    path("api/v2/artifacts/<uuid:identity>/content", read_http.artifact_content),
    path("auth/login", http.login_view), path("auth/logout", http.logout_view),
    path("api/v2/datasets", http.datasets), path("api/v2/datasets/<uuid:identity>/uploads", http.uploads),
    path("api/v2/uploads/<uuid:identity>/complete", http.complete), path("storage/uploads/<uuid:identity>", http.upload_bytes),
]

handler400 = "catalog.http.bad_request"
handler404 = "catalog.http.not_found"
handler500 = "catalog.http.server_error"
