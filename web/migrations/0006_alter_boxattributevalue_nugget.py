# Generated by Django 5.0.6 on 2024-05-15 13:58

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('web', '0005_alter_boxattributevalue_unique_together'),
    ]

    operations = [
        migrations.AlterField(
            model_name='boxattributevalue',
            name='nugget',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='web.nugget'),
        ),
    ]
