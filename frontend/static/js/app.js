/**
 * FinTrust AI - Global Application Manager for Standalone Frontend
 */

document.addEventListener('DOMContentLoaded', async () => {
    // Check active session status
    await checkAuthSession();
    
    // Setup Theme Switcher
    setupThemeToggle();
    
    // Setup Language Selector
    setupLanguageSelector();
});

let currentUser = null;

async function checkAuthSession() {
    try {
        const res = await apiFetch('/api/auth/me');
        if (res.ok) {
            const data = await res.json();
            if (data.authenticated) {
                currentUser = data.user;
                updateNavbarForUser(data.user, data.unread_count || 0);
            } else {
                updateNavbarForGuest();
            }
        }
    } catch (e) {
        console.warn("Could not verify session state:", e);
        updateNavbarForGuest();
    }
}

function updateNavbarForUser(user, unreadCount) {
    const authNav = document.getElementById('nav-auth-section');
    if (!authNav) return;

    let dashboardLink = 'applicant_dashboard.html';
    if (user.role === 'admin') dashboardLink = 'admin_dashboard.html';
    else if (user.role === 'lender') dashboardLink = 'lender_dashboard.html';

    authNav.innerHTML = `
        <div class="user-badge flex items-center gap-3">
            <span class="text-sm font-semibold text-slate-300">👋 ${escapeHtml(user.username)} (${user.role.toUpperCase()})</span>
            <a href="${dashboardLink}" class="nav-link px-3 py-1.5 rounded-lg bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 transition text-sm font-medium">Dashboard</a>
            <button onclick="handleLogout()" class="px-3 py-1.5 rounded-lg bg-rose-500/20 text-rose-400 hover:bg-rose-500/30 transition text-sm font-medium">Logout</button>
        </div>
    `;
}

function updateNavbarForGuest() {
    const authNav = document.getElementById('nav-auth-section');
    if (!authNav) return;

    authNav.innerHTML = `
        <a href="/login" class="nav-link px-4 py-2 rounded-xl bg-blue-600 text-white hover:bg-blue-700 transition font-medium shadow-lg shadow-blue-500/20 text-sm">Sign In / Register</a>
    `;
}

async function handleLogout() {
    try {
        await apiFetch('/api/auth/logout', { method: 'POST' });
        showToast('Logged out successfully', 'info');
        setTimeout(() => {
            window.location.href = 'login.html';
        }, 500);
    } catch (e) {
        console.error("Logout failed:", e);
        window.location.href = 'login.html';
    }
}

function setupThemeToggle() {
    const toggleBtn = document.getElementById('theme-toggle-btn');
    if (!toggleBtn) return;

    const currentTheme = localStorage.getItem('fintrust_theme') || 'dark';
    document.documentElement.setAttribute('data-theme', currentTheme);

    toggleBtn.addEventListener('click', () => {
        const theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('fintrust_theme', theme);
    });
}

function setupLanguageSelector() {
    const select = document.getElementById('language-select');
    if (!select) return;

    select.addEventListener('change', async (e) => {
        const lang = e.target.value;
        try {
            await apiFetch(`/set_language/${lang}`);
            window.location.reload();
        } catch (err) {
            console.error("Language switch failed:", err);
        }
    });
}

function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = 'position: fixed; bottom: 24px; right: 24px; z-index: 9999; display: flex; flex-direction: column; gap: 12px;';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const bgColors = {
        success: '#10B981',
        error: '#EF4444',
        info: '#3B82F6',
        warning: '#F59E0B'
    };

    toast.style.cssText = `
        background: ${bgColors[type] || '#3B82F6'};
        color: #ffffff;
        padding: 12px 20px;
        border-radius: 10px;
        font-weight: 500;
        font-size: 0.9rem;
        box-shadow: 0 10px 25px rgba(0,0,0,0.3);
        opacity: 0;
        transform: translateY(20px);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    `;
    toast.innerText = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '1';
        toast.style.transform = 'translateY(0)';
    }, 50);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(20px)';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}

window.showToast = showToast;
window.handleLogout = handleLogout;
