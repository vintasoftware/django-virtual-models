from django.urls import path

from movies import views

urlpatterns = [
    path("", views.MovieList.as_view(), name="list"),
]
