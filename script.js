// Theme state lives on <html> (class="theme-minimal" and/or "dark").
// The <head> of each page applies the saved state before first paint, so there's no flash.
document.addEventListener('DOMContentLoaded', () => {
    const root = document.documentElement;
    const themeBtn = document.getElementById('theme-toggle');   // cozy <-> minimal (your original button)
    const darkBtn = document.getElementById('dark-toggle');     // light <-> dark

    // Cozy <-> Minimal
    if (themeBtn) {
        themeBtn.addEventListener('click', () => {
            const minimal = root.classList.toggle('theme-minimal');
            localStorage.setItem('studyflow-theme', minimal ? 'theme-minimal' : 'theme-cozy');
        });
    }

    // Light <-> Dark
    function syncDarkIcon() {
        if (darkBtn) darkBtn.textContent = root.classList.contains('dark') ? '☀️' : '🌙';
    }
    syncDarkIcon();
    if (darkBtn) {
        darkBtn.addEventListener('click', () => {
            const dark = root.classList.toggle('dark');
            localStorage.setItem('studyflow-dark', dark ? '1' : '0');
            syncDarkIcon();
        });
    }

    // "Now" line on today's column of the timetable
    const tt = document.querySelector('.tt');
    const col = document.querySelector('.tt-col.is-today');
    if (tt && col) {
        const startHour = parseInt(tt.dataset.startHour, 10);
        const endHour = parseInt(tt.dataset.endHour, 10);
        const hourPx = parseFloat(getComputedStyle(tt).getPropertyValue('--hour-px')) || 56;

        const line = document.createElement('div');
        line.className = 'now-line';
        col.appendChild(line);

        const update = () => {
            const now = new Date();
            const mins = now.getHours() * 60 + now.getMinutes();
            line.style.display = (mins >= startHour * 60 && mins <= endHour * 60) ? 'block' : 'none';
            line.style.top = ((mins - startHour * 60) / 60 * hourPx) + 'px';
        };
        update();
        setInterval(update, 30000);
    }
});

// ---------- Floating reminder box ----------
document.addEventListener('DOMContentLoaded', () => {
    const box = document.getElementById('reminder-box');
    const toggle = document.getElementById('reminder-toggle');
    if (!box || !toggle) return;

    // Open by default on wide screens, closed on phones; remember what you chose.
    let open;
    try {
        const saved = localStorage.getItem('studyflow-reminders-open');
        open = saved === null ? window.innerWidth > 900 : saved === '1';
    } catch (e) { open = window.innerWidth > 900; }
    box.classList.toggle('collapsed', !open);

    toggle.addEventListener('click', () => {
        const nowCollapsed = box.classList.toggle('collapsed');
        try { localStorage.setItem('studyflow-reminders-open', nowCollapsed ? '0' : '1'); } catch (e) {}
    });

    // Refresh the list every minute so "in 2h 10m" stays accurate
    const items = document.getElementById('reminder-items');
    const badge = document.getElementById('reminder-badge');
    async function refresh() {
        try {
            const res = await fetch('/reminders', { cache: 'no-store' });
            if (!res.ok) return;
            items.innerHTML = await res.text();
            const n = parseInt(items.querySelector('.reminder-list').dataset.count, 10) || 0;
            badge.textContent = n;
            badge.hidden = n === 0;
        } catch (e) { /* offline: keep what we have */ }
    }
    setInterval(refresh, 60000);
});
