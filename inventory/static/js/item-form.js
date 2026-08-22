// Item form component — registered globally so _form.html can load
// on ANY page (items page now, goods-in picker in Phase 1).
document.addEventListener('alpine:init', () => {
    Alpine.data('itemForm', (itemId, isEditable, isLocked) => ({
        changed: false,
        editable: itemId ? isEditable : true,
        name: document.getElementById('item-name-input')?.value || '',
        category: document.getElementById('item-category-select')?.value || '',
        defaultSupplier: document.getElementById('item-supplier-select')?.value || '',
        isLocked: isLocked,
        imagePreview: document.getElementById('item-image-preview-src')?.textContent.trim() || '',
        imageRemoved: false,
        recentCategories: [], recentUnits: [], recentSuppliers: [], unitMap: {},
        cropModal: false, cropper: null, croppedFile: null,
        grid: [],
        overrideTracker: {},
        allTierIds: [],
        cartonUnitId: '',
        _idCounter: 0,

        genID() {
            this._idCounter += 1;
            return `row_${Date.now()}_${this._idCounter}`;
        },

        fmt(val) {
            return parseFloat(val || 0).toFixed(2);
        },

        get baseUnitShort() {
            const id = this.grid[0]?.unit_id;
            return id && this.unitMap[id] ? this.unitMap[id].short_name : 'Select above';
        },
        get baseUnitName() {
            const id = this.grid[0]?.unit_id;
            return id && this.unitMap[id] ? this.unitMap[id].name : 'First Select a base unit';
        },

        init() {
            this.changed = false;
            this.recentCategories = readJSON('recent-cats-data', []);
            this.recentUnits = readJSON('recent-units-data', []);
            this.recentSuppliers = readJSON('recent-sups-data', []);
            this.unitMap = readJSON('unit-map-data', {});
            this.allTierIds = readJSON('all-tier-ids-data', []);

            this.cartonUnitId = document.getElementById('carton-unit-id')?.value || '';

            this.grid = readJSON('packaging-data', []) || [];
            if (this.grid.length > 0) {
                this.grid.forEach((row) => {
                    row.id = this.genID();
                    row.unit_id = String(row.unit_id || '');

                    if (!row.prices) row.prices = {};
                    if (row.cost) this.overrideTracker[`${row.id}_cost`] = true;

                    for (const tierId in row.prices) {
                        const strTierId = String(tierId);
                        row.prices[strTierId] = row.prices[tierId];
                        this.overrideTracker[`${row.id}_${strTierId}`] = true;
                    }
                });
            } else {
                this.grid = [{ id: this.genID(), unit_id: '', factor: 1, barcode: '', cost: '', prices: {} }];
                if (this.cartonUnitId) {
                    this.grid.push({ id: this.genID(), unit_id: String(this.cartonUnitId), factor: '', barcode: '', cost: '', prices: {} });
                }
            }
        },

        addRow() {
            this.grid.push({ id: this.genID(), unit_id: '', factor: 1, barcode: '', cost: '', prices: {} });
            this.changed = true;
        },

        removeRow(index) {
            const row = this.grid[index];
            if (row) {
                this.allTierIds.forEach(tierId => {
                    delete this.overrideTracker[`${row.id}_${tierId}`];
                });
                delete this.overrideTracker[`${row.id}_cost`];
            }
            this.grid.splice(index, 1);
            this.changed = true;
        },

        updateGridRow(row) {
            row.factor = 1;
            row.cost = '';
            row.barcode = '';
            if (!row.prices) row.prices = {};
            this.allTierIds.forEach(tierId => {
                row.prices[tierId] = '';
                delete this.overrideTracker[`${row.id}_${tierId}`];
            });
            delete this.overrideTracker[`${row.id}_cost`];
            this.changed = true;
        },

        handleBaseUnitChange() {
            const baseUnitId = this.grid[0].unit_id;
            this.grid.forEach((row, idx) => {
                if (idx > 0 && row.unit_id === baseUnitId) {
                    this.updateGridRow(row);
                    row.unit_id = '';
                }
            });
            this.changed = true;
        },

        recalculateCost(changedIndex) {
            const changedRow = this.grid[changedIndex];
            const changedCost = parseFloat(changedRow.cost) || 0;
            const changedFactor = parseFloat(changedRow.factor) || 1;

            this.overrideTracker[`${changedRow.id}_cost`] = true;

            const baseCost = changedIndex === 0 ? changedCost : changedCost / changedFactor;
            this.grid[0].cost = baseCost.toFixed(2);

            this.grid.forEach((row, idx) => {
                if (idx === 0 || idx === changedIndex) return;
                const factor = parseFloat(row.factor) || 1;
                if (!this.overrideTracker[`${row.id}_cost`]) {
                    row.cost = (baseCost * factor).toFixed(2);
                }
            });
            this.changed = true;
        },

        recalculateFromBase(changedIndex = -1) {
            const baseCost = parseFloat(this.grid[0].cost) || 0;
            this.grid.forEach((row, idx) => {
                if (idx === 0) return;
                const factor = parseFloat(row.factor) || 1;

                if (idx === changedIndex) {
                    delete this.overrideTracker[`${row.id}_cost`];
                    this.allTierIds.forEach(tierId => delete this.overrideTracker[`${row.id}_${tierId}`]);
                }

                if (!this.overrideTracker[`${row.id}_cost`]) {
                    row.cost = (baseCost * factor).toFixed(2);
                }

                if (!row.prices) row.prices = {};
                this.allTierIds.forEach(tierId => {
                    const k = `${row.id}_${tierId}`;
                    if (!this.overrideTracker[k]) {
                        const baseTierPrice = parseFloat(this.grid[0].prices?.[tierId] || 0);
                        row.prices[tierId] = (baseTierPrice * factor).toFixed(2);
                    }
                });
            });
            this.changed = true;
        },

        recalculateTier(changedIndex, tierId) {
            const changedRow = this.grid[changedIndex];
            if (!changedRow.prices) changedRow.prices = {};
            const changedPrice = parseFloat(changedRow.prices[tierId]) || 0;
            const changedFactor = parseFloat(changedRow.factor) || 1;

            this.overrideTracker[`${changedRow.id}_${tierId}`] = true;

            const basePrice = changedIndex === 0 ? changedPrice : changedPrice / changedFactor;

            this.grid.forEach((row, idx) => {
                if (idx === changedIndex) return;
                if (!row.prices) row.prices = {};
                const k = `${row.id}_${tierId}`;

                if (!this.overrideTracker[k]) {
                    const factor = parseFloat(row.factor) || 1;
                    row.prices[tierId] = (basePrice * factor).toFixed(2);
                }
            });
            this.changed = true;
        },

        gridData() {
            return this.grid.map(row => {
                const cleanPrices = {};
                if (row.prices) {
                    for (const tierId in row.prices) {
                        if (row.prices[tierId] !== '' && row.prices[tierId] !== null) {
                            cleanPrices[tierId] = row.prices[tierId];
                        }
                    }
                }
                return {
                    unit_id: row.unit_id,
                    factor: row.factor,
                    barcode: row.barcode,
                    cost: row.cost,
                    prices: cleanPrices
                };
            });
        },

        handleFileSelect(event) {
            const file = event.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    this.$refs.cropImage.src = e.target.result;
                    this.cropModal = true;
                    this.$nextTick(() => {
                        if (this.cropper) this.cropper.destroy();
                        this.cropper = new Cropper(this.$refs.cropImage, { aspectRatio: 1, viewMode: 1, autoCropArea: 0.9 });
                    });
                };
                reader.readAsDataURL(file);
            }
        },
        saveCrop() {
            const canvas = this.cropper.getCroppedCanvas({ width: 400, height: 400 });
            this.imagePreview = canvas.toDataURL('image/jpeg');
            canvas.toBlob((blob) => {
                this.croppedFile = new File([blob], 'cropped.jpg', { type: 'image/jpeg' });
                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(this.croppedFile);
                document.getElementById('image-upload-input').files = dataTransfer.files;
            });
            this.cropper.destroy();
            this.cropModal = false;
            this.imageRemoved = false;
            this.changed = true;
        },
        cancelCrop() { this.cropper.destroy(); this.cropModal = false; document.getElementById('image-upload-input').value = ''; }
    }));
});