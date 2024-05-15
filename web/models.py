from django.db import models


class Collection(models.Model):
    class Meta:
        verbose_name = "Collection"
        verbose_name_plural = "Collections"

    name = models.CharField(max_length=255)
    slug = models.SlugField()
    docbase_file_path = models.FilePathField(path="/", allow_files=False, allow_folders=True, blank=True)

    def __str__(self):
        return self.name


class Document(models.Model):
    class Meta:
        verbose_name = "Document"
        verbose_name_plural = "Documents"

    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    text = models.TextField()
    slug = models.SlugField()
    box_rows = models.ManyToManyField("BoxAttribute", through="BoxAttributeValue")

    def __str__(self):
        return f"{self.title} ({self.collection.name})"

    @property
    def box(self):
        return BoxAttributeValue.objects.filter(document=self).all().order_by('box_attribute__name')


class BoxAttribute(models.Model):
    class Meta:
        verbose_name = "Box Attribute"
        verbose_name_plural = "Box Attributes"

    name = models.CharField(max_length=255)
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.name} ({self.collection.name})"


class NuggetLabel(models.Model):
    class Meta:
        verbose_name = "Nugget Label"
        verbose_name_plural = "Nugget Labels"

    name = models.CharField(max_length=255)
    color = models.CharField(default='#000000', max_length=7)

    def __str__(self):
        return self.name


class Nugget(models.Model):
    class Meta:
        verbose_name = "Nugget"
        verbose_name_plural = "Nuggets"

    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    value = models.CharField(max_length=255)
    start = models.PositiveIntegerField()
    end = models.PositiveIntegerField()
    label = models.ForeignKey(NuggetLabel, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.value} ({self.document.title}: {self.start}-{self.end})"


class BoxAttributeValue(models.Model):
    class Meta:
        verbose_name = "Box Attribute Value"
        verbose_name_plural = "Box Attribute Values"
        unique_together = ("box_attribute", "document")

    box_attribute = models.ForeignKey(BoxAttribute, on_delete=models.CASCADE)
    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    upvotes = models.IntegerField(default=0, blank=True)
    downvotes = models.IntegerField(default=0, blank=True)
    manually_confirmed = models.BooleanField(default=False, blank=True)
    nugget = models.ForeignKey(Nugget, on_delete=models.SET_NULL, null=True, blank=True)
    confidence = models.FloatField(default=0.0, blank=True)

    def __str__(self):
        if self.nugget is None:
            return f"[{self.document}] {self.box_attribute}: --"
        return f"[{self.document}] {self.box_attribute}: {self.nugget.value} ({self.nugget.start}-{self.nugget.end}))"

    @property
    def value(self):
        if self.nugget is not None:
            return self.nugget.value
        return "--"

    @property
    def votes(self):
        return self.upvotes - self.downvotes
