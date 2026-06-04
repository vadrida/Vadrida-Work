const CACHE_NAME = 'vadrida-v8'; // Bumped: fixed navigate mode Request constructor
const ASSETS_TO_CACHE = [
    '/',
    '/static/js/vadrida_offline.js',
    '/static/offline.html',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.3/css/all.min.css',
    'https://cdn.tailwindcss.com',
    'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js',
    'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js'
];

// 1. Install Event
self.addEventListener('install', (event) => {
    console.log('[SW] Installing version:', CACHE_NAME);
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return Promise.all(
                ASSETS_TO_CACHE.map(url => {
                    return fetch(url).then(response => {
                        if (response.ok) return cache.put(url, response);
                    }).catch(err => console.error('[SW] Pre-cache failed:', url));
                })
            );
        })
    );
});

// 2. Activate Event
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)));
        })
    );
});

// 3. Fetch Event
self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    
    const url = new URL(event.request.url);

    // CRITICAL: Do NOT intercept or cache Admin, API, or Signing requests
    if (url.pathname.startsWith('/admin/') || 
        url.pathname.startsWith('/coreapi/api/') ||
        url.pathname.includes('/digital-sign/')) {
        return;
    }

    // Only handle same-origin or specific CDNs
    if (!event.request.url.startsWith('http')) return;

    let fetchRequest = event.request;

    event.respondWith(
        fetch(fetchRequest)
            .then((response) => {
                if (response.ok) {
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, responseClone);
                    });
                    return response;
                }
                
                // If 5xx error, try EXACT match in cache (No ignoreSearch for HTML)
                if (response.status >= 500) {
                    return caches.match(event.request).then((cachedResponse) => {
                        if (cachedResponse) return cachedResponse;
                        if (event.request.mode === 'navigate') return caches.match('/static/offline.html');
                        return response;
                    });
                }
                return response;
            })
            .catch(() => {
                // Network failure
                return caches.match(event.request).then((cachedResponse) => {
                    if (cachedResponse) return cachedResponse;
                    if (event.request.mode === 'navigate') return caches.match('/static/offline.html');
                });
            })
    );
});
