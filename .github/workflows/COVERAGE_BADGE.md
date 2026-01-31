# Coverage Badge Setup

The coverage badge workflow is configured and running! To display the badge in your README:

## Step 1: Get Your Gist ID

Your `GIST_ID` is stored as a GitHub secret. To get the badge URL:

1. Go to https://gist.github.com/MrDesjardins
2. Find the gist that contains `audio-stream-server-coverage.json`
3. Copy the Gist ID from the URL (e.g., `https://gist.github.com/MrDesjardins/abc123def456` → `abc123def456`)

## Step 2: Add Badge to README

Add this to the top of your `README.md`:

```markdown
# Audio Stream Server

![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/MrDesjardins/YOUR_GIST_ID/raw/audio-stream-server-coverage.json)
```

Replace `YOUR_GIST_ID` with the ID from Step 1.

## Step 3: Alternative - Use Shields.io Badge

If you prefer a simpler approach without dynamic updates:

```markdown
![Coverage](https://img.shields.io/badge/coverage-89%25-brightgreen)
```

Update the percentage manually when it changes, or use the dynamic gist approach above for automatic updates.

## Badge Colors

The badge automatically changes color based on coverage:
- 🔴 Red: 0-60%
- 🟡 Yellow: 60-80%
- 🟢 Green: 80-100%

Current coverage: **89%** 🟢
