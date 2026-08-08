# apps/core/utils.py
from decimal import Decimal
from apps.accounts.models import CompanySetting

def get_vat_rate(company):
    """
    Fetches the VAT rate for a specific company.
    Returns 0 if VAT is disabled or settings don't exist.
    """
    if not company:
        return Decimal('0')
    
    try:
        setting = CompanySetting.objects.get(company=company)
        return setting.vat_percentage if setting.enable_vat else Decimal('0')
    except CompanySetting.DoesNotExist:
        # Fallback for companies without settings configured yet
        return Decimal('13.00') 