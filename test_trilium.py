#!/usr/bin/env python3
"""Test Trilium connection and configuration."""

import httpx
from config import get_config


def test_trilium_connection():
    """Test if we can connect to Trilium and the parent note exists."""
    config = get_config()

    print("Testing Trilium configuration...")
    print(f"TRILIUM_URL: {config.trilium_url}")
    print(f"TRILIUM_PARENT_NOTE_ID: {config.trilium_parent_note_id}")
    print()

    headers = {"Authorization": config.trilium_etapi_token, "Content-Type": "application/json"}

    # Test 1: Check if Trilium is reachable
    print("Test 1: Checking if Trilium is reachable...")
    try:
        url = config.trilium_url.rstrip("/") + "/etapi/app-info"
        response = httpx.get(url, headers=headers, timeout=5.0)
        response.raise_for_status()
        app_info = response.json()
        print(f"✓ Connected to Trilium {app_info.get('appVersion', 'unknown version')}")
    except Exception as e:
        print(f"✗ Failed to connect to Trilium: {e}")
        print(f"  Make sure Trilium is running at {config.trilium_url}")
        print(f"  Check that TRILIUM_ETAPI_TOKEN is correct")
        return False

    # Test 2: Check if parent note exists
    print("\nTest 2: Checking if parent note exists...")
    try:
        url = config.trilium_url.rstrip("/") + f"/etapi/notes/{config.trilium_parent_note_id}"
        response = httpx.get(url, headers=headers, timeout=5.0)
        response.raise_for_status()
        note = response.json()
        print(f"✓ Parent note found: '{note.get('title', 'Untitled')}'")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            print(f"✗ Parent note not found (404)")
            print(f"  The note ID '{config.trilium_parent_note_id}' does not exist")
            print(f"  To get a valid note ID:")
            print(f"  1. Open Trilium Notes")
            print(f"  2. Right-click on the note where you want summaries")
            print(f"  3. Select 'Copy Note ID'")
            print(f"  4. Update TRILIUM_PARENT_NOTE_ID in your .env file")
        else:
            print(f"✗ Error checking parent note: {e}")
        return False
    except Exception as e:
        print(f"✗ Error checking parent note: {e}")
        return False

    # Test 3: Try to search notes by attribute (for deduplication)
    print("\nTest 3: Checking if we can search notes by attribute...")
    try:
        # Search for any note with youtube_id attribute (to test search functionality)
        search_query = "#youtube_id"
        url = config.trilium_url.rstrip("/") + "/etapi/notes"
        params = {"search": search_query}
        response = httpx.get(url, headers=headers, params=params, timeout=5.0)

        if response.status_code == 200:
            results = response.json()
            print(f"✓ Successfully searched notes (found {len(results)} with youtube_id attribute)")
        else:
            print(f"⚠ Search returned status {response.status_code}")
            print(f"  This might be okay - the deduplication may still work")
    except Exception as e:
        print(f"⚠ Could not test search: {e}")
        print(f"  This might be okay - the deduplication will be skipped if search fails")

    print("\n" + "=" * 50)
    print("All critical tests passed! Trilium is configured correctly.")
    print("=" * 50)
    print("\nNote: The application will:")
    print("- Create notes under the parent note you specified")
    print("- Add a 'youtube_id' attribute to each note for deduplication")
    print("- Only include the summary (not the full transcript)")
    return True


if __name__ == "__main__":
    test_trilium_connection()
