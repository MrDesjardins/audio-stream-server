// Auto-update detection and playback state persistence

class UpdateChecker {
    constructor() {
        this.currentVersion = null;
        this.checkInterval = 60000; // Check every 60 seconds when focused
        this.intervalId = null;
        this.lastCheckTime = 0;
        this.initialized = false;
    }

    async init() {
        if (this.initialized) return;
        this.initialized = true;

        // Get current version on load
        this.currentVersion = await this.fetchVersion();
        console.log('Current version:', this.currentVersion?.hash?.substring(0, 8));

        // Check for updates when window gains focus
        window.addEventListener('focus', () => this.onWindowFocus());

        // Also check periodically when focused
        this.startPeriodicCheck();

        // Restore playback state if exists
        this.restorePlaybackState();
    }

    async fetchVersion() {
        try {
            const response = await fetch('/static/version.json?' + Date.now());
            if (!response.ok) return null;
            return await response.json();
        } catch (error) {
            console.error('Failed to fetch version:', error);
            return null;
        }
    }

    async onWindowFocus() {
        // Don't check too frequently (max once per 30 seconds)
        const now = Date.now();
        if (now - this.lastCheckTime < 30000) return;
        this.lastCheckTime = now;

        await this.checkForUpdates();
    }

    async checkForUpdates() {
        const newVersion = await this.fetchVersion();
        if (!newVersion || !this.currentVersion) return;

        // Compare git hashes
        if (newVersion.hash !== this.currentVersion.hash) {
            console.log('New version detected!');
            console.log('  Current:', this.currentVersion.hash.substring(0, 8));
            console.log('  New:', newVersion.hash.substring(0, 8));
            this.showUpdateModal(newVersion);
        }
    }

    showUpdateModal(newVersion) {
        // Check if modal already exists
        if (document.getElementById('update-modal')) return;

        const modal = document.createElement('div');
        modal.id = 'update-modal';
        modal.className = 'modal';
        modal.style.display = 'block';

        const shortHash = newVersion.hash.substring(0, 8);
        const timestamp = new Date(newVersion.timestamp).toLocaleString();

        modal.innerHTML = `
            <div class="modal-content" style="max-width: 500px;">
                <h2 style="margin-top: 0;">
                    <i class="fas fa-sync-alt"></i>
                    Update Available
                </h2>
                <p style="margin: 20px 0;">
                    A new version of the application is available.
                </p>
                <div style="background: rgba(255,255,255,0.05); padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <div style="font-size: 0.9em; opacity: 0.8;">
                        <strong>Version:</strong> ${shortHash}<br>
                        <strong>Released:</strong> ${timestamp}
                    </div>
                </div>
                <p style="margin: 20px 0; font-size: 0.9em; opacity: 0.8;">
                    ${this.isPlaying() ?
                        '<i class="fas fa-info-circle"></i> Your current playback will be saved and restored after the update.' :
                        ''
                    }
                </p>
                <div style="display: flex; gap: 10px; margin-top: 25px;">
                    <button onclick="updateChecker.refreshPage()" class="btn-primary" style="flex: 1;">
                        <i class="fas fa-sync-alt"></i>
                        Update Now
                    </button>
                    <button onclick="updateChecker.dismissUpdate()" class="btn-secondary" style="flex: 1;">
                        <i class="fas fa-times"></i>
                        Later
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // Close on outside click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                this.dismissUpdate();
            }
        });
    }

    isPlaying() {
        const audio = document.getElementById('audioPlayer');
        return audio && !audio.paused;
    }

    savePlaybackState() {
        const audio = document.getElementById('audioPlayer');
        if (!audio) return;

        const state = {
            currentVideoId: window.currentVideoId || null,
            currentTime: audio.currentTime,
            isPlaying: !audio.paused,
            queue: [...queue], // Save current queue
            timestamp: Date.now()
        };

        localStorage.setItem('playbackState', JSON.stringify(state));
        console.log('Saved playback state:', state);
    }

    async restorePlaybackState() {
        const stateStr = localStorage.getItem('playbackState');
        if (!stateStr) return;

        try {
            const state = JSON.parse(stateStr);

            // Only restore if saved within last 5 minutes
            if (Date.now() - state.timestamp > 5 * 60 * 1000) {
                console.log('Playback state too old, ignoring');
                localStorage.removeItem('playbackState');
                return;
            }

            console.log('Restoring playback state:', state);

            // Restore queue first
            if (state.queue && state.queue.length > 0) {
                queue = state.queue;
                renderQueue();
            }

            // Restore playback
            if (state.currentVideoId) {
                console.log(`Restoring playback: ${state.currentVideoId} at ${state.currentTime}s`);

                // Start streaming the video
                await startStream(state.currentVideoId);

                // Wait for audio to be ready
                const audio = document.getElementById('audioPlayer');
                if (audio) {
                    // Wait for metadata to load before seeking
                    const waitForMetadata = new Promise((resolve) => {
                        if (audio.readyState >= 1) {
                            resolve();
                        } else {
                            audio.addEventListener('loadedmetadata', resolve, { once: true });
                        }
                    });

                    await waitForMetadata;

                    // Seek to saved position
                    audio.currentTime = state.currentTime;

                    // Resume playback if it was playing
                    if (state.isPlaying) {
                        audio.play().catch(err => {
                            console.warn('Could not auto-play after restore:', err);
                            // Show a notification to manually resume
                            showNotification('Playback restored. Click play to resume.');
                        });
                    }
                }
            }

            // Clear the saved state
            localStorage.removeItem('playbackState');

        } catch (error) {
            console.error('Failed to restore playback state:', error);
            localStorage.removeItem('playbackState');
        }
    }

    refreshPage() {
        // Save state before refreshing
        this.savePlaybackState();

        // Hard refresh to bypass cache
        window.location.reload(true);
    }

    dismissUpdate() {
        const modal = document.getElementById('update-modal');
        if (modal) {
            modal.remove();
        }
    }

    startPeriodicCheck() {
        // Clear existing interval
        if (this.intervalId) {
            clearInterval(this.intervalId);
        }

        // Only check when document is visible
        this.intervalId = setInterval(() => {
            if (document.visibilityState === 'visible') {
                this.checkForUpdates();
            }
        }, this.checkInterval);
    }

    destroy() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
        }
    }
}

// Helper function to show notifications
function showNotification(message) {
    // Check if notification area exists, if not create it
    let notifArea = document.getElementById('notification-area');
    if (!notifArea) {
        notifArea = document.createElement('div');
        notifArea.id = 'notification-area';
        notifArea.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10000;
        `;
        document.body.appendChild(notifArea);
    }

    const notif = document.createElement('div');
    notif.style.cssText = `
        background: rgba(74, 144, 226, 0.95);
        color: white;
        padding: 15px 20px;
        border-radius: 8px;
        margin-bottom: 10px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        animation: slideIn 0.3s ease-out;
    `;
    notif.innerHTML = `<i class="fas fa-info-circle"></i> ${message}`;
    notifArea.appendChild(notif);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        notif.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => notif.remove(), 300);
    }, 5000);
}

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(400px);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }

    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(400px);
            opacity: 0;
        }
    }

    #update-modal .modal-content {
        animation: modalFadeIn 0.3s ease-out;
    }

    @keyframes modalFadeIn {
        from {
            transform: translateY(-50px);
            opacity: 0;
        }
        to {
            transform: translateY(0);
            opacity: 1;
        }
    }

    #update-modal .btn-primary {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 12px 24px;
        border-radius: 8px;
        cursor: pointer;
        font-size: 1em;
        transition: all 0.3s ease;
    }

    #update-modal .btn-primary:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
    }

    #update-modal .btn-secondary {
        background: rgba(255, 255, 255, 0.1);
        color: white;
        border: 1px solid rgba(255, 255, 255, 0.2);
        padding: 12px 24px;
        border-radius: 8px;
        cursor: pointer;
        font-size: 1em;
        transition: all 0.3s ease;
    }

    #update-modal .btn-secondary:hover {
        background: rgba(255, 255, 255, 0.15);
    }
`;
document.head.appendChild(style);

// Initialize update checker when DOM is ready
const updateChecker = new UpdateChecker();
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => updateChecker.init());
} else {
    updateChecker.init();
}
