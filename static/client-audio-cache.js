/**
 * Client-side audio cache using IndexedDB.
 * Stores MP3 blobs on the device for faster replays and offline playback.
 */
const clientAudioCache = (function () {
    let enabled = false;
    let apiBaseUrl = '';
    let initPromise = null;
    let activeBlobUrl = null;
    const prefetchInFlight = new Set();
    const prefetchQueue = [];
    const prefetchPromises = new Map();
    let prefetchWorkerRunning = false;
    let batchAbortController = null;
    let standaloneAbortController = null;

    function beginBatchAbortController() {
        if (batchAbortController) {
            batchAbortController.abort();
        }
        batchAbortController = new AbortController();
        return batchAbortController;
    }

    function createStandaloneAbortController() {
        if (standaloneAbortController) {
            standaloneAbortController.abort();
        }
        standaloneAbortController = new AbortController();
        return standaloneAbortController;
    }

    function abortDownloads() {
        if (batchAbortController) {
            batchAbortController.abort();
            batchAbortController = null;
        }
        if (standaloneAbortController) {
            standaloneAbortController.abort();
            standaloneAbortController = null;
        }
        while (prefetchQueue.length > 0) {
            const entry = prefetchQueue.shift();
            entry.reject(new DOMException('Aborted', 'AbortError'));
        }
        prefetchPromises.clear();
        prefetchWorkerRunning = false;
    }

    function isEnabled() {
        return enabled && typeof ClientCacheDb !== 'undefined';
    }

    async function init(config) {
        if (initPromise) {
            return initPromise;
        }

        initPromise = (async () => {
            enabled = Boolean(config && config.enabled);
            apiBaseUrl = (config && config.apiBaseUrl) || '';

            if (!enabled) {
                return false;
            }

            if (typeof indexedDB === 'undefined' || typeof ClientCacheDb === 'undefined') {
                enabled = false;
                return false;
            }

            try {
                ClientCacheDb.configure({
                    maxItems: (config && config.maxItems) || 5,
                    maxMb: (config && config.maxMb) || 0,
                });
                await ClientCacheDb.listVideoIds();
                return true;
            } catch (e) {
                console.warn('Client audio cache disabled:', e);
                enabled = false;
                return false;
            }
        })();

        return initPromise;
    }

    async function has(videoId) {
        if (!isEnabled() || !videoId) {
            return false;
        }
        return ClientCacheDb.has(videoId);
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
        return ClientCacheDb.put(videoId, blob, metadata);
    }

    async function remove(videoId) {
        if (!isEnabled() || !videoId) {
            return;
        }
        await ClientCacheDb.remove(videoId);
    }

    async function clear() {
        if (!isEnabled()) {
            return;
        }
        revokeActiveBlobUrl();
        abortDownloads();
        await ClientCacheDb.clear();
    }

    async function getStats() {
        if (!isEnabled()) {
            return { count: 0, maxItems: 5, totalMb: 0 };
        }
        return ClientCacheDb.getStats();
    }

    async function listVideoIds() {
        if (!isEnabled()) {
            return [];
        }
        return ClientCacheDb.listVideoIds();
    }

    function setProtectedVideoIds(videoIds) {
        if (!isEnabled()) {
            return;
        }
        ClientCacheDb.setProtectedVideoIds(videoIds);
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

        const entry = await ClientCacheDb.getEntry(videoId);
        if (!entry || !(entry.blob instanceof Blob)) {
            return null;
        }

        await ClientCacheDb.touch(videoId);

        revokeActiveBlobUrl();
        activeBlobUrl = URL.createObjectURL(entry.blob);
        return activeBlobUrl;
    }

    async function storeFromServer(videoId, title, externalSignal) {
        if (!isEnabled() || !videoId || prefetchInFlight.has(`store:${videoId}`)) {
            return false;
        }

        if (await has(videoId)) {
            return true;
        }

        prefetchInFlight.add(`store:${videoId}`);
        let signal = externalSignal;
        if (!signal) {
            signal = createStandaloneAbortController().signal;
        }
        try {
            const ready = await ClientCacheDb.waitForServerAudio(videoId, 5000, signal);
            if (!ready) {
                return false;
            }

            const response = await fetch(`/audio/${videoId}`, { signal });
            if (!response.ok) {
                return false;
            }

            const blob = await response.blob();
            return await put(videoId, blob, { title: title || '' });
        } catch (e) {
            if (signal.aborted) {
                return false;
            }
            console.warn(`Client cache store failed for ${videoId}:`, e);
            return false;
        } finally {
            prefetchInFlight.delete(`store:${videoId}`);
        }
    }

    async function downloadPrefetchedVideo(videoId, signal) {
        prefetchInFlight.add(`prefetch:${videoId}`);
        try {
            const ready = await ClientCacheDb.waitForServerAudio(
                videoId,
                120000,
                signal
            );
            if (!ready || signal.aborted) {
                return false;
            }
            return await storeFromServer(videoId, '', signal);
        } finally {
            prefetchInFlight.delete(`prefetch:${videoId}`);
        }
    }

    async function runPrefetchWorker() {
        if (prefetchWorkerRunning) {
            return;
        }
        prefetchWorkerRunning = true;
        const controller = beginBatchAbortController();
        const signal = controller.signal;

        try {
            while (prefetchQueue.length > 0 && !signal.aborted) {
                const entry = prefetchQueue.shift();
                if (!entry) {
                    continue;
                }

                try {
                    if (await has(entry.videoId)) {
                        entry.resolve(true);
                        continue;
                    }

                    const stored = await downloadPrefetchedVideo(entry.videoId, signal);
                    entry.resolve(stored);
                } catch (e) {
                    entry.reject(e);
                }
            }
        } finally {
            prefetchWorkerRunning = false;
            if (prefetchQueue.length > 0 && !signal.aborted) {
                runPrefetchWorker().catch((e) => {
                    console.warn('Client cache prefetch worker failed:', e);
                });
            }
        }
    }

    function prefetch(videoId) {
        if (!isEnabled() || !videoId) {
            return Promise.resolve(false);
        }
        if (prefetchPromises.has(videoId)) {
            return prefetchPromises.get(videoId);
        }

        const promise = new Promise((resolve, reject) => {
            prefetchQueue.push({ videoId, resolve, reject });
            runPrefetchWorker().catch((e) => {
                console.warn('Client cache prefetch worker failed:', e);
            });
        });
        prefetchPromises.set(videoId, promise);
        promise.finally(() => {
            prefetchPromises.delete(videoId);
        });
        return promise;
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
        listVideoIds,
        setProtectedVideoIds,
        revokeActiveBlobUrl,
        createObjectUrl,
        storeFromServer,
        prefetch,
        abortDownloads,
        checkStorageQuota,
    };
})();
