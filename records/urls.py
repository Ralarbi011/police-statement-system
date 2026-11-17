from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("people/", views.person_list, name="person_list"),
    path("people/new/", views.person_create, name="person_create"),
    path("people/<int:pk>/", views.person_detail, name="person_detail"),
    path("people/<int:pk>/edit/", views.person_edit, name="person_edit"),
    path("cases/", views.case_list, name="case_list"),
    path("cases/new/", views.case_create, name="case_create"),
    path("cases/<int:pk>/", views.case_detail, name="case_detail"),
    path("cases/<int:pk>/edit/", views.case_edit, name="case_edit"),
    path("cases/<int:pk>/assign/", views.case_assign, name="case_assign"),
    path("cases/<int:pk>/status/", views.case_status, name="case_status"),
    path("cases/<int:pk>/parties/add/", views.case_add_party, name="case_add_party"),
    path("cases/<int:pk>/notes/add/", views.case_add_note, name="case_add_note"),
    path("cases/<int:case_pk>/statements/new/", views.statement_create, name="statement_create"),
    path("cases/<int:case_pk>/attachments/new/", views.attachment_upload, name="attachment_upload"),
    path("statements/<int:pk>/", views.statement_detail, name="statement_detail"),
    path("statements/<int:pk>/edit/", views.statement_edit, name="statement_edit"),
    path("statements/<int:pk>/sign/", views.statement_sign, name="statement_sign"),
    path("statements/<int:pk>/print/", views.statement_print, name="statement_print"),
    path("attachments/<int:pk>/download/", views.attachment_download, name="attachment_download"),
]
