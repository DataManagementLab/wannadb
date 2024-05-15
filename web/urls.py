from django.urls import path

from . import views

urlpatterns = [
    path("", views.IndexView.as_view(), name="index"),
    path("collection/<slug:slug>/", views.CollectionView.as_view(), name="collection"),
    path("document/<slug:slug>/", views.DocumentView.as_view(), name="document"),
]
