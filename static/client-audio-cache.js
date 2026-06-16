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
    let downloadAbortController = null;

    function createDownloadAbortController() {
        if (downloadAbortController) {
            downloadAbortController.abort();
        }
        downloadAbortController = new AbortController();
        return downloadAbortController;
    }

    function abortDownloads() {
        if (downloadAbortController) {
            downloadAbortController.abort();
            downloadAbortController = null;
        }
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
            signal = createDownloadAbortController().signal;
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

    async function prefetch(videoId) {
        if (!isEnabled() || !videoId || prefetchInFlight.has(`prefetch:${videoId}`)) {
            return;
        }

        if (await has(videoId)) {
            return;
        }

        prefetchInFlight.add(`prefetch:${videoId}`);
        const controller = createDownloadAbortController();
        try {
            const ready = await ClientCacheDb.waitForServerAudio(
                videoId,
                120000,
                controller.signal
            );
            if (!ready) {
                return;
            }
            await storeFromServer(videoId, '', controller.signal);
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
