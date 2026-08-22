from decimal import Decimal
from django.test import TestCase
from apps.accounts.models import Company, User, UserProfile
from apps.parties.models import Party
from apps.catalog.models import Item, Unit
from apps.inventory.models import Warehouse, StockBatch
from .models import PurchaseInvoice, PurchaseItemLine, SaleInvoice, SaleItemLine
from .services import InventoryService


def make_line(inv, item, qty, net_cost, vat=True, disc=('fixed', Decimal('0'))):
    return PurchaseItemLine.objects.create(
        company=inv.company, invoice=inv, item=item, created_by=inv.created_by,
        warehouse=Warehouse.objects.get(pk=1), unit=item.base_unit,
        quantity=qty, cost_price=net_cost, is_vat_applicable=vat,
        discount_type=disc[0], discount_amount=disc[1])


class TotalsMath(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('t@t.com', 'x')
        cls.company = Company.objects.create(name='T')
        cls.sup = Party.objects.create(company=cls.company, name='S', is_supplier=True)
        cls.wh = Warehouse.objects.create(company=cls.company, name='Main', created_by=cls.user)
        cls.unit = Unit.objects.create(company=cls.company, name='Pcs', short_name='pc', created_by=cls.user)
        cls.item = Item.objects.create(company=cls.company, name='X', base_unit=cls.unit, created_by=cls.user)

    def invoice(self, **kw):
        return PurchaseInvoice.objects.create(
            company=self.company, supplier=self.sup, date_received='2025-01-01',
            reference_no=kw.pop('ref'), created_by=self.user,
            invoice_status='draft',   # keep stock signals out; we're testing math
            **kw)

    def test_inclusive_vatable_with_fixed_discount(self):
        inv = self.invoice(ref='P1', is_vat_inclusive=True,
                           discount_type='fixed', discount_amount=Decimal('88.50'))  # 100 gross netted
        # 10 x 113 gross -> net 100 each
        make_line(inv, self.item, Decimal('10'), Decimal('100.00'))
        InventoryService.recalculate_invoice_totals(inv)
        inv.refresh_from_db()
        self.assertEqual(inv.subtotal, Decimal('1000.00'))
        self.assertEqual(inv.tax_amount, Decimal('118.50'))
        self.assertEqual(inv.grand_total, Decimal('1030.00'))
        self.assertEqual(inv.round_off, Decimal('0.00'))

    def test_inclusive_mixed_bill_proportional(self):
        inv = self.invoice(ref='P2', is_vat_inclusive=True,
                           discount_type='fixed', discount_amount=Decimal('102.17'))  # 113 gross blended
        make_line(inv, self.item, Decimal('10'), Decimal('100.00'))                 # vatable net 1000
        make_line(inv, self.item, Decimal('226'), Decimal('1.00'), vat=False)       # exempt net 226
        InventoryService.recalculate_invoice_totals(inv)
        inv.refresh_from_db()
        self.assertEqual(inv.grand_total, Decimal('1243.00'))
        self.assertEqual(inv.tax_amount, Decimal('119.17'))

    def test_round_off_toggle(self):
        inv = self.invoice(ref='P3', round_off_enabled=True)
        make_line(inv, self.item, Decimal('10'), Decimal('124.573'))
        InventoryService.recalculate_invoice_totals(inv)
        inv.refresh_from_db()
        # identity must ALWAYS hold:
        taxable = inv.subtotal - inv.discount_amount
        self.assertEqual(inv.grand_total, taxable + inv.tax_amount + inv.round_off)

    def test_percentage_line_discount_survives_save(self):
        """Regression: _net_disc used to store 0 for percentage discounts."""
        inv = self.invoice(ref='P4')
        make_line(inv, self.item, Decimal('10'), Decimal('100.00'),
                  disc=('percentage', Decimal('10')))
        InventoryService.recalculate_invoice_totals(inv)
        inv.refresh_from_db()
        line = inv.lines.first()
        self.assertEqual(line.discount_amount, Decimal('10'))  # <- would fail before the fix
        self.assertEqual(line.line_total, Decimal('900.00'))
        self.assertEqual(inv.subtotal, Decimal('900.00'))
        self.assertEqual(inv.tax_amount, Decimal('117.00'))
        self.assertEqual(inv.grand_total, Decimal('1017.00'))

    def test_inclusive_percentage_line_discount_plus_fixed_header(self):
        """User types: 10 x Rs113 gross, 10% line discount, Rs113 header discount (gross).
        Correct answer: net line 900, net header 100, tax 104, grand 904."""
        inv = self.invoice(ref='P5', is_vat_inclusive=True,
                           discount_type='fixed', discount_amount=Decimal('100.00'))
        make_line(inv, self.item, Decimal('10'), Decimal('100.00'),
                  disc=('percentage', Decimal('10')))
        InventoryService.recalculate_invoice_totals(inv)
        inv.refresh_from_db()
        self.assertEqual(inv.subtotal, Decimal('900.00'))
        self.assertEqual(inv.tax_amount, Decimal('104.00'))
        self.assertEqual(inv.grand_total, Decimal('904.00'))


class VoidAndStockIntegrity(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('v@t.com', 'x')
        cls.company = Company.objects.create(name='V')
        UserProfile.objects.create(user=cls.user, company=cls.company)
        cls.sup = Party.objects.create(company=cls.company, name='S', is_supplier=True)
        cls.cust = Party.objects.create(company=cls.company, name='C', is_customer=True)
        cls.wh = Warehouse.objects.create(company=cls.company, name='Main', created_by=cls.user)
        cls.unit = Unit.objects.create(company=cls.company, name='Pcs', short_name='pc', created_by=cls.user)
        cls.item = Item.objects.create(company=cls.company, name='X', base_unit=cls.unit, created_by=cls.user)

    def purchase(self, ref, qty, cost, batch):
        inv = PurchaseInvoice.objects.create(
            company=self.company, supplier=self.sup, date_received='2025-01-01',
            reference_no=ref, created_by=self.user, invoice_status='finalized')
        PurchaseItemLine.objects.create(
            company=self.company, invoice=inv, item=self.item, created_by=self.user,
            warehouse=self.wh, unit=self.unit, quantity=Decimal(qty),
            cost_price=Decimal(cost), batch_no=batch)
        # Mirror the real (view) flow: a finalized purchase debits the supplier balance.
        # ORM creation alone only moves stock — balance adjustment is view logic.
        inv.refresh_from_db()
        InventoryService.apply_invoice_to_party_balance(inv, 'supplier', sign=-1)
        return inv

    def sale(self, ref, qty):
        inv = SaleInvoice.objects.create(
            company=self.company, customer=self.cust, date_dispatched='2025-01-02',
            reference_no=ref, created_by=self.user, invoice_status='finalized')
        SaleItemLine.objects.create(
            company=self.company, invoice=inv, item=self.item, created_by=self.user,
            warehouse=self.wh, unit=self.unit, quantity=Decimal(qty),
            selling_price=Decimal('150'))
        return inv

    def test_void_blocked_when_stock_sold(self):
        self.purchase('PV1', '10', '100', 'B1')
        self.sale('SV1', '4')
        self.client.force_login(self.user)
        inv = PurchaseInvoice.objects.get(reference_no='PV1')
        resp = self.client.post(f'/goods-in/void/{inv.id}/', {'void_reason': 'oops'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Cannot void', resp.json()['message'])
        self.assertIn('SV1', resp.json()['message'])          # names the blocking sale
        inv.refresh_from_db()
        self.assertEqual(inv.invoice_status, 'finalized')     # untouched
        self.assertEqual(StockBatch.objects.get(batch_no='B1').quantity, Decimal('6'))

    def test_void_restores_stock_balance_and_mac(self):
        self.purchase('PV1', '10', '100', 'B1')
        self.purchase('PV2', '10', '120', 'B2')
        self.item.refresh_from_db()
        self.assertEqual(self.item.cost_price, Decimal('110.00'))  # MAC after both buys
        self.client.force_login(self.user)
        resp = self.client.post('/goods-in/void/%s/' % PurchaseInvoice.objects.get(reference_no='PV2').id, {'void_reason': 'dup'})
        self.assertEqual(resp.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.cost_price, Decimal('100.00'))  # MAC healed
        self.assertEqual(StockBatch.objects.get(batch_no='B2').quantity, Decimal('0'))
        self.sup.refresh_from_db()
        self.assertEqual(self.sup.balance, Decimal('-1130'))      # only PV1's debt remains (1000 + 13% VAT)

    def test_void_when_no_stock_left_keeps_last_cost(self):
        self.purchase('PV1', '10', '100', 'B1')
        self.client.force_login(self.user)
        resp = self.client.post('/goods-in/void/%s/' % PurchaseInvoice.objects.get(reference_no='PV1').id, {'void_reason': 'x'})
        self.assertEqual(resp.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.cost_price, Decimal('100.00'))  # last known cost retained


class RefNumberAssignment(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('r@t.com', 'x')
        cls.company = Company.objects.create(name='R')
        UserProfile.objects.create(user=cls.user, company=cls.company)
        cls.sup = Party.objects.create(company=cls.company, name='S', is_supplier=True)
        cls.wh = Warehouse.objects.create(company=cls.company, name='Main', created_by=cls.user)
        cls.unit = Unit.objects.create(company=cls.company, name='Pcs', short_name='pc', created_by=cls.user)
        cls.item = Item.objects.create(company=cls.company, name='X', base_unit=cls.unit, created_by=cls.user)

    def test_next_reference_number_ignores_weird_refs(self):
        from apps.core.utils import next_reference_number
        for ref in ('PUR-0005', 'PUR-2025-999', 'URGENT'):   # odd formats must not break the sequence
            PurchaseInvoice.objects.create(
                company=self.company, supplier=self.sup, date_received='2025-01-01',
                reference_no=ref, created_by=self.user, invoice_status='draft')
        self.assertEqual(next_reference_number(self.company, PurchaseInvoice, 'PUR-'), 'PUR-0006')

    def test_save_reassigns_taken_ref_and_reports_it(self):
        PurchaseInvoice.objects.create(
            company=self.company, supplier=self.sup, date_received='2025-01-01',
            reference_no='PUR-0001', created_by=self.user, invoice_status='draft')
        self.client.force_login(self.user)
        resp = self.client.post('/goods-in/save/', {
            'supplier': str(self.sup.id), 'warehouse': str(self.wh.id),
            'date_received': '2025-01-05',
            'reference_no': 'PUR-0001',        # taken on purpose
            'is_vat_inclusive': 'false',
            'item_id[]': [str(self.item.id)], 'qty[]': ['5'],
            'cost_price[]': ['100'], 'unit_id[]': [str(self.unit.id)],
            'batch_no[]': [''], 'expiry_date[]': [''],
            'discount_type[]': ['fixed'], 'discount_amount[]': ['0'],
            'discount_type': 'fixed', 'discount_amount': '0',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['X-Reference-No'], 'PUR-0002')   # silently bumped, header tells truth
        inv = PurchaseInvoice.objects.get(reference_no='PUR-0002')
        self.assertEqual(inv.lines.count(), 1)
        self.assertTrue(inv.lines.first().batch_no.startswith('AUTO-PUR-0002-B'))  # no more AUTO-None
        self.sup.refresh_from_db()
        self.assertEqual(self.sup.balance, Decimal('-565'))    # 5x100 net + 13% VAT, debited