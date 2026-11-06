/**
 * static/js/announcements.js
 * SmartCivic Municipal Announcement Broadcast Client
 * - Manages dismissible active announcement banner
 * - Manages notification bell unread counter & dropdown
 * - Real-time Socket.IO live broadcast and retraction updates
 * - Strictly DOM manipulation via textContent (Zero unsafe innerHTML)
 */

let activeAnnouncementsList = [];

function getSeverityTheme(severity) {
    const sev = String(severity || 'info').toLowerCase();
    switch (sev) {
        case 'critical':
            return {
                border: '#ef4444',
                bg: 'rgba(239, 68, 68, 0.12)',
                badgeBg: 'rgba(239, 68, 68, 0.25)',
                text: '#f87171',
                label: 'CRITICAL ALERT'
            };
        case 'warning':
            return {
                border: '#f59e0b',
                bg: 'rgba(245, 158, 11, 0.12)',
                badgeBg: 'rgba(245, 158, 11, 0.25)',
                text: '#fbbf24',
                label: 'WARNING'
            };
        case 'info':
        default:
            return {
                border: '#3b82f6',
                bg: 'rgba(59, 130, 246, 0.12)',
                badgeBg: 'rgba(59, 130, 246, 0.25)',
                text: '#60a5fa',
                label: 'NOTICE'
            };
    }
}

async function fetchAndRenderAnnouncements() {
    try {
        if (typeof api !== 'function') return;
        const res = await api('/api/announcements/active');
        const json = await res.json();
        if (json.success && Array.isArray(json.data)) {
            activeAnnouncementsList = json.data;
            renderAnnouncementBanner();
            renderAnnouncementDropdown();
        }
    } catch (err) {
        console.warn('[Announcements] Failed to fetch active announcements:', err.message);
    }
}

function renderAnnouncementBanner() {
    const banner = document.getElementById('activeAnnouncementBanner');
    if (!banner) return;

    // Pick top unread announcement (pinned first, then newest)
    const unread = activeAnnouncementsList.filter(a => !a.is_read);

    banner.textContent = '';

    if (unread.length === 0) {
        banner.style.display = 'none';
        return;
    }

    const topAnn = unread[0];
    const theme = getSeverityTheme(topAnn.severity);

    banner.style.display = 'block';
    banner.style.padding = '1rem 1.25rem';
    banner.style.borderRadius = '10px';
    banner.style.background = theme.bg;
    banner.style.border = `1px solid ${theme.border}`;
    banner.style.borderLeft = `5px solid ${theme.border}`;
    banner.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.15)';

    const contentRow = document.createElement('div');
    contentRow.style.display = 'flex';
    contentRow.style.justifyContent = 'space-between';
    contentRow.style.alignItems = 'flex-start';
    contentRow.style.gap = '1rem';

    const textCol = document.createElement('div');
    textCol.style.flex = '1';

    const headerLine = document.createElement('div');
    headerLine.style.display = 'flex';
    headerLine.style.alignItems = 'center';
    headerLine.style.gap = '0.6rem';
    headerLine.style.marginBottom = '0.35rem';

    const badge = document.createElement('span');
    badge.style.padding = '0.15rem 0.5rem';
    badge.style.borderRadius = '4px';
    badge.style.fontSize = '0.68rem';
    badge.style.fontWeight = '800';
    badge.style.letterSpacing = '0.04em';
    badge.style.background = theme.badgeBg;
    badge.style.color = theme.text;
    badge.textContent = theme.label;
    headerLine.appendChild(badge);

    const titleEl = document.createElement('strong');
    titleEl.style.fontSize = '0.98rem';
    titleEl.style.color = '#ffffff';
    titleEl.textContent = (topAnn.pinned ? '📌 ' : '') + topAnn.title;
    headerLine.appendChild(titleEl);

    textCol.appendChild(headerLine);

    const bodyEl = document.createElement('p');
    bodyEl.style.fontSize = '0.88rem';
    bodyEl.style.lineHeight = '1.45';
    bodyEl.style.color = '#e2e8f0';
    bodyEl.style.margin = '0 0 0.35rem 0';
    bodyEl.textContent = topAnn.body;
    textCol.appendChild(bodyEl);

    const metaEl = document.createElement('div');
    metaEl.style.fontSize = '0.74rem';
    metaEl.style.color = '#94a3b8';
    metaEl.textContent = `Issued by Municipal Authority • ${new Date(topAnn.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
    textCol.appendChild(metaEl);

    contentRow.appendChild(textCol);

    // Dismiss / Acknowledge Button
    const dismissBtn = document.createElement('button');
    dismissBtn.type = 'button';
    dismissBtn.style.padding = '0.4rem 0.85rem';
    dismissBtn.style.fontSize = '0.8rem';
    dismissBtn.style.fontWeight = '600';
    dismissBtn.style.border = '1px solid rgba(255, 255, 255, 0.2)';
    dismissBtn.style.borderRadius = '6px';
    dismissBtn.style.background = 'rgba(255, 255, 255, 0.1)';
    dismissBtn.style.color = '#ffffff';
    dismissBtn.style.cursor = 'pointer';
    dismissBtn.style.whiteSpace = 'nowrap';
    dismissBtn.textContent = 'Dismiss';
    dismissBtn.onclick = () => dismissAnnouncementBanner(topAnn._id);

    contentRow.appendChild(dismissBtn);
    banner.appendChild(contentRow);
}

function renderAnnouncementDropdown() {
    const badge = document.getElementById('announcementUnreadBadge');
    const countEl = document.getElementById('announcementDropdownCount');
    const list = document.getElementById('announcementDropdownList');

    const unreadCount = activeAnnouncementsList.filter(a => !a.is_read).length;

    if (badge) {
        if (unreadCount > 0) {
            badge.style.display = 'flex';
            badge.textContent = String(unreadCount);
        } else {
            badge.style.display = 'none';
        }
    }

    if (countEl) {
        countEl.textContent = `${unreadCount} unread`;
    }

    if (!list) return;

    list.textContent = '';

    if (activeAnnouncementsList.length === 0) {
        const empty = document.createElement('p');
        empty.style.color = '#94a3b8';
        empty.style.fontSize = '0.82rem';
        empty.style.margin = '0.5rem 0';
        empty.textContent = 'No municipal bulletins currently active.';
        list.appendChild(empty);
        return;
    }

    activeAnnouncementsList.forEach(ann => {
        const item = document.createElement('div');
        item.style.padding = '0.65rem 0.75rem';
        item.style.borderRadius = '6px';
        item.style.background = ann.is_read ? 'rgba(255,255,255,0.02)' : 'rgba(59, 130, 246, 0.08)';
        item.style.border = ann.is_read ? '1px solid rgba(255,255,255,0.05)' : '1px solid rgba(59, 130, 246, 0.25)';
        item.style.cursor = 'pointer';

        const topRow = document.createElement('div');
        topRow.style.display = 'flex';
        topRow.style.justifyContent = 'space-between';
        topRow.style.alignItems = 'center';
        topRow.style.marginBottom = '0.25rem';

        const titleSpan = document.createElement('strong');
        titleSpan.style.fontSize = '0.85rem';
        titleSpan.style.color = ann.is_read ? '#cbd5e1' : '#ffffff';
        titleSpan.textContent = (ann.pinned ? '📌 ' : '') + ann.title;
        topRow.appendChild(titleSpan);

        if (!ann.is_read) {
            const unreadDot = document.createElement('span');
            unreadDot.style.width = '7px';
            unreadDot.style.height = '7px';
            unreadDot.style.borderRadius = '50%';
            unreadDot.style.background = '#3b82f6';
            topRow.appendChild(unreadDot);
        }

        item.appendChild(topRow);

        const bodySpan = document.createElement('p');
        bodySpan.style.fontSize = '0.78rem';
        bodySpan.style.color = '#94a3b8';
        bodySpan.style.margin = '0 0 0.35rem 0';
        bodySpan.style.lineHeight = '1.35';
        bodySpan.textContent = ann.body;
        item.appendChild(bodySpan);

        item.onclick = async () => {
            if (!ann.is_read) {
                await markAnnouncementRead(ann._id);
            }
        };

        list.appendChild(item);
    });
}

async function markAnnouncementRead(annId) {
    try {
        await api(`/api/announcements/${annId}/read`, { method: 'POST' });
        const target = activeAnnouncementsList.find(a => a._id === annId);
        if (target) {
            target.is_read = true;
        }
        renderAnnouncementBanner();
        renderAnnouncementDropdown();
    } catch (err) {
        console.warn('[Announcements] Failed to mark read:', err);
    }
}

async function dismissAnnouncementBanner(annId) {
    await markAnnouncementRead(annId);
    const banner = document.getElementById('activeAnnouncementBanner');
    if (banner) banner.style.display = 'none';
}

function toggleAnnouncementDropdown() {
    const dropdown = document.getElementById('announcementDropdown');
    if (!dropdown) return;
    const isShown = dropdown.style.display === 'block';
    dropdown.style.display = isShown ? 'none' : 'block';
}

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
    const dropdown = document.getElementById('announcementDropdown');
    const bellBtn = document.getElementById('announcementBellBtn');
    if (!dropdown || !bellBtn) return;
    if (!dropdown.contains(e.target) && !bellBtn.contains(e.target)) {
        dropdown.style.display = 'none';
    }
});

// Setup realtime Socket.IO listener for live announcements
function setupAnnouncementRealtime() {
    if (typeof io === 'undefined') return;
    try {
        const socket = io('/civic', { withCredentials: true, transports: ['websocket', 'polling'] });
        socket.on('announcement_broadcast', () => {
            fetchAndRenderAnnouncements();
        });
        socket.on('announcement_retracted', (data) => {
            if (data && data.announcement_id) {
                activeAnnouncementsList = activeAnnouncementsList.filter(a => a._id !== data.announcement_id);
                renderAnnouncementBanner();
                renderAnnouncementDropdown();
            } else {
                fetchAndRenderAnnouncements();
            }
        });
    } catch (err) {
        console.warn('[Announcements] Socket.IO realtime connection skipped:', err);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    fetchAndRenderAnnouncements();
    setupAnnouncementRealtime();
});

