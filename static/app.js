// Audio Stream Server - Main Application JavaScript
// This file expects a global `appConfig` object to be defined before loading

const player = document.getElementById('player');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status');
const streamStatus = document.getElementById('stream-status');
const streamStatusText = document.getElementById('stream-status-text');
const MAX_HISTORY_ITEMS = 10;
const transcriptionEnabled = appConfig.transcriptionEnabled;
let currentVideoId = null;
let currentQueueId = null;
let isPlaying = false;
let currentTrackTitle = null;
const defaultTitle = 'YouTube Radio';

// Prefetch configuration
const prefetchThresholdSeconds = appConfig.prefetchThresholdSeconds;
let prefetchTriggered = false;

// Remote logging for debugging on phone/car displays
const REMOTE_LOGGING_ENABLED = true;
const LOG_BATCH_INTERVAL = appConfig.clientLogBatchInterval;
let logBuffer = [];
let logBatchTimer = null;

// Remote logging function - sends logs to server
function remoteLog(level, message, context = {}) {
    const timestamp = new Date().toISOString();

    // Add to buffer
    logBuffer.push({
        level: level,
        message: message,
        timestamp: timestamp,
        context: context
    });

    // Also log to console
    const consoleMethod = console[level] || console.log;
    if (Object.keys(context).length > 0) {
        consoleMethod(`[${level.toUpperCase()}]`, message, context);
    } else {
        consoleMethod(`[${level.toUpperCase()}]`, message);
    }

    // Start batch timer if not already running
    if (REMOTE_LOGGING_ENABLED && !logBatchTimer) {
        logBatchTimer = setTimeout(flushLogs, LOG_BATCH_INTERVAL);
    }
}

// Send buffered logs to server
async function flushLogs() {
    if (logBuffer.length === 0) {
        logBatchTimer = null;
        return;
    }

    const logsToSend = [...logBuffer];
    logBuffer = [];
    logBatchTimer = null;

    try {
        await fetch('/admin/client-logs', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(logsToSend),
        });
    } catch (e) {
        // Silently fail - don't want logging to break the app
        console.debug('Failed to send remote logs:', e);
    }
}

// Flush logs on page unload
window.addEventListener('beforeunload', () => {
    if (logBuffer.length > 0) {
        // Use sendBeacon for reliability during page unload
        const blob = new Blob([JSON.stringify(logBuffer)], { type: 'application/json' });
        navigator.sendBeacon('/admin/client-logs', blob);
    }
});

// Stream resilience configuration
let retryCount = 0;
let maxRetries = 50; // Increased for long network transitions (5G↔WiFi)
let retryDelay = 1000; // Start with 1 second
let maxRetryDelay = 10000; // Max 10 seconds between retries (faster recovery)
let retryTimeout = null;
let lastPlayPosition = 0;
let isRetrying = false;
let stalledTimeout = null;
let bufferingStartTime = null;
let isSeeking = false;

// Theme Management
function getSystemTheme() {
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function initTheme() {
    const savedTheme = localStorage.getItem('theme');
    const themeIcon = document.getElementById('theme-icon');

    if (savedTheme) {
        document.documentElement.setAttribute('data-theme', savedTheme);
        updateThemeIcon(savedTheme);
    } else {
        const systemTheme = getSystemTheme();
        updateThemeIcon(systemTheme);
    }
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const systemTheme = getSystemTheme();
    let newTheme;

    if (!currentTheme) {
        // First toggle: switch from system default to opposite
        newTheme = systemTheme === 'light' ? 'dark' : 'light';
    } else if (currentTheme === systemTheme) {
        // Currently matching system, switch to opposite
        newTheme = systemTheme === 'light' ? 'dark' : 'light';
    } else {
        // Currently opposite of system, go back to system (remove override)
        document.documentElement.removeAttribute('data-theme');
        localStorage.removeItem('theme');
        updateThemeIcon(systemTheme);
        return;
    }

    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    updateThemeIcon(newTheme);
}

function updateThemeIcon(theme) {
    const themeIcon = document.getElementById('theme-icon');
    if (theme === 'light') {
        themeIcon.className = 'fas fa-moon';
    } else {
        themeIcon.className = 'fas fa-sun';
    }
}

// Listen for system theme changes
window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
    const savedTheme = localStorage.getItem('theme');
    if (!savedTheme) {
        updateThemeIcon(e.matches ? 'light' : 'dark');
    }
});

// Initialize theme on page load
initTheme();

// File polling functions
async function waitForAudioFile(videoId, maxWaitSeconds = 60) {
    /**
     * Poll the /audio endpoint until the file is available or timeout.
     * Returns true if file is ready, false if timeout.
     */
    const startTime = Date.now();
    const maxWaitMs = maxWaitSeconds * 1000;
    let attemptCount = 0;

    while (Date.now() - startTime < maxWaitMs) {
        attemptCount++;
        try {
            const audioUrl = `${appConfig.apiBaseUrl}/audio/${videoId}?t=${Date.now()}`;
            const response = await fetch(audioUrl, { method: 'HEAD' }); // Use HEAD to avoid downloading

            if (response.ok) {
                console.log(`Audio file ready after ${attemptCount} attempts (${Date.now() - startTime}ms)`);
                return true;
            }

            // File not ready yet, wait before retry
            const waitTime = Math.min(500 + (attemptCount * 100), 2000); // Progressive backoff, max 2s
            const elapsed = Math.ceil((Date.now() - startTime) / 1000);
            showStreamStatus(`Downloading from YouTube... (${elapsed}s)`);
            await new Promise(resolve => setTimeout(resolve, waitTime));
        } catch (error) {
            console.warn(`Polling attempt ${attemptCount} failed:`, error);
            await new Promise(resolve => setTimeout(resolve, 1000));
        }
    }

    console.error(`Audio file not ready after ${maxWaitSeconds}s`);
    return false;
}

// Stream Resilience Functions
function showStreamStatus(message) {
    streamStatusText.textContent = message;
    streamStatus.classList.remove('hidden');
}

function hideStreamStatus() {
    streamStatus.classList.add('hidden');
}

function retryStream() {
    if (retryCount >= maxRetries) {
        console.error(`Max retries (${maxRetries}) reached. Please refresh the page or restart the stream.`);
        updateStatus(`Stream failed after ${maxRetries} attempts. Please try again.`, 'error');
        hideStreamStatus();
        isRetrying = false;
        return;
    }

    retryCount++;
    const currentDelay = Math.min(retryDelay * Math.pow(1.5, retryCount - 1), maxRetryDelay);

    console.log(`Retry attempt ${retryCount}/${maxRetries} in ${currentDelay}ms...`);
    showStreamStatus(`Loading audio (attempt ${retryCount}/${maxRetries})...`);

    isRetrying = true;

    retryTimeout = setTimeout(() => {
        try {
            // First, just try to play without reloading (preserve buffer)
            player.play().then(() => {
                console.log('Stream resumed successfully (buffer preserved)');
                retryCount = 0; // Reset retry count on success
                hideStreamStatus();
                isRetrying = false;
            }).catch(err => {
                // If play fails after several quick attempts, reload as last resort
                if (retryCount > 5) {
                    console.log('Multiple quick retries failed, reloading stream...');
                    // Save current position
                    if (!isNaN(player.currentTime) && player.currentTime > 0) {
                        lastPlayPosition = player.currentTime;
                    }

                    // Reload the audio file
                    if (currentVideoId) {
                        const audioUrl = `${appConfig.apiBaseUrl}/audio/${currentVideoId}?t=${Date.now()}`;
                        player.src = audioUrl;
                        player.load();
                    }

                    // Try to restore position
                    if (lastPlayPosition > 0) {
                        player.currentTime = lastPlayPosition;
                    }

                    // Attempt to play
                    player.play().then(() => {
                        console.log('Stream reconnected after reload');
                        retryCount = 0;
                        hideStreamStatus();
                        isRetrying = false;
                    }).catch(err2 => {
                        console.error('Failed to play after reload:', err2);
                        retryStream(); // Try again
                    });
                } else {
                    // Quick retry without reload
                    console.error('Play failed, retrying...', err);
                    retryStream();
                }
            });
        } catch (err) {
            console.error('Error during stream retry:', err);
            retryStream(); // Try again
        }
    }, currentDelay);
}

function cancelRetry() {
    if (retryTimeout) {
        clearTimeout(retryTimeout);
        retryTimeout = null;
    }
    if (stalledTimeout) {
        clearTimeout(stalledTimeout);
        stalledTimeout = null;
    }
    retryCount = 0;
    isRetrying = false;
    hideStreamStatus();
}

// Track seeking to avoid false error triggers
player.addEventListener('seeking', function () {
    isSeeking = true;
});

player.addEventListener('seeked', function () {
    isSeeking = false;
});

// Audio Player Event Handlers for Resilience
player.addEventListener('error', function (e) {
    console.error('Audio player error:', e);
    const error = player.error;
    if (error) {
        console.error(`Error code: ${error.code}, message: ${error.message}`);

        // Don't retry on user-initiated actions (seeking, abort)
        // Error code 1 = MEDIA_ERR_ABORTED (user aborted)
        if (error.code === 1 || isSeeking) {
            console.log('User-initiated action, not retrying');
            return;
        }

        // Only retry on actual playback errors (network, decode)
        if (isPlaying && !isRetrying) {
            console.log('Stream error detected, attempting to reconnect...');
            retryStream();
        }
    }
});

player.addEventListener('waiting', function () {
    console.log('Player waiting for data (buffering)...');
    bufferingStartTime = Date.now();
    showStreamStatus('Buffering...');

    // Don't retry immediately - give it time to buffer
    // The browser will try to recover on its own first
});

player.addEventListener('stalled', function () {
    console.warn('Stream stalled, buffering...');
    showStreamStatus('Buffering...');

    // Clear any existing stalled timeout
    if (stalledTimeout) {
        clearTimeout(stalledTimeout);
    }

    // If still stalled after 30 seconds, try to reconnect
    // Increased from 10s to give more time for poor networks
    stalledTimeout = setTimeout(() => {
        if (isPlaying && !isRetrying) {
            console.log('Stream stalled for too long (30s), attempting to reconnect...');
            retryStream();
        }
    }, 30000); // Increased to 30 seconds
});

player.addEventListener('canplay', function () {
    console.log('Can play - enough data loaded');
    if (!isRetrying) {
        hideStreamStatus();
    }

    // Clear stalled timeout if stream is playable
    if (stalledTimeout) {
        clearTimeout(stalledTimeout);
        stalledTimeout = null;
    }
});

// Intercept native play button clicks
player.addEventListener('play', async function (e) {
    // If no valid source is loaded, prevent play and start queue instead
    if (!player.src || player.src === '' || player.src === window.location.href) {
        console.log('Play pressed with no source, starting queue...');
        e.preventDefault();
        player.pause(); // Ensure it's paused
        await playQueue();
    }
});

player.addEventListener('playing', function () {
    // Log buffering duration if we were buffering
    if (bufferingStartTime) {
        const bufferingDuration = Date.now() - bufferingStartTime;
        console.log(`Stream resumed after ${bufferingDuration}ms of buffering`);
        bufferingStartTime = null;
    }

    console.log('Playback started/resumed');
    hideStreamStatus();
    retryCount = 0; // Reset retry count when successfully playing

    // Update MediaSession playback state
    if ('mediaSession' in navigator && navigator.mediaSession.playbackState !== undefined) {
        navigator.mediaSession.playbackState = 'playing';
    }

    // Update position state when playback starts (important for Tesla scrubber)
    updatePositionState();

    // Clear stalled timeout
    if (stalledTimeout) {
        clearTimeout(stalledTimeout);
        stalledTimeout = null;
    }
});

player.addEventListener('pause', function () {
    console.log('Playback paused');
    // Don't show reconnection UI if user paused manually
    if (!isRetrying) {
        hideStreamStatus();
    }

    // Update MediaSession playback state
    if ('mediaSession' in navigator && navigator.mediaSession.playbackState !== undefined) {
        navigator.mediaSession.playbackState = 'paused';
    }
});

player.addEventListener('loadstart', function () {
    console.log('Started loading stream');
});

player.addEventListener('progress', function () {
    // Stream is downloading, this is good
    if (stalledTimeout) {
        clearTimeout(stalledTimeout);
        stalledTimeout = null;
    }
});

player.addEventListener('suspend', function () {
    // Browser has suspended loading (might be due to buffering enough data)
    console.log('Stream loading suspended (browser buffered enough)');
});

// Handle when duration becomes available
player.addEventListener('loadedmetadata', function () {
    remoteLog('log', '[MediaSession] Metadata loaded', { duration: player.duration });

    // Set position state when duration becomes available (critical for Tesla scrubber)
    updatePositionState();
});

player.addEventListener('durationchange', function () {
    remoteLog('log', '[MediaSession] Duration changed', { duration: player.duration });

    // Update position state when duration changes
    updatePositionState();
});

// Prefetch next queue item when current track is nearing its end
let lastPositionUpdate = 0;
player.addEventListener('timeupdate', async function () {
    // Update MediaSession position state (throttled to once per second for performance)
    const now = Date.now();
    if (now - lastPositionUpdate > 1000) {
        updatePositionState();
        lastPositionUpdate = now;
    }

    // Update progress bar on currently playing queue item
    if (isPlaying && player.duration && !isNaN(player.duration) && isFinite(player.duration)) {
        const progress = Math.ceil(player.currentTime / player.duration * 100);
        const progressBar = document.querySelector('.queue-progress-bar');
        if (progressBar) {
            progressBar.style.width = `${progress}%`;
        }
    }

    if (!isPlaying || prefetchTriggered || !player.duration) return;

    const remaining = player.duration - player.currentTime;
    if (remaining > prefetchThresholdSeconds) return;

    // Trigger only once per track
    prefetchTriggered = true;

    // Find the next video in the queue (index 1, since index 0 is current)
    const queue = await fetchQueue();
    if (queue.length < 2) return;

    const nextVideoId = queue[1].youtube_id;
    console.log(`Prefetching next track: ${queue[1].title} (${nextVideoId}) — ${Math.round(remaining)}s remaining`);

    try {
        await fetch(`/queue/prefetch/${nextVideoId}`, { method: 'POST' });
    } catch (e) {
        console.warn('Prefetch request failed:', e);
    }
});

player.addEventListener('abort', function () {
    console.warn('Stream loading aborted');
});

// Update browser window title
function updateWindowTitle(title) {
    if (title) {
        document.title = `${title} - YouTube Radio`;
        currentTrackTitle = title;
    } else {
        document.title = defaultTitle;
        currentTrackTitle = null;
    }
}

// Helper function to safely update position state with validation
function updatePositionState() {
    if (!('mediaSession' in navigator) || !navigator.mediaSession.setPositionState) {
        return;
    }

    // Validate that we have a valid duration
    if (!player.duration || isNaN(player.duration) || !isFinite(player.duration) || player.duration <= 0) {
        return;
    }

    try {
        // Clamp position to be within valid range [0, duration]
        const position = Math.min(Math.max(0, player.currentTime || 0), player.duration);
        const playbackRate = player.playbackRate || 1.0;

        // All parameters must be valid: duration > 0, position >= 0 && position <= duration, playbackRate != 0
        navigator.mediaSession.setPositionState({
            duration: player.duration,
            playbackRate: playbackRate,
            position: position
        });

        remoteLog('log', '[MediaSession] Position state updated', {
            duration: player.duration,
            position: position,
            playbackRate: playbackRate
        });
    } catch (e) {
        remoteLog('warn', '[MediaSession] Failed to set position state', {
            error: e.message,
            duration: player.duration,
            position: player.currentTime,
            playbackRate: player.playbackRate
        });
    }
}

// Set up MediaSession for lock screen and car display controls
function setupMediaSession(trackInfo) {
    if (!('mediaSession' in navigator)) {
        return;
    }

    if (!trackInfo) {
        return;
    }

    // Try to set metadata with artwork first, fallback to without artwork if it fails
    // Some car systems (Tesla) reject metadata with artwork issues
    try {
        // Only include artwork if we have a thumbnail
        // Don't include empty artwork array - some systems reject it
        const metadataOptions = {
            title: trackInfo.title || 'YouTube Audio',
            artist: trackInfo.channel || 'YouTube',
            album: 'YouTube Radio'
        };

        // Only add artwork if we have thumbnail data
        if (trackInfo.thumbnail_url) {
            const videoId = trackInfo.youtube_id || trackInfo.youtube_video_id;
            const artwork = [];

            if (videoId) {
                // Add multiple resolution options for better compatibility
                // Using direct YouTube thumbnail URLs
                artwork.push({
                    src: `https://i.ytimg.com/vi/${videoId}/maxresdefault.jpg`,
                    sizes: '1280x720',
                    type: 'image/jpeg'
                });
                artwork.push({
                    src: `https://i.ytimg.com/vi/${videoId}/sddefault.jpg`,
                    sizes: '640x480',
                    type: 'image/jpeg'
                });
                artwork.push({
                    src: trackInfo.thumbnail_url,
                    sizes: '480x360',
                    type: 'image/jpeg'
                });
                artwork.push({
                    src: `https://i.ytimg.com/vi/${videoId}/mqdefault.jpg`,
                    sizes: '320x180',
                    type: 'image/jpeg'
                });
            } else {
                artwork.push({
                    src: trackInfo.thumbnail_url,
                    sizes: '480x360',
                    type: 'image/jpeg'
                });
            }

            metadataOptions.artwork = artwork;
        }

        navigator.mediaSession.metadata = new MediaMetadata(metadataOptions);

        remoteLog('log', '[MediaSession] Updated metadata', {
            title: metadataOptions.title,
            artist: metadataOptions.artist,
            hasArtwork: !!metadataOptions.artwork,
            artworkCount: metadataOptions.artwork ? metadataOptions.artwork.length : 0
        });
    } catch (e) {
        // Fallback: set metadata without artwork
        // This fixes compatibility with strict car systems like Tesla
        remoteLog('warn', '[MediaSession] Failed to set metadata with artwork, trying without', { error: e.message });
        try {
            navigator.mediaSession.metadata = new MediaMetadata({
                title: trackInfo.title || 'YouTube Audio',
                artist: trackInfo.channel || 'YouTube',
                album: 'YouTube Radio'
            });
            remoteLog('log', '[MediaSession] Set metadata without artwork (fallback)');
        } catch (fallbackError) {
            remoteLog('error', '[MediaSession] Failed to set metadata even without artwork', { error: fallbackError.message });
        }
    }

    // Try to set position state after metadata (Tesla requires this early)
    updatePositionState();

    // Set up action handlers for background playback
    navigator.mediaSession.setActionHandler('play', () => {
        player.play();
    });
    navigator.mediaSession.setActionHandler('pause', () => {
        player.pause();
    });
    navigator.mediaSession.setActionHandler('nexttrack', () => {
        playNext();
    });
    navigator.mediaSession.setActionHandler('previoustrack', () => {
        rewind();
    });
    navigator.mediaSession.setActionHandler('seekbackward', (details) => {
        const skipTime = details.seekOffset || 15;
        player.currentTime = Math.max(0, player.currentTime - skipTime);
        updatePositionState();
    });
    navigator.mediaSession.setActionHandler('seekforward', (details) => {
        const skipTime = details.seekOffset || 15;
        player.currentTime = Math.min(player.currentTime + skipTime, player.duration || player.currentTime + skipTime);
        updatePositionState();
    });

    // Handle seek to specific position (for scrubber/progress bar in car displays)
    navigator.mediaSession.setActionHandler('seekto', (details) => {
        if (details.seekTime !== null && !isNaN(details.seekTime)) {
            // Use fastSeek if available for better performance
            if (details.fastSeek && 'fastSeek' in player) {
                player.fastSeek(details.seekTime);
            } else {
                player.currentTime = details.seekTime;
            }
            remoteLog('log', '[MediaSession] Seeked to position', { seekTime: details.seekTime });

            // Update position state immediately after seeking (critical for Tesla)
            updatePositionState();
        }
    });
}

// Queue Management
async function fetchQueue() {
    try {
        const res = await fetch('/queue');
        const data = await res.json();
        return data.queue || [];
    } catch (e) {
        console.error('Error fetching queue:', e);
        return [];
    }
}

async function addToQueue() {
    const input = document.getElementById('youtube_video_id').value;

    if (!input.trim()) {
        updateStatus('Please enter a YouTube ID or URL', 'error');
        return;
    }

    const youtube_video_id = extractVideoId(input);

    if (!youtube_video_id) {
        updateStatus('Invalid YouTube ID or URL', 'error');
        return;
    }

    const skipTranscriptionCheckbox = document.getElementById('skip_transcription');
    const skip_transcription = skipTranscriptionCheckbox ? skipTranscriptionCheckbox.checked : false;

    try {
        updateStatus('Adding to queue...', 'streaming');

        const res = await fetch('/queue/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ youtube_video_id, skip_transcription })
        });
        const data = await res.json();

        if (res.ok) {
            updateStatus('Added to queue: ' + data.title, 'streaming');
            document.getElementById('youtube_video_id').value = '';
            await renderQueue();
        } else {
            updateStatus('Failed to add to queue', 'error');
        }
    } catch (error) {
        updateStatus('Failed to add to queue', 'error');
        console.error(error);
    }
}

async function clearQueue() {
    if (!confirm('Clear all items from queue?')) {
        return;
    }

    try {
        await fetch('/queue/clear', { method: 'POST' });
        await renderQueue();
        updateStatus('Queue cleared', 'idle');
    } catch (e) {
        console.error('Error clearing queue:', e);
    }
}

async function suggestVideos() {
    const suggestBtn = document.getElementById('suggest-btn');
    if (!suggestBtn) return;

    // Disable button and show loading state
    suggestBtn.disabled = true;
    const originalHTML = suggestBtn.innerHTML;
    suggestBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Generating...</span>';

    try{
        updateStatus('Analyzing recent videos and finding similar content...', 'streaming');

        const res = await fetch('/queue/suggestions', { method: 'POST' });
        const data = await res.json();

        if (res.ok) {
            if (data.status === 'success' || data.status === 'no_suggestions') {
                const addedCount = data.added?.length || 0;
                const failedCount = data.failed?.length || 0;

                if (addedCount > 0) {
                    updateStatus(`Added ${addedCount} video suggestion(s) to queue!`, 'streaming');

                    // Show details of what was added
                    console.log('Suggestions added:', data.added);
                    data.added.forEach(item => {
                        console.log(`  - ${item.title} by ${item.channel || 'Unknown channel'}`);
                    });
                } else {
                    updateStatus('No new video suggestions found', 'idle');
                }

                if (failedCount > 0) {
                    console.warn(`${failedCount} suggestion(s) failed to add:`, data.failed);
                }

                // Refresh queue display
                await renderQueue();
            } else {
                updateStatus(data.message || 'No suggestions available', 'error');
            }
        } else {
            updateStatus(data.detail || 'Failed to generate suggestions', 'error');
            console.error('Suggestion error:', data);
        }
    } catch (error) {
        updateStatus('Failed to generate suggestions', 'error');
        console.error('Error generating suggestions:', error);
    } finally {
        // Re-enable button
        suggestBtn.disabled = false;
        suggestBtn.innerHTML = originalHTML;
    }
}

// Backwards compatibility alias
const suggestAudiobooks = suggestVideos;

async function removeFromQueue(queueId) {
    try {
        await fetch(`/queue/${queueId}`, { method: 'DELETE' });
        await renderQueue();
    } catch (e) {
        console.error('Error removing from queue:', e);
    }
}

async function playQueue() {
    const queue = await fetchQueue();

    if (queue.length === 0) {
        updateStatus('Queue is empty', 'error');
        return;
    }

    // Start streaming the first item (check type)
    const firstItem = queue[0];
    const itemType = firstItem.type || 'youtube';

    if (itemType === 'summary') {
        await startSummaryFromQueue(firstItem.week_year, firstItem.id);
    } else {
        await startStreamFromQueue(firstItem.youtube_id, firstItem.id);
    }
}

async function playNext() {
    try {
        const res = await fetch('/queue/next', { method: 'POST' });
        const data = await res.json();

        if (data.status === 'queue_empty') {
            updateStatus('Queue is empty', 'idle');
            player.pause();
            isPlaying = false;
            cancelRetry(); // Stop any retry attempts
            updateWindowTitle(null);  // Reset title when queue is empty
            await renderQueue();
            return;
        }

        if (data.status === 'next') {
            // Check type and call appropriate function
            if (data.type === 'summary') {
                await startSummaryFromQueue(data.week_year, data.queue_id);
            } else {
                await startStreamFromQueue(data.youtube_id, data.queue_id);
            }
            await renderQueue();
        }
    } catch (error) {
        console.error('Error playing next:', error);
        updateStatus('Failed to play next', 'error');
    }
}

async function startStreamFromQueue(youtube_video_id, queue_id) {
    const skipTranscriptionCheckbox = document.getElementById('skip_transcription');
    const skip_transcription = skipTranscriptionCheckbox ? skipTranscriptionCheckbox.checked : false;

    try {
        const res = await fetch('/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ youtube_video_id, skip_transcription })
        });
        const data = await res.json();
        updateStatus(data.status || data.detail, res.ok ? 'streaming' : 'error');

        if (res.ok) {
            currentVideoId = youtube_video_id;
            currentQueueId = queue_id;
            isPlaying = true;
            prefetchTriggered = false;
            cancelRetry();

            // Metadata & UI updates
            const queue = await fetchQueue();
            const currentItem = queue.find(item => item.id === queue_id);
            if (currentItem) {
                updateWindowTitle(currentItem.title);
                setupMediaSession(currentItem);
            }

            await renderHistory();
            await renderQueue();

            // Wait for audio file to be ready before playing
            showStreamStatus('Starting download from YouTube...');
            const fileReady = await waitForAudioFile(data.youtube_video_id, 60);

            if (!fileReady) {
                updateStatus('Download timed out or failed. Check server logs or try again.', 'error');
                hideStreamStatus();
                isPlaying = false;
                return;
            }

            // File is ready, now load and play
            const audioUrl = `${appConfig.apiBaseUrl}/audio/${data.youtube_video_id}?t=${Date.now()}`;
            console.log('Audio file ready, loading:', audioUrl);

            player.src = audioUrl;
            player.load();

            hideStreamStatus();

            player.play().catch(e => {
                console.error('Audio playback failed:', e);
                if (isPlaying) {
                    retryStream();
                }
            });
        } else {
            updateStatus('Failed to start stream', 'error');
        }
    } catch (error) {
        updateStatus('Failed to start stream', 'error');
        console.error(error);
    }
}

async function startSummaryFromQueue(weekYear, queue_id) {
    try {
        // For summaries, we directly play the audio file from the server
        updateStatus('Loading weekly summary...', 'streaming');

        // Get the audio file URL
        const audioUrl = `${appConfig.apiBaseUrl}/weekly-summaries/${weekYear}/audio?t=${Date.now()}`;

        currentVideoId = null; // No video ID for summaries
        currentQueueId = queue_id;
        isPlaying = true;
        prefetchTriggered = false;
        cancelRetry();

        // Update metadata & UI
        const queue = await fetchQueue();
        const currentItem = queue.find(item => item.id === queue_id);
        if (currentItem) {
            updateWindowTitle(currentItem.title);
            // Setup MediaSession for summary (no thumbnail)
            if ('mediaSession' in navigator) {
                navigator.mediaSession.metadata = new MediaMetadata({
                    title: currentItem.title,
                    artist: 'Weekly Summary',
                    album: 'Audio Stream Server',
                });
            }
        }

        await renderQueue();

        // Load and play the audio
        player.src = audioUrl;
        player.load();

        player.play().catch(e => {
            console.error('Audio playback failed:', e);
            updateStatus('Failed to play summary', 'error');
            isPlaying = false;
        });

        updateStatus('Playing: ' + (currentItem ? currentItem.title : 'Weekly Summary'), 'streaming');
    } catch (error) {
        updateStatus('Failed to play summary', 'error');
        console.error(error);
        isPlaying = false;
    }
}

async function renderQueue() {
    const queueContainer = document.getElementById('queue-list');
    const queueCountEl = document.getElementById('queue-count');
    const queue = await fetchQueue();

    queueCountEl.textContent = `${queue.length} track${queue.length !== 1 ? 's' : ''}`;

    if (queue.length === 0) {
        queueContainer.innerHTML = '<p class="queue-empty">Queue is empty. Add videos above to start!</p>';
        return;
    }

    queueContainer.innerHTML = queue.map((item, index) => {
        const isCurrentlyPlaying = currentQueueId === item.id;
        const positionBadge = `<span class="queue-position">${index + 1}</span>`;
        const itemType = item.type || 'youtube';

        // Debug logging for queue items
        remoteLog('debug', `renderQueue: item #${item.id}`, {
            type: item.type,
            typeType: typeof item.type,
            itemType: itemType,
            week_year: item.week_year,
            youtube_id: item.youtube_id,
            title: item.title ? item.title.substring(0, 50) : 'undefined'
        });

        // Different icons and badges for different types
        let icon, badge, onClick;
        if (itemType === 'summary') {
            icon = '<i class="fas fa-calendar-week"></i>';
            badge = '<span class="queue-badge summary-badge">Summary</span>';
            onClick = isCurrentlyPlaying ? '' : `startSummaryFromQueue('${item.week_year}', ${item.id})`;
        } else {
            icon = '<i class="fab fa-youtube"></i>';
            badge = '';
            onClick = isCurrentlyPlaying ? '' : `startStreamFromQueue('${item.youtube_id}', ${item.id})`;
        }

        return `
            <div class="queue-item ${isCurrentlyPlaying ? 'queue-item-playing' : ''}"
                 data-queue-id="${item.id}"
                 draggable="true"
                 onclick="${onClick}">
                ${isCurrentlyPlaying ? '<div class="queue-progress-bar"></div>' : ''}
                <div class="queue-drag-handle" title="Drag to reorder" onclick="event.stopPropagation();">
                    <i class="fas fa-grip-vertical"></i>
                </div>
                <div class="queue-info">
                    ${positionBadge}
                    ${icon}
                    <span class="queue-title">${escapeHtml(item.title)}</span>
                    ${badge}
                    ${isCurrentlyPlaying ? '<i class="fas fa-volume-up queue-playing-icon"></i>' : ''}
                </div>
                <button onclick="event.stopPropagation(); removeFromQueue(${item.id})"
                        class="btn-remove-queue"
                        title="Remove from queue">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `;
    }).join('');

    // Initialize drag-and-drop after rendering
    initializeQueueDragAndDrop();
}

// Queue drag-and-drop functionality
let draggedElement = null;
let draggedOverElement = null;
let touchClone = null;
let touchStartY = 0;
let touchCurrentY = 0;
let isTouchDragging = false;

function initializeQueueDragAndDrop() {
    const queueItems = document.querySelectorAll('.queue-item');

    queueItems.forEach(item => {
        // Mouse drag events
        item.addEventListener('dragstart', handleDragStart);
        item.addEventListener('dragend', handleDragEnd);
        item.addEventListener('dragover', handleDragOver);
        item.addEventListener('drop', handleDrop);
        item.addEventListener('dragleave', handleDragLeave);

        // Touch events for mobile
        item.addEventListener('touchstart', handleTouchStart, { passive: false });
        item.addEventListener('touchmove', handleTouchMove, { passive: false });
        item.addEventListener('touchend', handleTouchEnd);
        item.addEventListener('touchcancel', handleTouchEnd);
    });
}

function handleDragStart(e) {
    draggedElement = this;
    this.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/html', this.innerHTML);
}

function handleDragEnd(e) {
    this.classList.remove('dragging');
    // Remove all drag-over classes
    document.querySelectorAll('.queue-item').forEach(item => {
        item.classList.remove('drag-over');
    });
    draggedElement = null;
    draggedOverElement = null;
}

function handleDragOver(e) {
    if (e.preventDefault) {
        e.preventDefault();
    }
    e.dataTransfer.dropEffect = 'move';

    if (this === draggedElement) {
        return false;
    }

    this.classList.add('drag-over');
    draggedOverElement = this;
    return false;
}

function handleDragLeave(e) {
    this.classList.remove('drag-over');
}

async function handleDrop(e) {
    if (e.stopPropagation) {
        e.stopPropagation();
    }

    if (draggedElement !== this) {
        // Get all queue items
        const queueItems = Array.from(document.querySelectorAll('.queue-item'));
        const draggedIndex = queueItems.indexOf(draggedElement);
        const targetIndex = queueItems.indexOf(this);

        // Reorder in DOM
        if (draggedIndex < targetIndex) {
            this.parentNode.insertBefore(draggedElement, this.nextSibling);
        } else {
            this.parentNode.insertBefore(draggedElement, this);
        }

        // Get new order of queue IDs
        const newOrder = Array.from(document.querySelectorAll('.queue-item'))
            .map(item => parseInt(item.dataset.queueId));

        // Send to backend
        try {
            const response = await fetch('/queue/reorder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ queue_item_ids: newOrder })
            });

            if (!response.ok) {
                throw new Error('Failed to reorder queue');
            }

            // Refresh queue to update position badges
            await renderQueue();
        } catch (error) {
            console.error('Error reordering queue:', error);
            showNotification('Failed to reorder queue', 'error');
            // Refresh to restore original order
            await renderQueue();
        }
    }

    this.classList.remove('drag-over');
    return false;
}

// Touch event handlers for mobile drag-and-drop
function handleTouchStart(e) {
    // Only handle touch on drag handle
    const target = e.target;
    if (!target.closest('.queue-drag-handle')) {
        return;
    }

    e.preventDefault();

    draggedElement = this;
    isTouchDragging = true;

    const touch = e.touches[0];
    touchStartY = touch.clientY;
    touchCurrentY = touch.clientY;

    // Create a visual clone
    touchClone = this.cloneNode(true);
    touchClone.classList.add('touch-dragging-clone');
    touchClone.style.position = 'fixed';
    touchClone.style.width = this.offsetWidth + 'px';
    touchClone.style.left = this.getBoundingClientRect().left + 'px';
    touchClone.style.top = touch.clientY + 'px';
    touchClone.style.zIndex = '9999';
    touchClone.style.pointerEvents = 'none';
    touchClone.style.opacity = '0.8';
    document.body.appendChild(touchClone);

    // Add dragging class to original
    this.classList.add('dragging');
}

function handleTouchMove(e) {
    if (!isTouchDragging || !draggedElement) {
        return;
    }

    e.preventDefault();

    const touch = e.touches[0];
    touchCurrentY = touch.clientY;

    // Move the clone
    if (touchClone) {
        touchClone.style.top = touch.clientY + 'px';
    }

    // Find the element at touch position
    const elementBelow = document.elementFromPoint(touch.clientX, touch.clientY);
    const queueItemBelow = elementBelow ? elementBelow.closest('.queue-item') : null;

    // Remove drag-over from all items
    document.querySelectorAll('.queue-item').forEach(item => {
        item.classList.remove('drag-over');
    });

    // Add drag-over to target if valid
    if (queueItemBelow && queueItemBelow !== draggedElement) {
        queueItemBelow.classList.add('drag-over');
        draggedOverElement = queueItemBelow;
    }
}

async function handleTouchEnd(e) {
    if (!isTouchDragging || !draggedElement) {
        return;
    }

    e.preventDefault();

    // Remove the clone
    if (touchClone) {
        touchClone.remove();
        touchClone = null;
    }

    // Remove dragging class
    draggedElement.classList.remove('dragging');

    // Remove drag-over from all items
    document.querySelectorAll('.queue-item').forEach(item => {
        item.classList.remove('drag-over');
    });

    // Perform reorder if there's a valid drop target
    if (draggedOverElement && draggedOverElement !== draggedElement) {
        const queueItems = Array.from(document.querySelectorAll('.queue-item'));
        const draggedIndex = queueItems.indexOf(draggedElement);
        const targetIndex = queueItems.indexOf(draggedOverElement);

        // Reorder in DOM
        if (draggedIndex < targetIndex) {
            draggedOverElement.parentNode.insertBefore(draggedElement, draggedOverElement.nextSibling);
        } else {
            draggedOverElement.parentNode.insertBefore(draggedElement, draggedOverElement);
        }

        // Get new order of queue IDs
        const newOrder = Array.from(document.querySelectorAll('.queue-item'))
            .map(item => parseInt(item.dataset.queueId));

        // Send to backend
        try {
            const response = await fetch('/queue/reorder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ queue_item_ids: newOrder })
            });

            if (!response.ok) {
                throw new Error('Failed to reorder queue');
            }

            // Refresh queue to update position badges
            await renderQueue();
        } catch (error) {
            console.error('Error reordering queue:', error);
            showNotification('Failed to reorder queue', 'error');
            // Refresh to restore original order
            await renderQueue();
        }
    }

    // Reset state
    draggedElement = null;
    draggedOverElement = null;
    isTouchDragging = false;
    touchStartY = 0;
    touchCurrentY = 0;
}

// Auto-play next track when current track ends
player.addEventListener('ended', async function () {
    console.log('Track ended, playing next...');
    // Reset progress bar
    const progressBar = document.querySelector('.queue-progress-bar');
    if (progressBar) {
        progressBar.style.width = '0%';
    }
    await playNext();
});

// Weekly Summaries Management
const weeklySummaryEnabled = appConfig.weeklySummaryEnabled;

async function fetchWeeklySummaries() {
    try {
        const res = await fetch('/weekly-summaries?limit=10');
        const data = await res.json();
        return data || [];
    } catch (e) {
        console.error('Error fetching weekly summaries:', e);
        return [];
    }
}

async function renderWeeklySummaries() {
    if (!weeklySummaryEnabled) return;

    const summariesContainer = document.getElementById('summaries-list');
    const summaries = await fetchWeeklySummaries();

    if (summaries.length === 0) {
        summariesContainer.innerHTML = '<p class="summaries-empty">No summaries yet</p>';
        return;
    }

    summariesContainer.innerHTML = summaries.map(item => {
        const hasAudio = item.audio_file_path && item.audio_file_path.trim() !== '';
        const audioIcon = hasAudio ? '<i class="fas fa-volume-up"></i>' : '<i class="fas fa-file-text"></i>';
        const duration = item.duration_seconds ? formatDuration(item.duration_seconds) : '';
        const timeAgo = getTimeAgo(item.created_at);
        const triliumUrl = item.trilium_note_id ? `${appConfig.triliumUrl}/#root/${item.trilium_note_id}` : '';

        // Queue button only if audio exists
        const queueButton = hasAudio ?
            `<button class="summary-action-btn queue-btn" onclick="event.stopPropagation(); addSummaryToQueue('${item.week_year}')" title="Add to Queue">
                <i class="fas fa-plus-circle"></i>
            </button>` : '';

        // Trilium button
        const triliumButton = triliumUrl ?
            `<button class="summary-action-btn trilium-btn" onclick="event.stopPropagation(); window.open('${triliumUrl}', '_blank')" title="View in Trilium">
                <i class="fas fa-external-link-alt"></i>
            </button>` : '';

        return `
            <div class="summary-item ${hasAudio ? '' : 'no-audio'}">
                <div class="summary-info" onclick="${hasAudio ? `playSummary('${item.week_year}')` : ''}">
                    ${audioIcon}
                    <span class="summary-title">${escapeHtml(item.title)}</span>
                </div>
                <div class="summary-meta">
                    <div class="summary-meta-left">
                        <span class="summary-badge">${item.week_year}</span>
                        ${duration ? `<span class="summary-duration">${duration}</span>` : ''}
                        <span class="summary-time">${timeAgo}</span>
                    </div>
                    <div class="summary-meta-right">
                        ${queueButton}
                        ${triliumButton}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function formatDuration(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

async function addSummaryToQueue(weekYear) {
    try {
        updateStatus('Adding summary to queue...', 'streaming');

        const res = await fetch(`/queue/add-summary/${weekYear}`, {
            method: 'POST'
        });
        const data = await res.json();

        if (res.ok) {
            updateStatus('Added summary to queue', 'streaming');
            await renderQueue();
        } else {
            updateStatus('Failed to add summary to queue: ' + data.detail, 'error');
        }
    } catch (error) {
        updateStatus('Failed to add summary to queue', 'error');
        console.error(error);
    }
}

async function playSummary(weekYear) {
    try {
        // Add to queue first
        await addSummaryToQueue(weekYear);

        // Then play next (which will start the summary if queue was empty)
        if (!isPlaying) {
            await playNext();
        }
    } catch (error) {
        console.error('Error playing summary:', error);
        updateStatus('Failed to play summary', 'error');
    }
}

// History Management
async function fetchHistory() {
    try {
        const res = await fetch('/history');
        const data = await res.json();
        return data.history || [];
    } catch (e) {
        console.error('Error fetching history:', e);
        return [];
    }
}

async function clearHistory() {
    if (confirm('Are you sure you want to clear all history?')) {
        try {
            await fetch('/history/clear', { method: 'POST' });
            await renderHistory();
        } catch (e) {
            console.error('Error clearing history:', e);
        }
    }
}

async function renderHistory() {
    const historyContainer = document.getElementById('history-list');
    const history = await fetchHistory();

    if (history.length === 0) {
        historyContainer.innerHTML = '<p class="history-empty">No history yet</p>';
        return;
    }

    historyContainer.innerHTML = history.map(item => {
        const timeAgo = getTimeAgo(item.last_played_at);
        const playCountBadge = item.play_count > 1 ? `<span class="play-count-badge">${item.play_count}×</span>` : '';

        // Show summary button if transcription is enabled
        const summaryButton = transcriptionEnabled ?
            `<button class="history-action-btn summary-btn" onclick="event.stopPropagation(); viewSummary('${item.youtube_id}')" title="View Summary">
                <i class="fas fa-file-alt"></i>
            </button>` : '';

        return `
            <div class="history-item">
                <div class="history-info" onclick="loadFromHistory('${item.youtube_id}')">
                    <i class="fab fa-youtube"></i>
                    <span class="history-title">${escapeHtml(item.title)}</span>
                </div>
                <div class="history-meta">
                    <div class="history-meta-left">
                        ${playCountBadge}
                        <span class="history-time">${timeAgo}</span>
                    </div>
                    <div class="history-meta-right">
                        ${summaryButton}
                        <button class="history-action-btn queue-btn" onclick="event.stopPropagation(); addToQueueFromHistory('${item.youtube_id}')" title="Add to Queue">
                            <i class="fas fa-plus-circle"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function getTimeAgo(isoTimestamp) {
    const timestamp = new Date(isoTimestamp).getTime();
    const seconds = Math.floor((Date.now() - timestamp) / 1000);

    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
    return new Date(timestamp).toLocaleDateString();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function loadFromHistory(videoId) {
    try {
        updateStatus('Adding to queue...', 'streaming');

        const res = await fetch('/queue/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ youtube_video_id: videoId, skip_transcription: false })
        });
        const data = await res.json();

        if (res.ok) {
            updateStatus('Added to queue: ' + data.title, 'streaming');
            await renderQueue();
        } else {
            updateStatus('Failed to add to queue', 'error');
        }
    } catch (error) {
        updateStatus('Failed to add to queue', 'error');
        console.error(error);
    }
}

// Alias for consistency with UI
const addToQueueFromHistory = loadFromHistory;

function extractVideoId(input) {
    // If it's already just an ID (11 characters, alphanumeric), return it
    if (/^[a-zA-Z0-9_-]{11}$/.test(input.trim())) {
        return input.trim();
    }

    // Try to extract from various YouTube URL formats
    const patterns = [
        /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/,
        /youtube\.com\/watch\?.*v=([a-zA-Z0-9_-]{11})/
    ];

    for (const pattern of patterns) {
        const match = input.match(pattern);
        if (match) {
            return match[1];
        }
    }

    // If no pattern matched, return the original input trimmed
    return input.trim();
}

async function startStream() {
    const input = document.getElementById('youtube_video_id').value;

    if (!input.trim()) {
        updateStatus('Please enter a YouTube ID or URL', 'error');
        return;
    }

    // Extract video ID from URL or use as-is if it's already an ID
    const youtube_video_id = extractVideoId(input);

    if (!youtube_video_id) {
        updateStatus('Invalid YouTube ID or URL', 'error');
        return;
    }

    // Get skip_transcription checkbox value (if it exists)
    const skipTranscriptionCheckbox = document.getElementById('skip_transcription');
    const skip_transcription = skipTranscriptionCheckbox ? skipTranscriptionCheckbox.checked : false;

    try {
        const res = await fetch('/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ youtube_video_id, skip_transcription })
        });
        const data = await res.json();
        updateStatus(data.status || data.detail, res.ok ? 'streaming' : 'error');

        if (res.ok) {
            currentVideoId = youtube_video_id;
            isPlaying = true;
            prefetchTriggered = false;
            cancelRetry(); // Cancel any ongoing retries

            // Re-render history to show the new entry
            await renderHistory();

            // Update browser window title with track name from history
            const history = await fetchHistory();
            const currentTrack = history.find(item => item.youtube_id === youtube_video_id);
            if (currentTrack) {
                updateWindowTitle(currentTrack.title);
                setupMediaSession(currentTrack);
            }

            // Update transcription status UI if enabled
            if (transcriptionEnabled) {
                if (skip_transcription) {
                    const container = document.getElementById('transcription-status');
                    if (container) {
                        container.innerHTML = '<p class="transcription-idle"><i class="fas fa-music"></i> Transcription skipped for this stream</p>';
                    }
                }
            }

            // Wait for audio file to be ready before playing
            showStreamStatus('Starting download from YouTube...');
            const fileReady = await waitForAudioFile(youtube_video_id, 60);

            if (!fileReady) {
                updateStatus('Download timed out or failed. Check server logs or try again.', 'error');
                hideStreamStatus();
                isPlaying = false;
                return;
            }

            // File is ready, now load and play
            const audioUrl = `${appConfig.apiBaseUrl}/audio/${youtube_video_id}?t=${Date.now()}`;
            console.log('🎵 Audio file ready, loading:', audioUrl);

            player.src = audioUrl;
            player.load();

            hideStreamStatus();

            player.play().catch(e => {
                console.error('❌ Audio playback failed:', e);
                // Auto-retry if initial play fails
                if (isPlaying) {
                    retryStream();
                }
            });
        }
    } catch (error) {
        updateStatus('Failed to start stream', 'error');
        console.error(error);
    }
}

async function stopStream() {
    // Pause the player first
    player.pause();
    isPlaying = false;
    currentQueueId = null;

    // Cancel any retry attempts
    cancelRetry();

    // Reset browser window title
    updateWindowTitle(null);

    // Reset progress bar
    const progressBar = document.querySelector('.queue-progress-bar');
    if (progressBar) {
        progressBar.style.width = '0%';
    }

    // Then call server to stop the stream
    try {
        const res = await fetch('/stop', { method: 'POST' });
        const data = await res.json();
        updateStatus(data.status || data.detail, 'idle');
    } catch (error) {
        updateStatus('Failed to stop stream', 'error');
        console.error(error);
    }

    // Update queue display
    await renderQueue();
}

function pauseAudio() {
    player.pause();
}

async function playAudio() {
    // If nothing is loaded/playing, start the queue
    if (!player.src || player.src === '' || (!isPlaying && player.paused && player.currentTime === 0)) {
        console.log('No audio loaded, starting queue...');
        await playQueue();
    } else {
        player.play();
    }
}

function rewind() {
    player.currentTime = Math.max(0, player.currentTime - 15);
}

function fastforward() {
    player.currentTime = Math.max(0, player.currentTime + 15);
}

function setSpeed(speed) {
    player.playbackRate = speed;

    // Update active button styling
    document.querySelectorAll('.btn-speed').forEach(btn => {
        btn.classList.remove('active');
    });

    const speedId = `speed-${speed}x`;
    const activeBtn = document.getElementById(speedId);
    if (activeBtn) {
        activeBtn.classList.add('active');
    }

    console.log(`Playback speed set to ${speed}x`);
}

async function updateStatus(message, state) {
    if (message) {
        statusText.innerText = 'Status: ' + message;
    }

    // Update status dot
    statusDot.className = 'status-dot';
    if (state === 'streaming') {
        statusDot.classList.add('streaming');
    } else if (state === 'error') {
        statusDot.classList.add('error');
    }
}

async function fetchStatus() {
    try {
        const res = await fetch('/status');
        const data = await res.json();
        updateStatus(data.status, data.status);
    } catch (error) {
        console.error('Failed to fetch status:', error);
    }
}

// Transcription functions
async function fetchTranscriptionStatus() {
    if (!transcriptionEnabled || !currentVideoId) {
        return;
    }

    try {
        const res = await fetch(`/transcription/status/${currentVideoId}`);
        const data = await res.json();
        updateTranscriptionStatus(data);
    } catch (error) {
        console.error('Failed to fetch transcription status:', error);
    }
}

function updateTranscriptionStatus(data) {
    const container = document.getElementById('transcription-status');
    if (!container) return;

    const statusIcons = {
        'pending': '<i class="fas fa-clock"></i>',
        'checking_dedup': '<i class="fas fa-search"></i>',
        'transcribing': '<i class="fas fa-microphone"></i>',
        'summarizing': '<i class="fas fa-brain"></i>',
        'posting': '<i class="fas fa-upload"></i>',
        'completed': '<i class="fas fa-check-circle"></i>',
        'failed': '<i class="fas fa-exclamation-circle"></i>',
        'skipped': '<i class="fas fa-info-circle"></i>',
        'not_found': '<i class="fas fa-question-circle"></i>'
    };

    const statusLabels = {
        'pending': 'Waiting for audio download to complete...',
        'checking_dedup': 'Checking for existing note',
        'transcribing': 'Transcribing audio',
        'summarizing': 'Generating summary',
        'posting': 'Posting to Trilium',
        'completed': 'Completed',
        'failed': 'Failed',
        'skipped': 'Already exists in Trilium',
        'not_found': 'Not started'
    };

    const status = data.status || 'not_found';
    const icon = statusIcons[status] || '<i class="fas fa-circle"></i>';
    const label = statusLabels[status] || status;

    let html = `
        <div class="transcription-item">
            <div class="transcription-info">
                ${icon}
                <span class="transcription-label">${label}</span>
            </div>
    `;

    // Add action buttons based on status
    if (status === 'completed' || status === 'skipped') {
        html += `
            <div class="transcription-actions">
                <button onclick="viewSummary('${data.video_id}')" class="btn-transcription" title="View Summary">
                    <i class="fas fa-eye"></i>
                    <span>View Summary</span>
                </button>
        `;

        if (data.trilium_note_url) {
            html += `
                <a href="${data.trilium_note_url}" target="_blank" class="btn-transcription" title="Open in Trilium">
                    <i class="fas fa-external-link-alt"></i>
                    <span>Open in Trilium</span>
                </a>
            `;
        }

        html += `</div>`;
    } else if (status === 'failed') {
        html += `
            <div class="transcription-error">
                <i class="fas fa-exclamation-triangle"></i>
                <span>${data.error || 'Unknown error'}</span>
            </div>
        `;
    } else if (status === 'pending' || status === 'transcribing' || status === 'summarizing' || status === 'posting' || status === 'checking_dedup') {
        html += `
            <div class="transcription-progress">
                <div class="spinner"></div>
            </div>
        `;
    }

    html += `</div>`;
    container.innerHTML = html;
}

async function viewSummary(videoId) {
    const modal = document.getElementById('summary-modal');
    const content = document.getElementById('summary-content');

    modal.style.display = 'block';
    content.innerHTML = '<p>Loading summary...</p>';

    try {
        const res = await fetch(`/transcription/summary/${videoId}`);

        if (!res.ok) {
            if (res.status === 404) {
                content.innerHTML = `
                    <p>No summary found for this video.</p>
                    <p style="color: var(--text-muted); font-size: 0.9rem; margin-top: 10px;">
                        This video hasn't been transcribed yet. Play it with transcription enabled to generate a summary.
                    </p>
                `;
                return;
            }
            throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();

        if (data.summary) {
            // Format the summary with proper line breaks
            const formattedSummary = data.summary.replace(/\n/g, '<br>');
            content.innerHTML = `
                <div class="summary-text">${formattedSummary}</div>
                ${data.trilium_note_url ? `
                    <div class="summary-footer">
                        <a href="${data.trilium_note_url}" target="_blank" class="btn-transcription">
                            <i class="fas fa-external-link-alt"></i>
                            Open full note in Trilium
                        </a>
                    </div>
                ` : ''}
            `;
        } else {
            content.innerHTML = '<p>Summary not available yet</p>';
        }
    } catch (error) {
        console.error('Failed to fetch summary:', error);
        content.innerHTML = '<p>Failed to load summary. Please check the console for details.</p>';
    }
}

function closeSummaryModal() {
    const modal = document.getElementById('summary-modal');
    modal.style.display = 'none';
}

// Close modal when clicking outside
window.onclick = function (event) {
    const modal = document.getElementById('summary-modal');
    if (event.target === modal) {
        closeSummaryModal();
    }
}

// Poll status every 3 seconds
setInterval(fetchStatus, 3000);

// Poll transcription status every 5 seconds
if (transcriptionEnabled) {
    setInterval(fetchTranscriptionStatus, 5000);
}

// Initial status fetch, queue, and history render
fetchStatus();
renderQueue();
renderHistory();
if (weeklySummaryEnabled) {
    renderWeeklySummaries();
}
if (transcriptionEnabled) {
    fetchTranscriptionStatus();
}
