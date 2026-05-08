/**
 * Vadrida Offline-First Sync Engine
 * Handles IndexedDB persistence and background server synchronization.
 */

const VadridaSync = (function() {
    const DB_NAME = 'vadrida_offline_db';
    const DB_VERSION = 1;
    const STORE_NAME = 'form_drafts';

    let db;

    // 1. Initialize IndexedDB
    const initDB = () => {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);
            request.onerror = (event) => reject("DB Error: " + event.target.errorCode);
            request.onsuccess = (event) => {
                db = event.target.result;
                resolve(db);
            };
            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains(STORE_NAME)) {
                    db.createObjectStore(STORE_NAME, { keyPath: 'id' });
                }
            };
        });
    };

    // 2. Save Draft Locally
    const saveLocal = async (pageKey, data) => {
        if (!db) await initDB();
        return new Promise((resolve, reject) => {
            const transaction = db.transaction([STORE_NAME], 'readwrite');
            const store = transaction.objectStore(STORE_NAME);
            const entry = {
                id: pageKey,
                data: data,
                updatedAt: new Date().toISOString(),
                synced: false
            };
            const request = store.put(entry);
            request.onsuccess = () => resolve(true);
            request.onerror = () => reject(false);
        });
    };

    // 3. Load Draft Locally
    const loadLocal = async (pageKey) => {
        if (!db) await initDB();
        return new Promise((resolve, reject) => {
            const transaction = db.transaction([STORE_NAME], 'readonly');
            const store = transaction.objectStore(STORE_NAME);
            const request = store.get(pageKey);
            request.onsuccess = () => resolve(request.result ? request.result.data : null);
            request.onerror = () => reject(null);
        });
    };

    // 4. Cache List Locally
    const cacheList = async (key, listData) => {
        return saveLocal(`list_cache_${key}`, {
            timestamp: Date.now(),
            data: listData
        });
    };

    // 5. Get Cached List
    const getCachedList = async (key) => {
        const cached = await loadLocal(`list_cache_${key}`);
        return cached ? cached.data : null;
    };

    // 6. Update UI Status
    const updateUI = (status) => {
        VadridaSync.status = status; // Expose status for other scripts
        const indicator = document.getElementById('vadridaSyncIndicator');
        const icon = document.getElementById('vadridaSyncIcon');
        const text = document.getElementById('vadridaSyncText');

        if (!indicator || !icon || !text) return;

        switch(status) {
            case 'online':
                indicator.className = 'flex items-center gap-2 px-3 py-1 rounded-full bg-green-100 text-green-700 text-xs font-bold transition-all duration-300';
                icon.className = 'fas fa-cloud';
                text.textContent = 'Online';
                break;
            case 'offline':
                indicator.className = 'flex items-center gap-2 px-3 py-1 rounded-full bg-red-100 text-red-700 text-xs font-bold animate-pulse transition-all duration-300';
                icon.className = 'fas fa-cloud-download-alt';
                text.textContent = 'Offline (Local Save)';
                break;
            case 'syncing':
                indicator.className = 'flex items-center gap-2 px-3 py-1 rounded-full bg-blue-100 text-blue-700 text-xs font-bold transition-all duration-300';
                icon.className = 'fas fa-sync-alt fa-spin';
                text.textContent = 'Syncing...';
                break;
        }
    };

    // 5. Detect Connectivity
    window.addEventListener('online', () => updateUI('online'));
    window.addEventListener('offline', () => updateUI('offline'));

    return {
        init: initDB,
        save: saveLocal,
        load: loadLocal,
        cacheList: cacheList,
        getCachedList: getCachedList,
        setStatus: updateUI
    };
})();

// Auto-initialize on load
document.addEventListener('DOMContentLoaded', () => {
    VadridaSync.init();
    if (!navigator.onLine) VadridaSync.setStatus('offline');
});
