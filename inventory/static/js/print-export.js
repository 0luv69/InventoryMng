/**
 * ══════════════════════════════════════════════════════════════
 *  PrintExport — Universal Print / Export Module
 *  Reusable across ALL pages of InventoryChamps
 * ══════════════════════════════════════════════════════════════
 *
 *  API:
 *    PrintExport.printNow(options)     → open print-styled popup
 *    PrintExport.exportPDF(options)    → same popup, auto-triggers print (save-as-PDF)
 *    PrintExport.exportExcel(options)  → download .xlsx via SheetJS
 *
 *  options = {
 *    title:    'Invoice #1234',           // document title
 *    columns:  ['Date','Item','Qty'],     // table column headers
 *    rows:     [['2025-01-01','Pen',10]], // 2D array of row data
 *    summary:  { 'Total': '₹5,000' },    // optional key-value summary below table
 *    filename: 'invoice-1234',            // filename for Excel export (no extension)
 *    subtitle: 'Customer: John Doe',      // optional subtitle below title
 *  }
 */

const PrintExport = (() => {

    /* ──────────────────────────────────────
       CURRENCY SYMBOL MAP
    ────────────────────────────────────── */
    const CURRENCY_SYMBOLS = {
        NPR: '₹',
        INR: '₹',
        USD: '$',
    };

    function currencyLabel(code) {
        const sym = CURRENCY_SYMBOLS[code] || '';
        return sym ? `${code} (${sym})` : code;
    }


    /* ──────────────────────────────────────
       COMPANY INFO CACHE
    ────────────────────────────────────── */
    let _companyCache = null;
    let _companyFetchPromise = null;

    async function getCompanyInfo() {
        if (_companyCache) return _companyCache;
        if (_companyFetchPromise) return _companyFetchPromise;

        _companyFetchPromise = fetch('/api/company/info/')
            .then(r => {
                if (!r.ok) throw new Error('Failed to fetch company info');
                return r.json();
            })
            .then(data => {
                _companyCache = data;
                _companyFetchPromise = null;
                return data;
            })
            .catch(err => {
                console.error('PrintExport: company info error', err);
                _companyFetchPromise = null;
                return {
                    name: 'InventoryChamps',
                    logo_url: '',
                    address: '',
                    city: '',
                    state: '',
                    country: '',
                    phone: '',
                    email: '',
                    tax_id: '',
                    currency: 'NPR',
                };
            });

        return _companyFetchPromise;
    }

    /** Force refresh on next call (e.g. after company update) */
    function clearCache() {
        _companyCache = null;
    }


    /* ──────────────────────────────────────
       BUILD HEADER HTML
    ────────────────────────────────────── */
    function buildHeaderHTML(co) {
        const addressParts = [co.address, co.city, co.state, co.country]
            .filter(Boolean)
            .join(', ');

        const logoHTML = co.logo_url
            ? `<img src="${co.logo_url}" style="width:54px;height:54px;object-fit:contain;border-radius:8px;" alt="Logo">`
            : `<div style="width:54px;height:54px;border-radius:8px;background:#22c55e;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:22px;">${(co.name || 'I')[0].toUpperCase()}</div>`;

        const currText = co.currency ? currencyLabel(co.currency) : '';
        const taxText  = co.tax_id  ? `PAN/Tax: ${co.tax_id}` : '';
        const metaLine = [currText, taxText].filter(Boolean).join('  ·  ');

        return `
        <div style="display:flex;align-items:center;gap:16px;padding-bottom:14px;border-bottom:2px solid #e5e5e5;margin-bottom:18px;">
            ${logoHTML}
            <div style="flex:1;min-width:0;">
                <div style="font-size:18px;font-weight:800;color:#171717;margin-bottom:2px;">${co.name || 'InventoryChamps'}</div>
                ${addressParts ? `<div style="font-size:11px;color:#737373;">${addressParts}</div>` : ''}
                <div style="font-size:11px;color:#737373;">
                    ${co.phone ? `📞 ${co.phone}` : ''}${co.phone && co.email ? '  ·  ' : ''}${co.email ? `✉ ${co.email}` : ''}
                </div>
                ${metaLine ? `<div style="font-size:10px;color:#a3a3a3;margin-top:2px;">${metaLine}</div>` : ''}
            </div>
        </div>`;
    }


    /* ──────────────────────────────────────
       BUILD TABLE HTML
    ────────────────────────────────────── */
    function buildTableHTML(columns, rows) {
        if (!columns || !columns.length) return '';

        const ths = columns.map(c =>
            `<th style="padding:8px 10px;text-align:left;font-size:11px;font-weight:700;color:#525252;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #d4d4d4;background:#fafafa;">${c}</th>`
        ).join('');

        const trs = (rows || []).map((row, ri) => {
            const bg = ri % 2 === 0 ? '#ffffff' : '#fafafa';
            const tds = row.map(cell =>
                `<td style="padding:7px 10px;font-size:12px;color:#404040;border-bottom:1px solid #e5e5e5;">${cell ?? ''}</td>`
            ).join('');
            return `<tr style="background:${bg};">${tds}</tr>`;
        }).join('');

        return `
        <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
            <thead><tr>${ths}</tr></thead>
            <tbody>${trs}</tbody>
        </table>`;
    }


    /* ──────────────────────────────────────
       BUILD SUMMARY HTML
    ────────────────────────────────────── */
    function buildSummaryHTML(summary) {
        if (!summary || !Object.keys(summary).length) return '';

        const rows = Object.entries(summary).map(([k, v]) =>
            `<tr>
                <td style="padding:4px 10px;font-size:12px;font-weight:600;color:#525252;text-align:right;">${k}:</td>
                <td style="padding:4px 10px;font-size:12px;font-weight:700;color:#171717;text-align:right;">${v}</td>
            </tr>`
        ).join('');

        return `
        <table style="margin-left:auto;margin-bottom:16px;border-top:2px solid #d4d4d4;min-width:220px;">
            <tbody>${rows}</tbody>
        </table>`;
    }


    /* ──────────────────────────────────────
       BUILD FULL PAGE HTML
    ────────────────────────────────────── */
    function buildPageHTML(companyInfo, options) {
        const now = new Date();
        const dateStr = now.toLocaleDateString('en-US', {
            year: 'numeric', month: 'short', day: 'numeric'
        });
        const timeStr = now.toLocaleTimeString('en-US', {
            hour: '2-digit', minute: '2-digit'
        });

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${options.title || 'Print Document'}</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            color: #171717;
            padding: 32px;
            max-width: 900px;
            margin: 0 auto;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }
        @media print {
            body { padding: 16px; }
            .no-print { display: none !important; }
            @page { margin: 12mm 10mm; }
        }
    </style>
</head>
<body>
    ${buildHeaderHTML(companyInfo)}

    <!-- Document Title -->
    <div style="margin-bottom:16px;">
        <div style="font-size:16px;font-weight:700;color:#171717;">${options.title || 'Document'}</div>
        ${options.subtitle ? `<div style="font-size:12px;color:#737373;margin-top:2px;">${options.subtitle}</div>` : ''}
        <div style="font-size:10px;color:#a3a3a3;margin-top:4px;">Printed on: ${dateStr} at ${timeStr}</div>
    </div>

    <!-- Table -->
    ${buildTableHTML(options.columns, options.rows)}

    <!-- Summary -->
    ${buildSummaryHTML(options.summary)}

    <!-- Footer -->
    <div style="margin-top:24px;padding-top:12px;border-top:1px solid #e5e5e5;display:flex;justify-content:space-between;align-items:center;">
        <div style="font-size:10px;color:#a3a3a3;">${companyInfo.name || 'InventoryChamps'} — Generated automatically</div>
        <div style="font-size:10px;color:#a3a3a3;">Page 1</div>
    </div>
</body>
</html>`;
    }


    /* ══════════════════════════════════════
       PUBLIC: printNow()
    ══════════════════════════════════════ */
    async function printNow(options = {}) {
        try {
            const co = await getCompanyInfo();
            const html = buildPageHTML(co, options);

            const w = window.open('', '_blank', 'width=850,height=700,scrollbars=yes,resizable=yes');
            if (!w) {
                if (typeof toast !== 'undefined') toast.error('Popup blocked! Please allow pop-ups for this site.');
                return;
            }
            w.document.open();
            w.document.write(html);
            w.document.close();

            // Wait for images to load, then trigger print
            w.onload = () => {
                setTimeout(() => w.print(), 350);
            };

        } catch (err) {
            console.error('PrintExport.printNow error:', err);
            if (typeof toast !== 'undefined') toast.error('Failed to generate print view.');
        }
    }


    /* ══════════════════════════════════════
       PUBLIC: exportPDF()
       (Uses browser print → Save as PDF)
    ══════════════════════════════════════ */
    async function exportPDF(options = {}) {
        // Same as printNow — the browser print dialog lets the user "Save as PDF"
        await printNow(options);
    }


    /* ══════════════════════════════════════
       PUBLIC: exportExcel()
       Uses SheetJS (xlsx) loaded via CDN
    ══════════════════════════════════════ */

    /** Dynamically load SheetJS if not already available */
    function _ensureXLSX() {
        return new Promise((resolve, reject) => {
            if (typeof XLSX !== 'undefined') { resolve(); return; }
            const s = document.createElement('script');
            s.src = 'https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js';
            s.onload = resolve;
            s.onerror = () => reject(new Error('Failed to load SheetJS library'));
            document.head.appendChild(s);
        });
    }

    async function exportExcel(options = {}) {
        try {
            await _ensureXLSX();

            const co = await getCompanyInfo();
            const wb = XLSX.utils.book_new();

            // Build data array: company header rows + blank + column headers + data rows + summary
            const sheetData = [];

            // Company header in Excel
            sheetData.push([co.name || 'InventoryChamps']);
            const addressParts = [co.address, co.city, co.state, co.country].filter(Boolean).join(', ');
            if (addressParts) sheetData.push([addressParts]);
            const contact = [co.phone ? `Phone: ${co.phone}` : '', co.email ? `Email: ${co.email}` : ''].filter(Boolean).join('  |  ');
            if (contact) sheetData.push([contact]);
            if (co.tax_id) sheetData.push([`PAN/Tax: ${co.tax_id}`, '', `Currency: ${currencyLabel(co.currency)}`]);
            sheetData.push([]); // blank row

            // Document title
            sheetData.push([options.title || 'Document']);
            if (options.subtitle) sheetData.push([options.subtitle]);

            const now = new Date();
            sheetData.push([`Exported: ${now.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })} ${now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}`]);
            sheetData.push([]); // blank row

            // Column headers
            if (options.columns && options.columns.length) {
                sheetData.push(options.columns);
            }

            // Data rows
            if (options.rows && options.rows.length) {
                options.rows.forEach(r => sheetData.push(r));
            }

            // Summary
            if (options.summary && Object.keys(options.summary).length) {
                sheetData.push([]); // blank row
                Object.entries(options.summary).forEach(([k, v]) => {
                    const row = new Array((options.columns?.length || 2) - 2).fill('');
                    row.push(k, v);
                    sheetData.push(row);
                });
            }

            const ws = XLSX.utils.aoa_to_sheet(sheetData);

            // Auto-size columns
            if (options.columns) {
                ws['!cols'] = options.columns.map((col, i) => {
                    let maxW = col.length;
                    (options.rows || []).forEach(row => {
                        const cellLen = String(row[i] ?? '').length;
                        if (cellLen > maxW) maxW = cellLen;
                    });
                    return { wch: Math.min(maxW + 4, 40) };
                });
            }

            const sheetName = (options.title || 'Sheet1').substring(0, 31).replace(/[\\\/\?\*\[\]]/g, '');
            XLSX.utils.book_append_sheet(wb, ws, sheetName);

            const filename = (options.filename || options.title || 'export').replace(/[^a-zA-Z0-9_\-]/g, '_') + '.xlsx';
            XLSX.writeFile(wb, filename);

            if (typeof toast !== 'undefined') toast.success(`Excel exported: ${filename}`);

        } catch (err) {
            console.error('PrintExport.exportExcel error:', err);
            if (typeof toast !== 'undefined') toast.error('Failed to export Excel file.');
        }
    }


    /* ══════════════════════════════════════
       RETURN PUBLIC API
    ══════════════════════════════════════ */
    return {
        printNow,
        exportPDF,
        exportExcel,
        clearCache,
        getCompanyInfo,
        currencyLabel,
    };

})();