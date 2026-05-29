/**
 * Client-side audio cache using IndexedDB.
 * Stores MP3 blobs on the device for faster replays and offline playback.
 */
const clientAudioCache = (function () {
    const DB_NAME = 'audio-stream-client-cache';
    const DB_VERSION = 1;
    const STORE_NAME = 'audio_files';

    let enabled = false;
    let maxItems = 5;
    let maxMb = 0;
    let apiBaseUrl = '';
    let db = null;
    let initPromise = null;
    let activeBlobUrl = null;
    const prefetchInFlight = new Set();

    function isEnabled() {
        return enabled && db !== null;
    }

    function _tx(storeName, mode) {
        return db.transaction(storeName, mode).objectStore(storeName);
    }

    function _getAllEntries() {
        return new Promise((resolve, reject) => {
            const request = _tx(STORE_NAME, 'readonly').getAll();
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => reject(request.error);
        });
    }

    function _getEntry(videoId) {
        return new Promise((resolve, reject) => {
            const request = _tx(STORE_NAME, 'readonly').get(videoId);
            request.onsuccess = () => resolve(request.result || null);
            request.onerror = () => reject(request.error);
        });
    }

    function _putEntry(entry) {
        return new Promise((resolve, reject) => {
            const request = _tx(STORE_NAME, 'readwrite').put(entry);
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });
    }

    function _deleteEntry(videoId) {
        return new Promise((resolve, reject) => {
            const request = _tx(STORE_NAME, 'readwrite').delete(videoId);
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });
    }

    async function _evictIfNeeded() {
        if (!isEnabled()) {
            return;
        }

        let entries = await _getAllEntries();
        entries.sort((a, b) => a.cachedAt - b.cachedAt);

        const totalBytes = () => entries.reduce((sum, e) => sum + (e.sizeBytes || 0), 0);

        while (entries.length > maxItems) {
            const oldest = entries.shift();
            await _deleteEntry(oldest.videoId);
        }

        if (maxMb > 0) {
            const maxBytes = maxMb * 1024 * 1024;
            while (entries.length > 0 && totalBytes() > maxBytes) {
                const oldest = entries.shift();
                await _deleteEntry(oldest.videoId);
            }
        }
    }

    async function _waitForServerAudio(videoId, maxWaitMs) {
        const start = Date.now();
        let attempt = 0;
        while (Date.now() - start < maxWaitMs) {
            attempt += 1;
            try {
                const url = `${apiBaseUrl}/audio/${videoId}`;
                const response = await fetch(url, { method: 'HEAD' });
                if (response.ok) {
                    return true;
                }
            } catch (e) {
                /* retry */
            }
            const waitMs = Math.min(500 + attempt * 100, 2000);
            await new Promise((resolve) => setTimeout(resolve, waitMs));
        }
        return false;
    }

    async function init(config) {
        if (initPromise) {
            return initPromise;
        }

        initPromise = (async () => {
            enabled = Boolean(config && config.enabled);
            maxItems = (config && config.maxItems) || 5;
            maxMb = (config && config.maxMb) || 0;
            apiBaseUrl = (config && config.apiBaseUrl) || '';

            if (!enabled) {
                return false;
            }

            if (typeof indexedDB === 'undefined') {
                enabled = false;
                return false;
            }

            try {
                db = await new Promise((resolve, reject) => {
                    const request = indexedDB.open(DB_NAME, DB_VERSION);
                    request.onerror = () => reject(request.error);
                    request.onsuccess = () => resolve(request.result);
                    request.onupgradeneeded = (event) => {
                        const database = event.target.result;
                        if (!database.objectStoreNames.contains(STORE_NAME)) {
                            database.createObjectStore(STORE_NAME, { keyPath: 'videoId' });
                        }
                    };
                });
                return true;
            } catch (e) {
                console.warn('Client audio cache disabled:', e);
                enabled = false;
                db = null;
                return false;
            }
        })();

        return initPromise;
    }

    async function has(videoId) {
        if (!isEnabled() || !videoId) {
            return false;
        }
        const entry = await _getEntry(videoId);
        return entry !== null && entry.blob instanceof Blob;
    }

    async function hasMany(videoIds) {
        const result = new Set();
        if (!isEnabled() || !videoIds || videoIds.length === 0) {
            return result;
        }
        for (const videoId of videoIds) {
            if (await has(videoId)) {
                result.add(videoId);
            }
        }
        return result;
    }

    async function put(videoId, blob, metadata) {
        if (!isEnabled() || !videoId || !(blob instanceof Blob)) {
            return false;
        }

        const entry = {
            videoId,
            blob,
            sizeBytes: blob.size,
            title: (metadata && metadata.title) || '',
            cachedAt: Date.now(),
        };

        await _putEntry(entry);
        await _evictIfNeeded();
        return true;
    }

    async function remove(videoId) {
        if (!isEnabled() || !videoId) {
            return;
        }
        await _deleteEntry(videoId);
    }

    async function clear() {
        if (!isEnabled()) {
            return;
        }
        revokeActiveBlobUrl();
        const entries = await _getAllEntries();
        await Promise.all(entries.map((e) => _deleteEntry(e.videoId)));
    }

    async function getStats() {
        if (!isEnabled()) {
            return { count: 0, maxItems, totalMb: 0 };
        }
        const entries = await _getAllEntries();
        const totalBytes = entries.reduce((sum, e) => sum + (e.sizeBytes || 0), 0);
        return {
            count: entries.length,
            maxItems,
            totalMb: Math.round((totalBytes / (1024 * 1024)) * 10) / 10,
        };
    }

    function revokeActiveBlobUrl() {
        if (activeBlobUrl) {
            URL.revokeObjectURL(activeBlobUrl);
            activeBlobUrl = null;
        }
    }

    async function createObjectUrl(videoId) {
        if (!isEnabled() || !videoId) {
            return null;
        }

        const entry = await _getEntry(videoId);
        if (!entry || !(entry.blob instanceof Blob)) {
            return null;
        }

        entry.cachedAt = Date.now();
        await _putEntry(entry);

        revokeActiveBlobUrl();
        activeBlobUrl = URL.createObjectURL(entry.blob);
        return activeBlobUrl;
    }

    async function storeFromServer(videoId, title) {
        if (!isEnabled() || !videoId || prefetchInFlight.has(`store:${videoId}`)) {
            return false;
        }

        if (await has(videoId)) {
            return true;
        }

        prefetchInFlight.add(`store:${videoId}`);
        try {
            const ready = await _waitForServerAudio(videoId, 5000);
            if (!ready) {
                return false;
            }

            const url = `${apiBaseUrl}/audio/${videoId}`;
            const response = await fetch(url);
            if (!response.ok) {
                return false;
            }

            const blob = await response.blob();
            return await put(videoId, blob, { title: title || '' });
        } catch (e) {
            console.warn(`Client cache store failed for ${videoId}:`, e);
            return false;
        } finally {
            prefetchInFlight.delete(`store:${videoId}`);
        }
    }

    async function prefetch(videoId) {
        if (!isEnabled() || !videoId || prefetchInFlight.has(`prefetch:${videoId}`)) {
            return;
        }

        if (await has(videoId)) {
            return;
        }

        prefetchInFlight.add(`prefetch:${videoId}`);
        try {
            const ready = await _waitForServerAudio(videoId, 120000);
            if (!ready) {
                return;
            }
            await storeFromServer(videoId, '');
        } finally {
            prefetchInFlight.delete(`prefetch:${videoId}`);
        }
    }

    async function checkStorageQuota() {
        if (!navigator.storage || !navigator.storage.estimate) {
            return null;
        }
        try {
            const estimate = await navigator.storage.estimate();
            if (!estimate.quota || !estimate.usage) {
                return null;
            }
            const ratio = estimate.usage / estimate.quota;
            return ratio > 0.8 ? ratio : null;
        } catch (e) {
            return null;
        }
    }

    return {
        init,
        isEnabled,
        has,
        hasMany,
        put,
        remove,
        clear,
        getStats,
        revokeActiveBlobUrl,
        createObjectUrl,
        storeFromServer,
        prefetch,
        checkStorageQuota,
    };
})();
