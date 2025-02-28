from django.urls import path

from . import views

urlpatterns = [
    path("", views.IndexView.as_view(), name="index"),
    path("collection/<slug:slug>/", views.CollectionView.as_view(), name="collection"),
    path("collection/<slug:slug>/add_attribute/", views.AddAttributeView.as_view(), name="add_attribute"),
    path("attribute/<pk>/populate/", views.PopulateInitialView.as_view(), name="populate_attribute"),
    path("document/<slug:slug>/", views.DocumentView.as_view(), name="document"),
]
