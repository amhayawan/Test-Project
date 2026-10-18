from django.urls import path

from . import views

urlpatterns = [
    path("available/", views.available, name="cases_available"),
    path("research-form/blank/", views.research_form, name="research_form_blank"),
    path("<int:pk>/research-form/", views.research_form, name="research_form"),
]
