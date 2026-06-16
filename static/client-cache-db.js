/**
 * Shared IndexedDB storage for client-side audio cache.
 * Loaded in the page and via importScripts() in the service worker.
 */
var ClientCacheDb = (function () {
    const DB_NAME = 'audio-stream-client-cache';
    const DB_VERSION = 1;
    const STORE_NAME = 'audio_files';

    let dbPromise = null;
    let maxItems = 5;
    let maxMb = 0;
    let protectedVideoIds = new Set();

    function configure(options) {
        if (!options) {
            return;
        }
        if (options.maxItems !== undefined) {
            maxItems = options.maxItems;
        }
        if (options.maxMb !== undefined) {
            maxMb = options.maxMb;
        }
        if (options.protectedVideoIds) {
            protectedVideoIds = new Set(options.protectedVideoIds);
        }
    }

    function setProtectedVideoIds(videoIds) {
        protectedVideoIds = new Set(videoIds || []);
    }

    function openDb() {
        if (dbPromise) {
            return dbPromise;
        }

        dbPromise = new Promise((resolve, reject) => {
            if (typeof indexedDB === 'undefined') {
                reject(new Error('IndexedDB unavailable'));
                return;
            }

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

        return dbPromise;
    }

    function tx(mode) {
        return openDb().then((db) => db.transaction(STORE_NAME, mode).objectStore(STORE_NAME));
    }

    function getAllEntries() {
        return tx('readonly').then((store) => new Promise((resolve, reject) => {
            const request = store.getAll();
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => reject(request.error);
        }));
    }

    function getEntry(videoId) {
        return tx('readonly').then((store) => new Promise((resolve, reject) => {
            const request = store.get(videoId);
            request.onsuccess = () => resolve(request.result || null);
            request.onerror = () => reject(request.error);
        }));
    }

    async function touch(videoId) {
        const entry = await getEntry(videoId);
        if (!entry) {
            return;
        }
        entry.cachedAt = Date.now();
        await putEntry(entry);
    }

    function putEntry(entry) {
        return tx('readwrite').then((store) => new Promise((resolve, reject) => {
            const request = store.put(entry);
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        }));
    }

    function deleteEntry(videoId) {
        return tx('readwrite').then((store) => new Promise((resolve, reject) => {
            const request = store.delete(videoId);
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        }));
    }

    function isProtected(videoId) {
        return protectedVideoIds.has(videoId);
    }

    function nextEvictableEntry(entries) {
        for (let i = 0; i < entries.length; i += 1) {
            if (!isProtected(entries[i].videoId)) {
                return entries.splice(i, 1)[0];
            }
        }
        return null;
    }

    async function evictIfNeeded() {
        let entries = await getAllEntries();
        entries.sort((a, b) => a.cachedAt - b.cachedAt);

        const totalBytes = () => entries.reduce((sum, entry) => sum + (entry.sizeBytes || 0), 0);

        while (entries.length > maxItems) {
            const oldest = nextEvictableEntry(entries);
            if (!oldest) {
                break;
            }
            await deleteEntry(oldest.videoId);
        }

        if (maxMb > 0) {
            const maxBytes = maxMb * 1024 * 1024;
            while (entries.length > 0 && totalBytes() > maxBytes) {
                const oldest = nextEvictableEntry(entries);
                if (!oldest) {
                    break;
                }
                await deleteEntry(oldest.videoId);
            }
        }
    }

    async function has(videoId) {
        if (!videoId) {
            return false;
        }
        const entry = await getEntry(videoId);
        return entry !== null && entry.blob instanceof Blob;
    }

    async function put(videoId, blob, metadata) {
        if (!videoId || !(blob instanceof Blob)) {
            return false;
        }

        await putEntry({
            videoId,
            blob,
            sizeBytes: blob.size,
            title: (metadata && metadata.title) || '',
            cachedAt: Date.now(),
        });
        await evictIfNeeded();
        return true;
    }

    async function remove(videoId) {
        if (!videoId) {
            return;
        }
        await deleteEntry(videoId);
    }

    async function clear() {
        const entries = await getAllEntries();
        await Promise.all(entries.map((entry) => deleteEntry(entry.videoId)));
    }

    async function listVideoIds() {
        const entries = await getAllEntries();
        return entries.map((entry) => entry.videoId);
    }

    async function deleteExcept(keepVideoIds) {
        const keepSet = new Set(keepVideoIds || []);
        const cachedIds = await listVideoIds();
        for (const videoId of cachedIds) {
            if (!keepSet.has(videoId)) {
                await remove(videoId);
            }
        }
    }

    async function getStats() {
        const entries = await getAllEntries();
        const totalBytes = entries.reduce((sum, entry) => sum + (entry.sizeBytes || 0), 0);
        return {
            count: entries.length,
            maxItems,
            totalMb: Math.round((totalBytes / (1024 * 1024)) * 10) / 10,
        };
    }

    async function waitForServerAudio(videoId, maxWaitMs, signal) {
        const start = Date.now();
        let attempt = 0;
        while (Date.now() - start < maxWaitMs) {
            if (signal && signal.aborted) {
                return false;
            }
            attempt += 1;
            try {
                const response = await fetch(`/audio/${videoId}`, {
                    method: 'HEAD',
                    signal,
                });
                if (response.ok) {
                    return true;
                }
            } catch (e) {
                if (signal && signal.aborted) {
                    return false;
                }
            }
            const waitMs = Math.min(500 + attempt * 100, 2000);
            await new Promise((resolve) => setTimeout(resolve, waitMs));
        }
        return false;
    }

    function extractVideoIdFromAudioUrl(url) {
        try {
            const pathname = new URL(url).pathname;
            const parts = pathname.split('/');
            return parts[parts.length - 1] || null;
        } catch (e) {
            return null;
        }
    }

    return {
        configure,
        setProtectedVideoIds,
        has,
        put,
        remove,
        clear,
        listVideoIds,
        deleteExcept,
        getStats,
        getEntry,
        touch,
        waitForServerAudio,
        extractVideoIdFromAudioUrl,
    };
})();
