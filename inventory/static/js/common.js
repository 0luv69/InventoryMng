// Shared helpers — loaded globally on every page (must execute before Alpine).

function getCsrfToken() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
}

// Safe JSON reader for Django's {{ x|json_script:"id" }} blocks.
function readJSON(id, fallback = null) {
    try {
        const el = document.getElementById(id);
        return el ? JSON.parse(el.textContent) : fallback;
    } catch (e) {
        return fallback;
    }
}


function roundMoney(val) {
    return Math.round((parseFloat(val || 0) + Number.EPSILON) * 100) / 100;
}