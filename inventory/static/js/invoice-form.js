// Goods-In (purchase invoice) form component.
// Spreadsheet-style line grid: typeahead item search + modal picker.
// Data source (for now): full item list embedded via json_script ('items-data').
// Phase 1.2 will swap the client-side filter for server-side search.

(function () {
    const factory = (invoiceId, initialVatInclusive, vatRate) => ({
        items: [],
        lines: [],
        isVatInclusive: initialVatInclusive || false,
        vatRate: isNaN(parseFloat(vatRate)) ? 13 : parseFloat(vatRate),
        isViewMode: invoiceId !== null && invoiceId !== undefined,
        itemPicker: { open: false, search: '', category: '', activeIndex: null },
        ta: { open: false, index: null, suggestions: [], highlight: -1, style: {} },
        invDiscountType: 'fixed',
        invDiscountAmount: 0,
        _ridCounter: 0,

        get multiplier() { return 1 + (this.vatRate / 100); },

        init() {
            this.$el.addEventListener('htmx:configRequest', (evt) => this.stripBlankRows(evt));

            this.items = readJSON('items-data', []);
            const existing = readJSON('invoice-lines-data', []);
            this.lines = existing.length > 0
                ? existing.map((l) => this.normalizeLine(l))
                : [this.blankLine()];
        },

        // ---------- line management ----------
        blankLine() {
            return {
                _rid: ++this._ridCounter,
                item_id: null, item_name: '', search: '',
                qty: 1, unit_id: '', conversion_factor: 1, uoms: [],
                base_unit_id: null, base_unit_name: '',
                cost_price: 0, discount_type: 'fixed', discount_amount: 0,
                batch_no: '', expiry_date: '', is_vat_applicable: true,
            };
        },

        normalizeLine(l) {
            const base = this.blankLine();
            return Object.assign(base, l, {
                search: l.item_name || '',
                is_vat_applicable: l.is_vat_applicable !== false,
                unit_id: l.unit_id != null ? String(l.unit_id) : '',
            });
        },

        addLine() {
            this.lines.push(this.blankLine());
            this.focusField(this.lines.length - 1, 'item');
        },

        removeLine(index) {
            if (this.lines.length === 1) {
                this.lines = [this.blankLine()];
            } else {
                this.lines.splice(index, 1);
            }
        },

        maybeAppendRow() {
            if (this.isViewMode) return;
            const last = this.lines[this.lines.length - 1];
            if (last && last.item_id) {
                this.lines.push(this.blankLine());
            }
        },


        // Drop blank lines from the outgoing request (server re-checks anyway).
        stripBlankRows(evt) {
            if (this.isViewMode) return;
            const src = evt.detail.parameters;
            const keys = ['item_id[]', 'qty[]', 'cost_price[]', 'unit_id[]',
                          'discount_amount[]', 'discount_type[]', 'batch_no[]', 'expiry_date[]'];

            const isFormData = !!(src && typeof src.getAll === 'function');
            const getCol = (k) => {
                if (isFormData) return src.getAll(k);
                const v = src ? src[k] : undefined;
                if (v === undefined) return [];
                return Array.isArray(v) ? v : [v];
            };

            const items = getCol('item_id[]');
            if (!items.length) return;
            const keep = [];
            for (let i = 0; i < items.length; i++) {
                if (String(items[i] || '').trim() !== '') keep.push(i);
            }
            if (keep.length === items.length) return; // nothing blank — leave payload untouched

            const out = isFormData ? new FormData() : {};
            keys.forEach((k) => {
                const col = getCol(k);
                keep.forEach((i) => {
                    const v = (col[i] !== undefined && col[i] !== null) ? col[i] : '';
                    if (isFormData) out.append(k, v);
                    else (Array.isArray(out[k]) ? out[k] : (out[k] = [])).push(v);
                });
            });
            evt.detail.parameters = out;
        },

        
        // ---------- item selection ----------
        clearItem(line) {
            line.item_id = null;
            line.item_name = '';
            line.uoms = [];
            line.base_unit_id = null;
            line.base_unit_name = '';
            line.unit_id = '';
            line.conversion_factor = 1;
        },

        applyItem(line, item) {
            line.item_id = item.id;
            line.item_name = item.name;
            line.search = item.name;
            line.uoms = item.uoms || [];
            line.base_unit_id = String(item.base_unit_id);
            line.base_unit_name = item.base_unit_name;
            line.unit_id = String(item.base_unit_id);
            line.conversion_factor = 1;
            line.is_vat_applicable = item.vat !== false;
            let cost = parseFloat(item.cost_price) || 0;
            if (this.isVatInclusive && line.is_vat_applicable) cost = cost * this.multiplier;
            line.cost_price = roundMoney(cost);
        },

        setUnit(line) {
            if (!line.unit_id) return;
            if (String(line.unit_id) === String(line.base_unit_id)) {
                line.conversion_factor = 1;
                return;
            }
            const uom = (line.uoms || []).find((u) => String(u.unit_id) === String(line.unit_id));
            if (!uom) return;
            line.conversion_factor = parseFloat(uom.factor);
            const item = this.items.find((i) => i.id === line.item_id);
            if (item) {
                let baseCost = parseFloat(item.cost_price) || 0;
                if (this.isVatInclusive && line.is_vat_applicable) baseCost = baseCost * this.multiplier;
                line.cost_price = roundMoney(baseCost * line.conversion_factor);
            }
        },

        // ---------- typeahead (single shared dropdown, fixed position) ----------
        onTypeahead(line, index, event) {
            if (line.item_id && line.search !== line.item_name) this.clearItem(line);
            const q = (line.search || '').trim().toLowerCase();
            if (!q) { this.closeTA(); return; }
            const sugg = this.items.filter((it) =>
                it.name.toLowerCase().includes(q) || (it.barcode || '').includes(q)
            ).slice(0, 8);

            const rect = event.target.getBoundingClientRect();
            const openUp = (rect.bottom + 280 > window.innerHeight) && (rect.top > 280);
            this.ta.style = openUp
                ? { left: rect.left + 'px', width: Math.max(rect.width, 280) + 'px', top: Math.max(8, rect.top - 248) + 'px' }
                : { left: rect.left + 'px', width: Math.max(rect.width, 280) + 'px', top: (rect.bottom + 4) + 'px' };

            this.ta.index = index;
            this.ta.suggestions = sugg;
            this.ta.highlight = sugg.length ? 0 : -1;
            this.ta.open = sugg.length > 0;
        },

        onTAEnter(index) {
            if (this.ta.open && this.ta.highlight >= 0) {
                this.selectSuggestion(index, this.ta.suggestions[this.ta.highlight]);
            } else {
                this.closeTA();
                this.advance(index, 'qty');
            }
        },

        moveHighlight(dir) {
            const n = this.ta.suggestions.length;
            if (!n) return;
            this.ta.highlight = (this.ta.highlight + dir + n) % n;
        },

        closeTA() {
            this.ta.open = false;
            this.ta.suggestions = [];
            this.ta.index = null;
        },

        onTABlur() {
            setTimeout(() => {
                const idx = this.ta.index;
                if (idx !== null && this.lines[idx] && this.lines[idx].item_id) {
                    this.lines[idx].search = this.lines[idx].item_name;
                }
                this.closeTA();
            }, 150);
        },

        selectSuggestion(index, item) {
            this.applyItem(this.lines[index], item);
            this.closeTA();
            this.focusField(index, 'qty');
            this.maybeAppendRow();
        },

        typeaheadMeta(item) {
            let meta = this.getItemUnitsString(item);
            if (item.barcode) meta += ' · ' + item.barcode;
            return meta;
        },

        // ---------- picker modal ----------
        get filteredItems() {
            const q = (this.itemPicker.search || '').toLowerCase();
            return this.items.filter((item) => {
                const matchSearch = !q || item.name.toLowerCase().includes(q) || (item.barcode || '').includes(q);
                const matchCat = !this.itemPicker.category || item.category_id == this.itemPicker.category;
                return matchSearch && matchCat;
            });
        },

        openItemPicker(index) {
            this.itemPicker.activeIndex = index;
            this.itemPicker.open = true;
            this.itemPicker.search = '';
            this.itemPicker.category = '';
            this.$nextTick(() => { if (this.$refs.pickerSearch) this.$refs.pickerSearch.focus(); });
        },

        selectItem(item) {
            const index = this.itemPicker.activeIndex;
            if (index === null) return;
            this.applyItem(this.lines[index], item);
            this.itemPicker.open = false;
            this.focusField(index, 'qty');
            this.maybeAppendRow();
        },

        getItemUnitsString(item) {
            if (!item.uoms || item.uoms.length === 0) return item.base_unit_name;
            const shortNames = item.uoms.map((u) => `${u.name}×${u.factor}`).join(' · ');
            return `${item.base_unit_name} · ${shortNames}`;
        },

        // ---------- keyboard flow ----------
        advance(index, field) {
            this.focusField(index, field);
        },

        advanceFromRowEnd(index) {
            if (index === this.lines.length - 1) this.maybeAppendRow();
            this.focusField(Math.min(index + 1, this.lines.length - 1), 'item');
        },

        focusField(index, field) {
            this.$nextTick(() => {
                const el = document.getElementById(`gi-${index}-${field}`);
                if (!el) return;
                el.focus();
                if (el.select && ['item', 'qty', 'rate', 'disc'].includes(field)) el.select();
            });
        },

        // ---------- money (all previews mirror server formulas exactly) ----------
        lineDiscountValue(line) {
            const gross = (parseFloat(line.qty) || 0) * (parseFloat(line.cost_price) || 0);
            const amt = parseFloat(line.discount_amount) || 0;
            const val = line.discount_type === 'percentage' ? gross * (amt / 100) : amt;
            return Math.min(val, gross);
        },

        lineGross(line) {
            return roundMoney((parseFloat(line.qty) || 0) * (parseFloat(line.cost_price) || 0) - this.lineDiscountValue(line));
        },

        lineNet(line) {
            const amt = this.lineGross(line);
            return (this.isVatInclusive && line.is_vat_applicable) ? roundMoney(amt / this.multiplier) : amt;
        },

        lineBeforeTax(line) {
            return (this.isVatInclusive && line.is_vat_applicable && line.item_id) ? this.lineNet(line) : null;
        },

        get subtotal() { return this.lines.reduce((s, l) => s + this.lineNet(l), 0); },
        get vatableNet() { return this.lines.filter((l) => l.is_vat_applicable).reduce((s, l) => s + this.lineNet(l), 0); },

        get headerDiscountNet() {
            const typed = parseFloat(this.invDiscountAmount) || 0;
            if (this.invDiscountType === 'percentage') return this.subtotal * (typed / 100);
            if (!this.isVatInclusive) return typed;
            // Inclusive: typed discount is GROSS — net it with the blended ratio (mirrors server)
            const grossSum = this.lines.reduce((s, l) => s + this.lineGross(l), 0);
            return grossSum > 0 ? typed * (this.subtotal / grossSum) : typed;
        },

        get taxableAmount() { return Math.max(0, this.subtotal - this.headerDiscountNet); },

        get vatAmount() {
            if (this.subtotal <= 0) return 0;
            const vatableAfter = this.vatableNet * (this.taxableAmount / this.subtotal);
            return vatableAfter * (this.vatRate / 100);
        },

        get grandTotal() { return this.taxableAmount + this.vatAmount; },

        get hasMixedVat() {
            const sel = this.lines.filter((l) => l.item_id);
            return sel.some((l) => l.is_vat_applicable) && sel.some((l) => !l.is_vat_applicable);
        },
    });

    // Register for BOTH cases: loaded before Alpine (page load) or after (htmx-swapped partial)
    if (window.Alpine) {
        Alpine.data('invoiceForm', factory);
    } else {
        document.addEventListener('alpine:init', () => Alpine.data('invoiceForm', factory));
    }
})();