# JavaScript Testing Guide

This document describes how to test the `update-checker.js` functionality.

## Manual Testing

### Setup

1. Start the development server:
```bash
uv run python main.py
```

2. Open browser console: `http://localhost:8000`

### Test 1: Initial Load

**Expected:**
```javascript
Current version: <8-char-hash>
```

**Verify:**
- No errors in console
- Version logged successfully

### Test 2: Version Check on Focus

**Steps:**
1. Keep browser tab open
2. Switch to another tab/window (blur)
3. Wait 30+ seconds
4. Deploy a new version (or modify version.json)
5. Switch back to the app tab (focus)

**Expected:**
```javascript
New version detected!
  Current: <old-hash>
  New: <new-hash>
```
- Update modal appears
- Modal shows version info

### Test 3: Playback State Persistence

**Steps:**
1. Start playing an audiobook
2. Let it play for ~30 seconds
3. Open console and type:
```javascript
updateChecker.savePlaybackState()
localStorage.getItem('playbackState')
```

**Expected:**
```json
{
  "currentVideoId": "abc123",
  "currentTime": 30.5,
  "isPlaying": true,
  "queue": [...],
  "timestamp": 1707523200000
}
```

### Test 4: Playback Restoration

**Steps:**
1. Start playing an audiobook at position 1:30
2. Add a few items to queue
3. Click "Update Now" in modal
4. Page refreshes

**Expected:**
- Same video starts playing
- Playback position at 1:30
- Queue is restored
- Audio continues playing (or shows notification if autoplay blocked)

### Test 5: Update Dismissal

**Steps:**
1. Trigger update modal
2. Click "Later" button

**Expected:**
- Modal closes
- No refresh happens
- Can continue using app

### Test 6: Old State Cleanup

**Steps:**
1. Manually set old timestamp in localStorage:
```javascript
const state = JSON.parse(localStorage.getItem('playbackState'));
state.timestamp = Date.now() - (10 * 60 * 1000); // 10 minutes ago
localStorage.setItem('playbackState', JSON.stringify(state));
```
2. Refresh page

**Expected:**
```javascript
Playback state too old, ignoring
```
- State is removed
- No playback restoration

### Test 7: No Current Playback

**Steps:**
1. Don't play anything
2. Trigger update modal

**Expected:**
- Modal doesn't mention "playback will be saved"
- Update works normally

### Test 8: Modal Outside Click

**Steps:**
1. Trigger update modal
2. Click outside the modal (on overlay)

**Expected:**
- Modal closes
- Same as clicking "Later"

### Test 9: Periodic Checking

**Steps:**
1. Keep browser tab focused
2. Wait 60+ seconds
3. Deploy new version
4. Wait for next check

**Expected:**
- Automatic version check happens
- Modal appears if new version detected

### Test 10: Visibility State

**Steps:**
1. Minimize browser window
2. Wait 60+ seconds
3. Deploy new version
4. Restore window

**Expected:**
- No checks while minimized
- Check happens on restore

## Console Commands for Testing

```javascript
// Get current version
await updateChecker.fetchVersion()

// Manually trigger update check
await updateChecker.checkForUpdates()

// Show update modal (for testing UI)
updateChecker.showUpdateModal({
  hash: "test1234567890abcdef",
  branch: "main",
  timestamp: new Date().toISOString()
})

// Save current playback state
updateChecker.savePlaybackState()

// Check if audio is playing
updateChecker.isPlaying()

// View saved state
JSON.parse(localStorage.getItem('playbackState'))

// Clear saved state
localStorage.removeItem('playbackState')

// Manually refresh page with state save
updateChecker.refreshPage()

// Dismiss modal
updateChecker.dismissUpdate()
```

## Automated Testing (Future Enhancement)

To add automated JavaScript tests, consider:

1. **Jest** - JavaScript testing framework
2. **Puppeteer** - Browser automation
3. **Playwright** - Modern browser testing

### Example Jest Test Structure:

```javascript
// tests/javascript/update-checker.test.js
describe('UpdateChecker', () => {
  let checker;

  beforeEach(() => {
    checker = new UpdateChecker();
  });

  test('should fetch version', async () => {
    const version = await checker.fetchVersion();
    expect(version).toHaveProperty('hash');
    expect(version).toHaveProperty('branch');
    expect(version).toHaveProperty('timestamp');
  });

  test('should save playback state', () => {
    // Mock audio element
    document.body.innerHTML = '<audio id="audioPlayer"></audio>';
    window.currentVideoId = 'test123';

    checker.savePlaybackState();

    const saved = localStorage.getItem('playbackState');
    expect(saved).toBeDefined();
    const state = JSON.parse(saved);
    expect(state.currentVideoId).toBe('test123');
  });

  test('should show modal on version change', async () => {
    checker.currentVersion = { hash: 'old123', branch: 'main' };
    const newVersion = { hash: 'new456', branch: 'main' };

    await checker.showUpdateModal(newVersion);

    const modal = document.getElementById('update-modal');
    expect(modal).toBeDefined();
    expect(modal.style.display).toBe('block');
  });
});
```

## Coverage Requirements

Target coverage for update-checker.js:

- [ ] Version fetching: 100%
- [ ] Update detection: 100%
- [ ] Playback state save: 100%
- [ ] Playback state restore: 100%
- [ ] Modal show/hide: 100%
- [ ] Event handlers: 90%

## Browser Compatibility

Test in:
- ✅ Chrome/Edge (Chromium)
- ✅ Firefox
- ✅ Safari (iOS)
- ✅ Mobile browsers

## Known Limitations

1. **Autoplay Policy**: Some browsers block autoplay after refresh
   - Handled with notification to user
2. **LocalStorage Limits**: ~5MB limit
   - Playback state is small (~1KB)
3. **Offline Behavior**: No version checks when offline
   - Gracefully degrades

## Debugging Tips

### Enable Verbose Logging:

```javascript
// In update-checker.js, add at top:
const DEBUG = true;

// Then throughout code:
if (DEBUG) console.log('...details...');
```

### Force Version Mismatch:

```javascript
// In console:
updateChecker.currentVersion = { hash: 'forcemismatch' };
await updateChecker.checkForUpdates();
```

### Simulate Old State:

```javascript
const oldState = {
  currentVideoId: "test123",
  currentTime: 100,
  isPlaying: true,
  queue: [],
  timestamp: Date.now() - (10 * 60 * 1000) // 10 min ago
};
localStorage.setItem('playbackState', JSON.stringify(oldState));
```

## Test Checklist

Before releasing:
- [ ] All manual tests pass
- [ ] No console errors
- [ ] Modal displays correctly
- [ ] Playback state persists
- [ ] Old state cleanup works
- [ ] Works on mobile
- [ ] Works in production mode
- [ ] No memory leaks (check with DevTools)
