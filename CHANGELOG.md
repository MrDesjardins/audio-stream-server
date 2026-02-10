# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - 2026-02-09

### Added
- **ElevenLabs TTS Cost Tracking**: Added automatic usage tracking for ElevenLabs TTS API calls with character count logging
- **Whisper/Voxtral Per-Minute Pricing**: Implemented per-second pricing calculations for audio transcription models
- **Audio Duration Tracking**: Added `audio_duration_seconds` field to LLM usage stats for accurate transcription cost calculations
- **Mistral Provider Validation**: Added proper configuration validation for Mistral/Voxtral transcription provider

### Changed
- **Weekly Summary Schedule**: Changed from Friday 11 PM to Sunday 11 PM Pacific (better alignment with ISO week ending)
  - ISO weeks run Monday-Sunday
  - Summary now ready for Monday morning listening
- **Migration System**: Update script now runs all 6 migration files automatically:
  - `migrate_database.py` (base schema)
  - `migrate_add_metadata.py` (channel/thumbnail fields)
  - `migrate_add_queue_columns.py` (queue type/week_year)
  - `migrate_add_llm_stats.py` (LLM usage tracking)
  - `migrate_add_audio_duration.py` (audio duration for costs)
  - `migrate_add_weekly_summary.py` (weekly summaries table)

### Fixed
- **OpenAI TTS Cost Tracking**: Fixed missing usage tracking for OpenAI TTS (tts-1, tts-1-hd)
  - Now logs character count and model info to database
  - Added pricing to stats dashboard ($15/1M for tts-1, $30/1M for tts-1-hd)
- **ElevenLabs TTS Pricing**: Added pricing to stats dashboard for all ElevenLabs models:
  - `eleven_flash_v2_5`: $100/1M chars (~$0.10 per 1K)
  - `eleven_turbo_v2_5`, `eleven_multilingual_v2`, `eleven_monolingual_v1`: $300/1M chars
- **Path Expansion in routes/transcription.py**: Fixed missing path expansion before file existence check
  - Changed from `os.path.exists()` to `expand_path().exists()`
  - Prevents failures when paths contain `~` or symbolic links
- **Mistral Provider Support**: Fixed config validation to accept `mistral` as valid transcription provider
  - Previously showed error: "Must be 'openai' or 'gemini'"
  - Now accepts: "Must be 'openai', 'gemini', or 'mistral'"
  - Added API key validation for Mistral

### Testing
- All 443 tests passing
- Updated transcription route tests to mock `expand_path` instead of `os.path.exists`
- Added ElevenLabs TTS tracking tests

### Documentation
- Updated README.md with:
  - Sunday 11 PM schedule for weekly summaries
  - All three transcription providers (OpenAI, Mistral, Gemini)
  - Complete pricing table including TTS models
  - All 6 migration files with descriptions
- Updated CLAUDE.md with:
  - Complete migration file list
  - Updated migration descriptions
- Updated .env.example with:
  - Sunday schedule clarification
  - ISO week explanation (Monday-Sunday)

## Design Improvements Proposed

### 1. Configuration Validation Registry Pattern
- Declarative provider registry for automatic validation
- Single source of truth for providers
- Auto-generated error messages

### 2. Migration Auto-Discovery Pattern
- Auto-discover and run all migrations in correct order
- Warning system for migrations not in defined order
- Prevents forgotten migrations in update.sh

### 3. Cost Tracking Decorator Pattern
- Enforce tracking for all LLM API calls
- Separate tracking code from business logic
- Consistent tracking across providers

### 4. Pricing Configuration File
- Centralized YAML-based pricing configuration
- Shared between Python backend and JavaScript frontend
- Easy to update when providers change prices
- Version tracking for historical costs

### 5. Pre-commit Hook Enhancements
- Automated checks for common mistakes
- Path expansion validation
- LLM tracking coverage checks
- Migration registration verification

## Cost Tracking Coverage

### ✅ Fully Tracked
- OpenAI GPT models (gpt-4o-mini, gpt-4o, etc.)
- OpenAI TTS (tts-1, tts-1-hd) **[FIXED TODAY]**
- OpenAI Whisper (per-minute pricing) **[FIXED TODAY]**
- Mistral Voxtral (per-minute pricing) **[FIXED TODAY]**
- Gemini models (all text and audio)
- ElevenLabs TTS (all models) **[FIXED TODAY]**

### Stats Dashboard Features
- Cost calculation for all models
- Per-minute pricing for audio transcription (Whisper, Voxtral)
- Per-character pricing for TTS (OpenAI, ElevenLabs)
- Per-token pricing for text models
- Filtering by provider, model, feature, date range
- Aggregated cost breakdowns by feature
- Visual charts for usage trends

## Migration Notes

### For Production Deployment
1. Pull latest changes: `git pull origin main`
2. Run update script: `./update.sh`
3. Update script will automatically:
   - Run all 6 migrations
   - Update dependencies
   - Restart service if running

### For Existing Databases
All migrations are idempotent and safe to run multiple times. They will:
- Create backups before making changes
- Skip if already applied
- Preserve all existing data

## Breaking Changes
None. All changes are backward compatible.

## Notes
- ISO weeks are Monday-Sunday (ISO 8601 standard)
- Weekly summary triggered Sunday 11 PM captures full week (Mon-Sun)
- "Last 7 days" logic aligns perfectly with ISO week boundaries
