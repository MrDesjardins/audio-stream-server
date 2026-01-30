#!/usr/bin/env python3
"""
List all available ElevenLabs voices for your account.
This shows which voices you can use with the API on your current plan.
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("ELEVENLABS_API_KEY")

if not api_key:
    print("❌ ELEVENLABS_API_KEY not found in .env file")
    exit(1)

print("Fetching available voices from ElevenLabs...\n")

try:
    # Use v1 endpoint which is more widely documented
    response = httpx.get(
        "https://api.elevenlabs.io/v1/voices",
        headers={"xi-api-key": api_key},
        timeout=10
    )

    response.raise_for_status()
    data = response.json()

    voices = data.get("voices", [])

    if not voices:
        print("❌ No voices found")
        exit(1)

    print(f"Found {len(voices)} voices:\n")
    print("=" * 80)

    # Categorize voices
    premade = []
    cloned = []
    generated = []
    professional = []
    other = []

    for voice in voices:
        category = voice.get("category", "unknown")
        if category == "premade":
            premade.append(voice)
        elif category == "cloned":
            cloned.append(voice)
        elif category == "generated":
            generated.append(voice)
        elif category == "professional":
            professional.append(voice)
        else:
            other.append(voice)

    # Print PRE-MADE voices (these should work on free tier)
    if premade:
        print("\n🎤 PRE-MADE VOICES (Free Tier Compatible):")
        print("-" * 80)
        for voice in premade:
            voice_id = voice.get("voice_id")
            name = voice.get("name")
            labels = voice.get("labels", {})
            description = labels.get("description", "No description")
            gender = labels.get("gender", "unknown")
            age = labels.get("age", "unknown")
            accent = labels.get("accent", "unknown")
            use_case = labels.get("use case", "general")

            print(f"\n  Name: {name}")
            print(f"  ID: {voice_id}")
            print(f"  Gender: {gender}, Age: {age}, Accent: {accent}")
            print(f"  Use case: {use_case}")
            print(f"  Description: {description}")

    # Print CLONED voices (if any)
    if cloned:
        print("\n\n🔬 CLONED VOICES (Your Clones):")
        print("-" * 80)
        for voice in cloned:
            print(f"  {voice.get('name')} - {voice.get('voice_id')}")

    # Print GENERATED voices (if any)
    if generated:
        print("\n\n🎨 GENERATED VOICES (Voice Design):")
        print("-" * 80)
        for voice in generated:
            print(f"  {voice.get('name')} - {voice.get('voice_id')}")

    # Print PROFESSIONAL voices (likely require payment)
    if professional:
        print("\n\n💎 PROFESSIONAL VOICES (May Require Payment):")
        print("-" * 80)
        for voice in professional:
            print(f"  {voice.get('name')} - {voice.get('voice_id')}")

    # Print recommendation
    if premade:
        print("\n" + "=" * 80)
        print("\n📝 RECOMMENDATION:")
        print(f"   Use one of the {len(premade)} PRE-MADE voices listed above.")
        print("   Copy a voice ID and update your .env file:")
        print(f"\n   ELEVENLABS_VOICE_ID=<voice_id_here>")
    else:
        print("\n⚠️  No pre-made voices found. You may need to:")
        print("   1. Check your API key is correct")
        print("   2. Visit https://elevenlabs.io and add pre-made voices to your account")

    print("\n" + "=" * 80)

except httpx.HTTPStatusError as e:
    print(f"❌ HTTP Error: {e.response.status_code}")
    print(f"   {e.response.text}")
except Exception as e:
    print(f"❌ Error: {e}")
