from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_remove_item_supplier_purchaseinvoice_supplier"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="feature_flags",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="company",
            name="tax_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="company",
            name="tax_label",
            field=models.CharField(default="VAT", max_length=30),
        ),
        migrations.AddField(
            model_name="company",
            name="tax_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="tax_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="purchaseinvoice",
            name="tax_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AddField(
            model_name="purchaseitem",
            name="tax_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="purchaseitem",
            name="tax_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AddField(
            model_name="saleinvoice",
            name="tax_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="saleinvoice",
            name="tax_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AddField(
            model_name="saleitem",
            name="tax_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="saleitem",
            name="tax_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
    ]
