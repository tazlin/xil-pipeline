import os
from elevenlabs.client import ElevenLabs

# Pulling from your environment variable as we discussed
client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))

print("--- Your Available Voices ---")
response = client.voices.get_all()
for v in response.voices:
    if v.category == "premade":
        print(f"Name: {v.name:15} | ID: {v.voice_id} | Category: {v.category}")