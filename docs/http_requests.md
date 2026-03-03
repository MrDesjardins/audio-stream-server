# HTTP Request Flows

Mermaid sequence diagrams for every major user action and background flow in the app.

**Participants used throughout:**
- **Browser** – the HTML page / audio element
- **app.js** – frontend JavaScript
- **FastAPI** – the Python backend
- **DB** – SQLite database
- **YT** – YouTube / yt-dlp / ffmpeg pipeline

---

## 1. Page Load

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI
    participant DB

    Browser->>FastAPI: GET /
    FastAPI->>Browser: HTML + window.appConfig<br/>(host, ports, feature flags)

    par Initial data fetch
        app.js->>FastAPI: GET /status
        FastAPI-->>app.js: {status, current_video_id, queue_hash}
    and
        app.js->>FastAPI: GET /queue
        FastAPI->>DB: SELECT queue items
        DB-->>FastAPI: queue rows
        FastAPI-->>app.js: {queue: [...]}
    and
        app.js->>FastAPI: GET /history
        FastAPI->>DB: SELECT last 10 plays
        DB-->>FastAPI: history rows
        FastAPI-->>app.js: [{youtube_id, title, play_count, ...}]
    end

    opt weekly_summary_enabled
        app.js->>FastAPI: GET /weekly-summaries?limit=10
        FastAPI->>DB: SELECT weekly_summaries
        DB-->>FastAPI: summary rows
        FastAPI-->>app.js: [{week_year, title, ...}]
    end

    Note over app.js: renderQueue() called

    opt queue has youtube items
        app.js->>FastAPI: GET /playback-positions?ids=vid1,vid2,...
        FastAPI->>DB: SELECT positions by ids
        DB-->>FastAPI: position rows
        FastAPI-->>app.js: {vid1: {position_seconds, duration_seconds}, ...}
        Note over app.js: Show resume badges on queue items
    end

    Note over app.js: Start background polling loops
    loop Every 3s
        app.js->>FastAPI: GET /status
        FastAPI-->>app.js: {status, queue_hash, ...}
    end
    opt transcription_enabled
        loop Every 5s
            app.js->>FastAPI: GET /transcription/status/{current_video_id}
            FastAPI-->>app.js: {status, summary?, trilium_note_url?}
        end
    end
```

---

## 2. Add Video to Queue

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI
    participant DB
    participant YT

    Browser->>app.js: User clicks "Add to Queue"
    app.js->>FastAPI: POST /queue/add<br/>{youtube_video_id, skip_transcription}
    FastAPI->>YT: yt-dlp --get-title (fetch video info)
    YT-->>FastAPI: title, channel, thumbnail_url
    FastAPI->>DB: INSERT INTO queue
    DB-->>FastAPI: new queue_id
    FastAPI-->>app.js: {status, queue_id, youtube_id, title}

    par Refresh UI
        app.js->>FastAPI: GET /queue
        FastAPI-->>app.js: updated queue
    and
        app.js->>FastAPI: GET /history
        FastAPI-->>app.js: updated history
    end
```

---

## 3. Play Queue (Start Playback)

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI
    participant DB
    participant YT

    Browser->>app.js: User clicks "Play Queue"
    app.js->>FastAPI: GET /queue
    FastAPI-->>app.js: {queue: [first_item, ...]}

    alt first item type = "youtube"
        app.js->>FastAPI: POST /stream<br/>{youtube_video_id, queue_id, skip_transcription}
        FastAPI->>YT: yt-dlp | ffmpeg pipeline starts
        FastAPI-->>app.js: {status, video_id, title}

        loop Poll every 500ms (max 60s)
            app.js->>FastAPI: HEAD /audio/{video_id}
            alt audio ready
                FastAPI-->>app.js: 200 OK (X-Audio-Duration header)
                Note over app.js: Stop polling, proceed
            else still downloading
                FastAPI-->>app.js: 404
            end
        end

        app.js->>FastAPI: GET /playback-position/{video_id}
        FastAPI->>DB: SELECT position
        DB-->>FastAPI: {position_seconds}
        FastAPI-->>app.js: {position_seconds}

        Note over Browser: If position_seconds > 30s,<br/>seek on canplay event

        Browser->>FastAPI: GET /audio/{video_id}
        Note over FastAPI: Streams MP3 (Accept-Ranges supported)
        FastAPI-->>Browser: audio/mpeg stream

        par UI updates
            app.js->>FastAPI: GET /history
            FastAPI-->>app.js: updated history
        and
            app.js->>FastAPI: GET /queue
            FastAPI-->>app.js: updated queue (now-playing indicator)
        end

        Note over app.js: Update MediaSession metadata<br/>(title, channel, thumbnail)

    else first item type = "summary"
        Note over app.js: Load audio directly (no /stream call)
        Browser->>FastAPI: GET /weekly-summaries/{week_year}/audio
        FastAPI-->>Browser: audio/mpeg stream
    end
```

---

## 4. Active Playback Loop (always-on background)

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI
    participant DB

    Note over app.js: Runs continuously during playback

    loop Every 10s (timeupdate throttled)
        app.js->>FastAPI: POST /playback-position/{video_id}<br/>{position_seconds, duration_seconds}
        FastAPI->>DB: INSERT OR REPLACE playback_positions
        Note over FastAPI: Fire-and-forget; errors ignored
    end

    loop Every 3s
        app.js->>FastAPI: GET /status
        FastAPI-->>app.js: {status, queue_hash, current_video_id}
        alt queue_hash changed
            Note over app.js: Another device modified queue
            app.js->>FastAPI: GET /queue
            FastAPI-->>app.js: updated queue
            Note over app.js: Refresh now-playing indicator
        end
    end

    loop timeupdate (every ~250ms)
        alt within prefetchThresholdSeconds of end
            app.js->>FastAPI: POST /queue/prefetch/{next_video_id}
            FastAPI-->>app.js: {status: "started"|"cached"|"downloading"}
            Note over app.js: Fire-and-forget (deduplicated by app.js flag)
        end
    end

    opt transcription_enabled
        loop Every 5s
            app.js->>FastAPI: GET /transcription/status/{video_id}
            FastAPI-->>app.js: {status, summary?, trilium_note_url?}
            Note over app.js: Update transcription status UI
        end
    end

    opt Tab becomes visible after being hidden
        app.js->>FastAPI: GET /status
        FastAPI-->>app.js: status
        app.js->>FastAPI: GET /queue
        FastAPI-->>app.js: queue
        opt player paused
            app.js->>FastAPI: GET /playback-position/{video_id}
            FastAPI-->>app.js: {position_seconds}
            alt drift > 15s
                Note over app.js: Seek to server position
            end
        end
    end
```

---

## 5. Track Ends Naturally

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI
    participant DB

    Browser->>app.js: "ended" event fires

    app.js->>FastAPI: DELETE /playback-position/{video_id}
    FastAPI->>DB: DELETE position record
    Note over FastAPI: Fire-and-forget

    app.js->>FastAPI: POST /queue/next
    FastAPI->>DB: DELETE current item, reorder positions
    DB-->>FastAPI: next queue item
    FastAPI-->>app.js: {status, type, youtube_id|week_year, title, ...}

    alt type = "youtube"
        Note over app.js: Dispatch to Play Queue flow (step 3)
    else type = "summary"
        Note over app.js: Dispatch to summary playback
    else status = "queue_empty"
        Note over app.js: Pause player, update status to idle
    end
```

---

## 6. User Clicks Next

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI
    participant DB

    Browser->>app.js: User clicks "Next" button

    app.js->>FastAPI: POST /queue/next
    FastAPI->>DB: DELETE current item, reorder positions
    DB-->>FastAPI: next queue item
    FastAPI-->>app.js: {status, type, youtube_id|week_year, title, ...}

    alt type = "youtube"
        Note over app.js: Dispatch to Play Queue flow (step 3)
    else type = "summary"
        Note over app.js: Dispatch to summary playback
    else status = "queue_empty"
        Note over app.js: Pause player, update status to idle
    end
```

---

## 7. Stop Stream

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI

    Browser->>app.js: User clicks "Stop"
    Note over app.js: Pause audio element immediately (local)
    app.js->>FastAPI: POST /stop
    FastAPI-->>app.js: {status: "stream stopped"}
    Note over app.js: Update status display to idle
```

---

## 8. Remove from Queue

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI
    participant DB

    Browser->>app.js: User clicks remove icon on queue item
    app.js->>FastAPI: DELETE /queue/{queue_id}
    FastAPI->>DB: DELETE from queue, reorder positions
    DB-->>FastAPI: ok
    FastAPI-->>app.js: {status: "removed", queue_id}

    app.js->>FastAPI: GET /queue
    FastAPI-->>app.js: updated queue
    Note over app.js: Re-render queue
```

---

## 9. Clear Queue

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI
    participant DB

    Browser->>app.js: User clicks "Clear Queue" (confirmation dialog shown)
    Browser->>app.js: User confirms
    app.js->>FastAPI: POST /queue/clear
    FastAPI->>DB: DELETE all queue items
    FastAPI-->>app.js: {status: "cleared"}

    app.js->>FastAPI: GET /queue
    FastAPI-->>app.js: {queue: []}
    Note over app.js: Re-render empty queue
```

---

## 10. Reorder Queue (drag-and-drop)

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI
    participant DB

    Browser->>app.js: User drops item in new position<br/>(mouse or touch drag)
    Note over app.js: Compute new order from DOM

    app.js->>FastAPI: POST /queue/reorder<br/>{queue_item_ids: [id1, id2, ...]}
    FastAPI->>DB: UPDATE queue positions
    DB-->>FastAPI: ok
    FastAPI-->>app.js: {status: "reordered"}

    app.js->>FastAPI: GET /queue
    FastAPI-->>app.js: updated queue
    Note over app.js: Re-render queue with new order

    alt error
        Note over app.js: Restore original DOM order
    end
```

---

## 11. Smart Suggestions

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI
    participant DB
    participant YT

    Browser->>app.js: User clicks "Smart Suggestions"
    Note over app.js: Show loading spinner

    app.js->>FastAPI: POST /queue/suggestions
    FastAPI->>DB: SELECT recent play history
    FastAPI->>YT: Fetch related video suggestions
    FastAPI->>DB: INSERT suggested videos into queue
    FastAPI-->>app.js: {status, added: [...], failed: [...], total_suggestions}

    Note over app.js: Hide spinner, show count of added videos

    app.js->>FastAPI: GET /queue
    FastAPI-->>app.js: updated queue with suggestions
    Note over app.js: Re-render queue
```

---

## 12. Clear History

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI
    participant DB

    Browser->>app.js: User clicks "Clear History" (confirmation shown)
    Browser->>app.js: User confirms
    app.js->>FastAPI: POST /history/clear
    FastAPI->>DB: DELETE FROM play_history
    FastAPI-->>app.js: {status: "cleared"}

    app.js->>FastAPI: GET /history
    FastAPI->>DB: SELECT last 10 plays
    FastAPI-->>app.js: []
    Note over app.js: Re-render empty history
```

---

## 13. View Transcription Summary

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI

    Note over app.js: Background polling running (every 5s)
    loop Every 5s
        app.js->>FastAPI: GET /transcription/status/{video_id}
        FastAPI-->>app.js: {status, summary?, trilium_note_url?}
        Note over app.js: Update transcription status UI with icon/text
    end

    Browser->>app.js: User clicks "View Summary"
    app.js->>FastAPI: GET /transcription/summary/{video_id}
    alt summary exists
        FastAPI-->>app.js: {video_id, status, summary, trilium_note_url?}
        Note over app.js: Open modal with formatted summary HTML<br/>Show "Open in Trilium" link if available
    else not found
        FastAPI-->>app.js: 404
        Note over app.js: Show helpful "not yet available" message
    end
```

---

## 14. Weekly Summaries: Add to Queue / Play

```mermaid
sequenceDiagram
    participant Browser
    participant app.js
    participant FastAPI
    participant DB

    Note over app.js: On page load (if weekly_summary_enabled)
    app.js->>FastAPI: GET /weekly-summaries?limit=10
    FastAPI->>DB: SELECT weekly_summaries ORDER BY created_at DESC
    DB-->>FastAPI: summary rows
    FastAPI-->>app.js: [{week_year, title, audio_file_path, duration_seconds, ...}]
    Note over app.js: Render weekly summaries section

    alt User clicks "Add to Queue" on a summary
        Browser->>app.js: click
        app.js->>FastAPI: POST /queue/add-summary/{week_year}
        FastAPI->>DB: INSERT INTO queue (type="summary", week_year)
        FastAPI-->>app.js: {status: "success", queue_id, message}
        app.js->>FastAPI: GET /queue
        FastAPI-->>app.js: updated queue
    end

    alt User clicks summary item to play directly
        Browser->>app.js: click
        app.js->>FastAPI: POST /queue/add-summary/{week_year}
        FastAPI-->>app.js: {status: "success", queue_id}
        Note over app.js: Call startSummaryFromQueue()
        Browser->>FastAPI: GET /weekly-summaries/{week_year}/audio?t={timestamp}
        FastAPI-->>Browser: audio/mpeg stream
        Note over app.js: Update MediaSession metadata
    end
```

---

## 15. Client Log Flushing

```mermaid
sequenceDiagram
    participant app.js
    participant FastAPI

    Note over app.js: Logs accumulate in in-memory buffer<br/>via log(level, message, context)

    Note over app.js: On first log: schedule flushLogs()<br/>after LOG_BATCH_INTERVAL ms

    app.js->>FastAPI: POST /admin/client-logs<br/>[{level, message, timestamp, context}, ...]
    FastAPI-->>app.js: {status: "ok", received: count}
    Note over app.js: Clear buffer; schedule next flush if buffer non-empty

    alt Page unload (beforeunload)
        Note over app.js: navigator.sendBeacon() used for reliability<br/>POST /admin/client-logs (non-blocking)
    end
```

---

## 16. Admin Stats Page

```mermaid
sequenceDiagram
    participant Browser
    participant AdminJS as Admin page JS
    participant FastAPI
    participant DB

    Browser->>FastAPI: GET /admin/stats
    FastAPI-->>Browser: HTML stats dashboard (full page navigation)

    par Admin dashboard data
        AdminJS->>FastAPI: GET /admin/llm-usage/stats<br/>?start_date&end_date&provider&model&feature&limit
        FastAPI->>DB: SELECT llm_usage_stats with filters
        DB-->>FastAPI: usage rows
        FastAPI-->>AdminJS: [{provider, model, tokens, cost, feature, ...}]
    and
        AdminJS->>FastAPI: GET /admin/llm-usage/summary<br/>?start_date&end_date
        FastAPI->>DB: SELECT aggregated totals
        DB-->>FastAPI: summary row
        FastAPI-->>AdminJS: {total_cost, total_tokens, by_provider, ...}
    end

    opt Manual weekly summary trigger
        Browser->>FastAPI: POST /admin/weekly-summary/trigger<br/>{date?: "YYYY-MM-DD"}
        FastAPI-->>Browser: {status: "triggered", message, date}
    end

    opt Check next scheduled run
        Browser->>FastAPI: GET /admin/weekly-summary/next-run
        FastAPI-->>Browser: {status, next_run_time?, message}
    end
```

---

## Endpoint Reference

All 33 endpoints across 5 route files plus `main.py`:

### main.py
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Main HTML page with injected `window.appConfig` |
| GET | `/vpn-status` | Check if client IP is within the WireGuard subnet |

### routes/stream.py
| Method | Path | Description |
|--------|------|-------------|
| POST | `/stream` | Start streaming a YouTube video |
| GET | `/audio/{video_id}` | Serve MP3 audio (range-request capable) |
| HEAD | `/audio/{video_id}` | Check if audio file is ready |
| POST | `/stop` | Stop the current stream |
| GET | `/status` | Streaming status + queue hash |
| GET | `/history` | Last N played videos |
| POST | `/history/clear` | Clear all play history |
| GET | `/playback-position/{video_id}` | Get saved position |
| POST | `/playback-position/{video_id}` | Save current position |
| DELETE | `/playback-position/{video_id}` | Clear saved position |
| GET | `/playback-positions` | Batch-fetch positions by video IDs |

### routes/queue.py
| Method | Path | Description |
|--------|------|-------------|
| POST | `/queue/add` | Add YouTube video to queue |
| GET | `/queue` | Get current queue |
| DELETE | `/queue/{queue_id}` | Remove one queue item |
| POST | `/queue/next` | Advance to next item in queue |
| POST | `/queue/clear` | Clear entire queue |
| POST | `/queue/reorder` | Reorder queue items |
| POST | `/queue/prefetch/{video_id}` | Pre-download next track audio |
| POST | `/queue/suggestions` | Generate and add smart suggestions |

### routes/transcription.py
| Method | Path | Description |
|--------|------|-------------|
| GET | `/transcription/status/{video_id}` | Get transcription job status |
| POST | `/transcription/start/{video_id}` | Manually trigger transcription |
| GET | `/transcription/summary/{video_id}` | Get summary text + Trilium link |

### routes/weekly_summaries.py
| Method | Path | Description |
|--------|------|-------------|
| GET | `/weekly-summaries` | List recent weekly summaries |
| GET | `/weekly-summaries/{week_year}/audio` | Stream weekly summary audio |
| POST | `/queue/add-summary/{week_year}` | Add weekly summary to queue |

### routes/admin.py
| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/stats` | HTML stats dashboard |
| POST | `/admin/weekly-summary/trigger` | Manually trigger weekly summary |
| GET | `/admin/weekly-summary/next-run` | Next scheduled summary run time |
| GET | `/admin/llm-usage/stats` | LLM usage records (filterable) |
| GET | `/admin/llm-usage/summary` | Aggregated LLM usage totals |
| POST | `/admin/client-logs` | Receive browser logs |
| GET | `/admin/client-logs` | Read recent browser logs |
| DELETE | `/admin/client-logs` | Clear browser logs |
