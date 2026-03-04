const toast = (() => {

    const queue  = [];
    let active   = false;
    let activeId = null;
    let activeDismiss = null;
    const controllers = new Map();

    const icons = {
        success: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
        error:   `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
        info:    `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
        warning: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
    };

    const closeIcon = `<svg class="hover:rotate-180 transition-transform" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;

    const slot  = document.getElementById('toastSlot');
    const stack = document.getElementById('toastStack');
    const badge = document.getElementById('toastBadge');


    function makeId() {
        try {
            if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
        } catch (_) {
            // ignore
        }
        return 't_' + Date.now().toString(16) + Math.random().toString(16).slice(2);
    }

    function getController(id) {
        if (controllers.has(id)) return controllers.get(id);
        const controller = {
            id,
            dismiss: (reason = 'exit') => {
                if (activeId === id && typeof activeDismiss === 'function') {
                    activeDismiss(reason);
                    return;
                }
                const idx = queue.findIndex((t) => t.id === id);
                if (idx !== -1) {
                    queue.splice(idx, 1);
                    updatePeek();
                }
                controllers.delete(id);
            },
        };
        controllers.set(id, controller);
        return controller;
    }

    function push(type, msg, duration = 2500) {
        const id = makeId();
        const item = { id, type, msg, duration };
        queue.push(item);
        updatePeek();
        if (!active) next();
        return getController(id);
    }

    function next() {
        if (queue.length === 0) {
            active = false;
            activeId = null;
            activeDismiss = null;
            updatePeek();
            return;
        }
        active = true;
        const item = queue.shift();
        activeId = item.id;
        updatePeek();
        activeDismiss = render(item.id, item.type, item.msg, item.duration);
    }

    function updatePeek() {
        const n = queue.length;
        stack.classList.remove('q1', 'q2');
        if (n === 1) stack.classList.add('q1');
        if (n >= 2)  stack.classList.add('q2');

        if (n > 0) {
            badge.textContent = '+' + n;
            badge.classList.add('show');
        } else {
            badge.classList.remove('show');
        }
    }


    function render(id, type, msg, duration) {
    slot.innerHTML = '';

    const el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = `
        <div class="toast-icon ${type}">${icons[type]}</div>
        <span class="toast-msg">${esc(msg)}</span>
        <button class="toast-close" aria-label="Dismiss" class="onhover:">${closeIcon}</button>
        <div class="toast-bar ${type}"></div>
    `;
    slot.appendChild(el);

    // Timer bar
    const bar = el.querySelector('.toast-bar');
    bar.style.animation = `shrink ${duration}ms linear forwards`;

    // Animate in
    requestAnimationFrame(() =>
        requestAnimationFrame(() => el.classList.add('show'))
    );

    // ── Timer ──
    let remaining = duration;
    let started   = Date.now();
    let timeout   = null;
    let done      = false;

    function start() {
        started = Date.now();
        timeout = setTimeout(() => dismiss('manual'), remaining); // dismiss('auto')
        bar.style.animationPlayState = 'running';
    }

    function pause() {
        if (timeout) { clearTimeout(timeout); timeout = null; }
        remaining = Math.max(0, remaining - (Date.now() - started));
        bar.style.animationPlayState = 'paused';
    }

    /**
        * @param {'auto'|'manual'} reason
        *   auto   = timer expired → normal slide-down exit
        *   manual = user clicked ✕ → throw animation
        */
    function dismiss(reason='exit') {
        if (done) return;
        done = true;
        if (timeout) { clearTimeout(timeout); timeout = null; }

        el.removeEventListener('mouseenter', pause);
        el.removeEventListener('mouseleave', start);
        el.removeEventListener('touchstart', pause);
        el.removeEventListener('touchend', start);

        // Pick animation based on reason
        el.classList.remove('show');
        el.classList.add(reason === 'manual' ? 'throw' : 'exit');
        

        let cleaned = false;
        function cleanup() {
        if (cleaned) return;
        cleaned = true;
        el.remove();
        controllers.delete(id);
        if (activeId === id) {
            activeId = null;
            activeDismiss = null;
        }
        next();
        }
        el.addEventListener('transitionend', cleanup, { once: true });
        setTimeout(cleanup, 500);
    }

    // Hover pause (desktop)
    el.addEventListener('mouseenter', pause);
    el.addEventListener('mouseleave', start);

    // Touch pause (mobile)
    el.addEventListener('touchstart', pause, { passive: true });
    el.addEventListener('touchend', start, { passive: true });

    // Close button → THROW
    el.querySelector('.toast-close').addEventListener('click', (e) => {
        e.stopPropagation();
        dismiss('manual');
    });

    start();
    return dismiss;
    }


    function esc(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    return {
        success: (msg, ms) => push('success', msg, ms),
        error:   (msg, ms) => push('error',   msg, ms),
        info:    (msg, ms) => push('info',    msg, ms),
        warning: (msg, ms) => push('warning', msg, ms),
    };

})();
