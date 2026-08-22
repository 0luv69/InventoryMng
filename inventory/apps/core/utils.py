# apps/core/utils.py
import re
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
    
def next_reference_number(company, model, prefix):
    """
    Returns the next free reference number: prefix + zero-padded number.
    Scans refs that are exactly prefix+digits and takes max+1, so manual/odd
    refs ('PUR-2025-001', 'URGENT') never break the sequence.
    Used by: purchase ('PUR-'), sale ('SAL-'), payment ('PAY-').
    """
    pattern = re.compile(rf'^{re.escape(prefix)}(\d+)$')
    max_num = 0
    for ref in model.objects.filter(company=company, reference_no__startswith=prefix).values_list('reference_no', flat=True):
        m = pattern.match(ref)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"{prefix}{max_num + 1:04d}"

def _net_cost(p):
    return p['gross_cost'] / p['_multiplier'] if (p['is_vat_applicable'] and p.get('_inclusive')) else p['gross_cost']

def _stored_disc(p):
    """Discount value as stored on the line: fixed amounts get netted
    (VATable + inclusive only), percentage stored exactly as typed."""
    if p['discount_type'] != 'fixed':
        return p['discount_amount_gross']
    if p['is_vat_applicable'] and p['_inclusive']:
        return p['discount_amount_gross'] / p['_multiplier']
    return p['discount_amount_gross']

def _net_disc_value(p):
    """Money VALUE of the discount in net terms — ratio math only."""
    if p['discount_type'] == 'fixed':
        return _stored_disc(p)
    return p['qty_val'] * _net_cost(p) * p['discount_amount_gross'] / Decimal('100')