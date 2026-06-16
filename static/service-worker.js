/* global ClientCacheDb */
'use strict';

importScripts('/static/client-cache-db.js?v=3');

const SW_VERSION = 'queue-cache-v4';
let activeDownloadTag = null;
let lastApiBaseUrl = '';
let lastPrefetchAllowedFromPage = false;
let sequentialDownloadAbortController = null;
let connectionListenerAttached = false;

self.addEventListener('install', (event) => {
    event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener('message', (event) => {
    const data = event.data || {};
    if (data.type === 'SYNC_QUEUE') {
        event.waitUntil(handleSyncQueue(data));
        return;
    }
    if (data.type === 'ABORT_DOWNLOADS') {
        event.waitUntil(abortActiveDownloads());
        return;
    }
    if (data.type === 'CLEAR_DEVICE_CACHE') {
        event.waitUntil(handleClearCache());
        return;
    }
    if (data.type === 'QUEUE_REMOVE') {
        event.waitUntil(enqueueQueueMutation({ kind: 'remove', queueId: data.queueId }));
        return;
    }
    if (data.type === 'QUEUE_NEXT') {
        event.waitUntil(enqueueQueueMutation({ kind: 'next', queueId: data.queueId }));
        return;
    }
    if (data.type === 'FLUSH_QUEUE_MUTATIONS') {
        event.waitUntil(flushQueueMutations());
    }
});

self.addEventListener('backgroundfetchsuccess', (event) => {
    event.waitUntil(handleBackgroundFetchSuccess(event.registration));
});

self.addEventListener('backgroundfetchfail', (event) => {
    console.warn('Background fetch failed:', event.registration.id);
    notifyClients({ type: 'CACHE_UPDATED' });
});

self.addEventListener('backgroundfetchabort', () => {
    notifyClients({ type: 'CACHE_UPDATED' });
});

function isPrefetchAllowedInServiceWorker(apiBaseUrl, trustedFromPage) {
    const conn = self.navigator && self.navigator.connection;
    if (conn) {
        if (conn.saveData) {
            return false;
        }
        if (conn.type === 'wifi' || conn.type === 'ethernet') {
            return true;
        }
        if (conn.type === 'cellular') {
            return false;
        }
    }
    // When the OS does not expose connection type, trust the page (desktop is always true;
    // mobile defaults to false when type is unknown).
    return Boolean(trustedFromPage);
}

function ensureConnectionListener(apiBaseUrl) {
    if (connectionListenerAttached) {
        return;
    }
    const conn = self.navigator && self.navigator.connection;
    if (!conn || typeof conn.addEventListener !== 'function') {
        return;
    }
    conn.addEventListener('change', () => {
        if (!isPrefetchAllowedInServiceWorker(lastApiBaseUrl, lastPrefetchAllowedFromPage)) {
            abortActiveDownloads();
        }
    });
    connectionListenerAttached = true;
    if (apiBaseUrl) {
        lastApiBaseUrl = apiBaseUrl;
    }
}

function beginSequentialDownloadAbortController() {
    if (sequentialDownloadAbortController) {
        sequentialDownloadAbortController.abort();
    }
    sequentialDownloadAbortController = new AbortController();
    return sequentialDownloadAbortController;
}

async function abortActiveDownloads() {
    if (sequentialDownloadAbortController) {
        sequentialDownloadAbortController.abort();
        sequentialDownloadAbortController = null;
    }

    if (activeDownloadTag && self.registration.backgroundFetch && self.registration.backgroundFetch.get) {
        try {
            const existing = await self.registration.backgroundFetch.get(activeDownloadTag);
            if (existing) {
                await existing.abort();
            }
        } catch (e) {
            console.warn('Failed to abort background fetch:', e);
        }
        activeDownloadTag = null;
    }

    notifyClients({ type: 'CACHE_UPDATED' });
}

async function handleClearCache() {
    await abortActiveDownloads();
    await ClientCacheDb.clear();
    notifyClients({ type: 'CACHE_UPDATED' });
}

async function handleSyncQueue(data) {
    const items = Array.isArray(data.items) ? data.items : [];
    const apiBaseUrl = data.apiBaseUrl || '';
    const prefetchAllowed = Boolean(data.prefetchAllowed);
    lastPrefetchAllowedFromPage = prefetchAllowed;
    const queueVideoIds = items.map((item) => item.videoId).filter(Boolean);

    if (apiBaseUrl) {
        lastApiBaseUrl = apiBaseUrl;
    }
    ensureConnectionListener(apiBaseUrl);

    ClientCacheDb.configure({
        maxItems: data.maxItems || 5,
        maxMb: data.maxMb || 0,
        protectedVideoIds: queueVideoIds,
    });

    await ClientCacheDb.deleteExcept(queueVideoIds);

    if (!prefetchAllowed || !apiBaseUrl || items.length === 0) {
        await abortActiveDownloads();
        notifyClients({ type: 'CACHE_UPDATED' });
        return;
    }

    if (!isPrefetchAllowedInServiceWorker(apiBaseUrl, prefetchAllowed)) {
        await abortActiveDownloads();
        notifyClients({ type: 'CACHE_UPDATED' });
        return;
    }

    const pending = [];
    for (const item of items) {
        if (!item.videoId) {
            continue;
        }
        if (await ClientCacheDb.has(item.videoId)) {
            continue;
        }
        pending.push(item);
    }

    if (pending.length === 0) {
        notifyClients({ type: 'CACHE_UPDATED' });
        return;
    }

    const startedBackgroundFetch = await tryBackgroundFetch(pending, apiBaseUrl);
    if (!startedBackgroundFetch) {
        await downloadSequentially(pending, apiBaseUrl);
    }

    notifyClients({ type: 'CACHE_UPDATED' });
}

async function tryBackgroundFetch(pending, apiBaseUrl) {
    if (!self.registration.backgroundFetch) {
        return false;
    }

    const downloadTag = `queue-cache-${Date.now()}`;
    const readyItems = [];
    const signal = beginSequentialDownloadAbortController().signal;

    for (const item of pending) {
        if (signal.aborted || !isPrefetchAllowedInServiceWorker(apiBaseUrl, lastPrefetchAllowedFromPage)) {
            return false;
        }
        const ready = await ClientCacheDb.waitForServerAudio(item.videoId, 120000, signal);
        if (ready) {
            readyItems.push(item);
        }
    }

    if (readyItems.length === 0 || signal.aborted
        || !isPrefetchAllowedInServiceWorker(apiBaseUrl, lastPrefetchAllowedFromPage)) {
        return false;
    }

    try {
        if (activeDownloadTag && self.registration.backgroundFetch.get) {
            const existing = await self.registration.backgroundFetch.get(activeDownloadTag);
            if (existing) {
                await existing.abort();
            }
        }

        const urls = readyItems.map((item) => `/audio/${item.videoId}`);
        await self.registration.backgroundFetch.fetch(downloadTag, urls, {
            title: `Caching ${readyItems.length} queued track${readyItems.length === 1 ? '' : 's'}`,
            downloadTotal: readyItems.length,
        });
        activeDownloadTag = downloadTag;
        sequentialDownloadAbortController = null;
        return true;
    } catch (e) {
        console.warn('Background Fetch unavailable, falling back to service worker fetch:', e);
        return false;
    }
}

async function handleBackgroundFetchSuccess(registration) {
    if (!registration || !registration.matchAll) {
        notifyClients({ type: 'CACHE_UPDATED' });
        return;
    }

    try {
        const records = await registration.matchAll();
        for (const record of records) {
            const response = await record.responseReady;
            if (!response || !response.ok) {
                continue;
            }
            const videoId = ClientCacheDb.extractVideoIdFromAudioUrl(record.request.url);
            if (!videoId) {
                continue;
            }
            const blob = await response.blob();
            await ClientCacheDb.put(videoId, blob, { title: '' });
        }
    } catch (e) {
        console.warn('Failed to persist background fetch results:', e);
    }

    activeDownloadTag = null;
    notifyClients({ type: 'CACHE_UPDATED' });
}

async function downloadSequentially(pending, apiBaseUrl) {
    const controller = beginSequentialDownloadAbortController();
    const signal = controller.signal;

    for (const item of pending) {
        if (signal.aborted || !isPrefetchAllowedInServiceWorker(apiBaseUrl, lastPrefetchAllowedFromPage)) {
            break;
        }
        if (await ClientCacheDb.has(item.videoId)) {
            continue;
        }

        const ready = await ClientCacheDb.waitForServerAudio(item.videoId, 120000, signal);
        if (!ready || signal.aborted
            || !isPrefetchAllowedInServiceWorker(apiBaseUrl, lastPrefetchAllowedFromPage)) {
            break;
        }

        try {
            const response = await fetch(`/audio/${item.videoId}`, { signal });
            if (!response.ok) {
                continue;
            }
            const blob = await response.blob();
            await ClientCacheDb.put(item.videoId, blob, { title: item.title || '' });
            notifyClients({ type: 'CACHE_UPDATED', videoId: item.videoId });
        } catch (e) {
            if (signal.aborted) {
                break;
            }
            console.warn(`Service worker download failed for ${item.videoId}:`, e);
        }
    }

    sequentialDownloadAbortController = null;
}

async function notifyClients(message) {
    const clients = await self.clients.matchAll({
        type: 'window',
        includeUncontrolled: true,
    });
    for (const client of clients) {
        client.postMessage(message);
    }
}

const MUTATION_DB_NAME = 'audio-stream-queue-sync';
const MUTATION_STORE = 'mutations';

function openMutationDb() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(MUTATION_DB_NAME, 1);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);
        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains(MUTATION_STORE)) {
                db.createObjectStore(MUTATION_STORE, { keyPath: 'id', autoIncrement: true });
            }
        };
    });
}

async function enqueueQueueMutation(mutation) {
    if (!mutation || !mutation.kind) {
        return;
    }
    const db = await openMutationDb();
    await new Promise((resolve, reject) => {
        const tx = db.transaction(MUTATION_STORE, 'readwrite');
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
        tx.objectStore(MUTATION_STORE).add({
            kind: mutation.kind,
            queueId: mutation.queueId ?? null,
            createdAt: Date.now(),
        });
    });
    await flushQueueMutations();
}

async function listQueueMutations() {
    const db = await openMutationDb();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(MUTATION_STORE, 'readonly');
        const request = tx.objectStore(MUTATION_STORE).getAll();
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
    });
}

async function deleteQueueMutation(id) {
    const db = await openMutationDb();
    await new Promise((resolve, reject) => {
        const tx = db.transaction(MUTATION_STORE, 'readwrite');
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
        tx.objectStore(MUTATION_STORE).delete(id);
    });
}

async function applyQueueMutation(mutation) {
    if (mutation.kind === 'remove') {
        const response = await fetch(`/queue/${mutation.queueId}`, { method: 'DELETE' });
        return response.ok || response.status === 404;
    }
    if (mutation.kind === 'next') {
        const body = mutation.queueId != null ? JSON.stringify({ queue_id: mutation.queueId }) : '{}';
        const response = await fetch('/queue/next', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body,
        });
        return response.ok;
    }
    return true;
}

async function flushQueueMutations() {
    const mutations = await listQueueMutations();
    mutations.sort((a, b) => a.id - b.id);

    for (const mutation of mutations) {
        try {
            const ok = await applyQueueMutation(mutation);
            if (!ok) {
                break;
            }
            await deleteQueueMutation(mutation.id);
        } catch (e) {
            console.warn('Queue mutation sync paused:', e);
            break;
        }
    }

    notifyClients({ type: 'QUEUE_MUTATIONS_FLUSHED' });
}
