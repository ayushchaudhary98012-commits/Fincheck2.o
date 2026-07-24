/**
 * FinTrust AI - Standalone Frontend API Configuration
 * Supports decoupled deployment (Vercel / Netlify / Cloudflare Pages)
 * communicating with Flask REST API (Render / Railway / Heroku / AWS).
 */

const API_BASE_URL = window.API_BASE_URL || (
    window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
        ? 'http://127.0.0.1:5000'
        : 'https://fintrust-backend-api.onrender.com' // Replace with your live backend Render/Railway URL
);

/**
 * Universal cross-origin fetch helper with session credentials support.
 */
async function apiFetch(endpoint, options = {}) {
    const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
    
    const defaultHeaders = {
        'Accept': 'application/json',
    };

    if (options.body && !(options.body instanceof FormData)) {
        defaultHeaders['Content-Type'] = 'application/json';
    }

    const config = {
        ...options,
        headers: {
            ...defaultHeaders,
            ...options.headers
        },
        credentials: 'include' // Essential for Flask cross-origin session cookies
    };

    try {
        const response = await fetch(url, config);
        return response;
    } catch (err) {
        console.error(`[API Error] Failed to fetch ${url}:`, err);
        throw err;
    }
}

window.API_BASE_URL = API_BASE_URL;
window.apiFetch = apiFetch;
