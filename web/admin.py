from django.contrib import admin

from web.models import Collection, Document, BoxAttribute, BoxAttributeValue, Nugget, NuggetLabel


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "collection")


@admin.register(BoxAttribute)
class BoxAttributeAdmin(admin.ModelAdmin):
    list_display = ("name", "collection")
    list_filter = ("collection",)


@admin.register(NuggetLabel)
class NuggetLabelAdmin(admin.ModelAdmin):
    list_display = ("name", "color")


@admin.register(Nugget)
class NuggetAdmin(admin.ModelAdmin):
    list_display = ("document", "value", "start", "end")
    list_filter = ("document",)


@admin.register(BoxAttributeValue)
class BoxAttributeValueAdmin(admin.ModelAdmin):
    list_display = ("box_attribute", "document", "value", "manually_confirmed")
