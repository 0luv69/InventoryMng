from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Company(TimeStampedModel):
    CURRENCY_CHOICES = [
        ("NPR", "NPR"),
        ("INR", "INR"),
        ("USD", "USD"),
    ]

    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    logo = models.ImageField(upload_to="company_logos/", null=True, blank=True)

    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, blank=True)


    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="NPR")
    low_stock_threshold = models.PositiveIntegerField(default=20, validators=[MinValueValidator(1)])
    fiscal_year_start = models.CharField(max_length=20, default="shrawan")
    tax_id = models.CharField(max_length=50, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class UserProfile(TimeStampedModel):
    """
    Keep default Django User, link it to company here.
    One user belongs to one company in this MVP.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="users", null=True, blank=True)
    phone_num = models.CharField(max_length=30, blank=True)
    def __str__(self):
        return f"{self.user} @ {self.company.name}"
    

class RequestDemo(TimeStampedModel):
    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    message = models.TextField(blank=True)
    

    def __str__(self):
        return f"{self.name} ({self.email})"


class Unit(TimeStampedModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="units")
    name = models.CharField(max_length=50)
    short_name = models.CharField(max_length=10)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="uniq_unit_name_per_company"),
            models.UniqueConstraint(fields=["company", "short_name"], name="uniq_unit_short_name_per_company"),
        ]

    def __str__(self):
        return f"{self.name} ({self.short_name})"