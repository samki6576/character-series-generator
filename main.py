import json
import os
import subprocess
import asyncio
import time
import requests
import dashscope
from openai import OpenAI

# ============================================================
# 1️⃣ YOUR API KEY
# ============================================================
QWEN_API_KEY = "sk-ws-H.XIRERM.Vfpa.MEQCIHxyRZqHWwJGrqtDfBV6d35OvRlGnGqbnoj9V0YrD3MFAiAsU9S_ksWQZvauYtekgOF9EiHVw2Za_Ir7w7lkkBsjGQ"
QWEN_MODEL = "qwen3.6-plus"
# ============================================================

dashscope.api_key = QWEN_API_KEY

client = OpenAI(
    api_key=QWEN_API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1",
)

# ============================================================
# STEP 1: Load character
# ============================================================
with open("character_profile.json", "r") as f:
    character = json.load(f)

print(f"✅ Loaded character: {character['name']}")

# ============================================================
# STEP 2: Get story idea
# ============================================================
story_idea = input("🎬 Type a one-line story idea: ")

# ============================================================
# STEP 3: Generate script
# ============================================================
print("📝 Writing script with Qwen AI...")

prompt_text = f"""
You are a screenwriter. 
Character profile: {json.dumps(character)}
Story idea: {story_idea}

Write a short script with exactly 3 scenes. 
Output ONLY valid JSON format with a "scenes" list. 
Each scene must have: "description", "narration", "video_prompt".
"""

try:
    response = client.responses.create(
        model=QWEN_MODEL,
        input=prompt_text,
    )
    
    script_text = ""
    for item in response.output:
        if item.type == "message":
            script_text = item.content[0].text
            break
    
    if not script_text:
        print("❌ No response received.")
        exit()
        
    print("✅ Script generated!")

except Exception as e:
    print(f"❌ API Error: {e}")
    exit()

# Parse JSON
try:
    start = script_text.find('{')
    end = script_text.rfind('}') + 1
    script_json = json.loads(script_text[start:end])
except:
    script_json = json.loads(script_text)

scenes = script_json["scenes"]
print(f"✅ Script written! {len(scenes)} scenes.")

# ============================================================
# STEP 4: Generate Voiceover
# ============================================================
print("🎤 Generating voiceovers...")

async def generate_audio(scene_index, text, voice_name):
    from edge_tts import Communicate
    output_file = f"scene_{scene_index}_audio.mp3"
    comm = Communicate(text, voice_name)
    await comm.save(output_file)
    return output_file

async def run_tts():
    tasks = []
    for i, scene in enumerate(scenes):
        tasks.append(generate_audio(i+1, scene["narration"], character["voice"]))
    return await asyncio.gather(*tasks)

audio_files = asyncio.run(run_tts())
print("✅ Voiceovers done!")

# ============================================================
# STEP 5: Generate REAL video clips using HappyHorse
# ============================================================
print("🎬 Generating video clips with HappyHorse...")
print("⏳ This takes 1-3 minutes per scene. Please wait...")

HAPPYHORSE_URL = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"

headers = {
    "Authorization": f"Bearer {QWEN_API_KEY}",
    "Content-Type": "application/json",
    "X-DashScope-Async": "enable"  # REQUIRED for async video tasks - was missing
}

# Correct status-check endpoint (different from the submission URL)
TASK_STATUS_URL = "https://dashscope-intl.aliyuncs.com/api/v1/tasks"

video_files = []

for i, scene in enumerate(scenes):
    print(f"   Rendering scene {i+1}/{len(scenes)}...")
    
    # Build a prompt that includes character and style
    prompt = f"{scene['video_prompt']}. Style: {character['style']}. Character: {character['name']}, {character['personality']}."
    
    payload = {
        "model": "wan2.7-t2v",  # text-to-video model (wanx-v1 was image-only)
        "input": {
            "prompt": prompt
        },
        "parameters": {
            "duration": 4,   # 4-second clips
            "size": "640*360"
        }
    }
    
    # Submit the video task
    response = requests.post(HAPPYHORSE_URL, headers=headers, json=payload)
    
    if response.status_code == 200:
        task_id = response.json().get("output", {}).get("task_id")
        if not task_id:
            print("   ⚠️ No task_id received. Using static fallback.")
            # Fallback: create a static image video (we already have that code)
            video_files.append(None)
            continue
            
        # Poll for result (up to 5 minutes)
        result_url = None
        for attempt in range(30):
            time.sleep(10)
            status_response = requests.get(
                f"{TASK_STATUS_URL}/{task_id}",
                headers={"Authorization": f"Bearer {QWEN_API_KEY}"}
            )
            status_data = status_response.json()
            state = status_data.get("output", {}).get("task_status", "")
            
            if state == "SUCCEEDED":
                result_url = status_data.get("output", {}).get("video_url")
                break
            elif state == "FAILED":
                print(f"   ❌ Video generation failed for scene {i+1}: {status_data.get('output', {}).get('message', 'unknown error')}")
                break
        
        if result_url:
            # Download the video
            video_data = requests.get(result_url).content
            video_file = f"scene_{i+1}.mp4"
            with open(video_file, "wb") as f:
                f.write(video_data)
            video_files.append(video_file)
            print(f"   ✅ Scene {i+1} video saved!")
        else:
            video_files.append(None)
            print(f"   ⚠️ Scene {i+1} timed out. Using static fallback.")
    else:
        print(f"   ❌ API error: {response.text}")
        video_files.append(None)

# ============================================================
# STEP 6: Fallback for failed videos – create static image clips
# ============================================================
print("🖼️ Checking for failed scenes...")

character_image = None
if "reference_images" in character and character["reference_images"]:
    for angle, path in character["reference_images"].items():
        if path and os.path.exists(path):
            character_image = path
            break

if not character_image and os.path.exists("character_references"):
    for file in os.listdir("character_references"):
        if file.endswith((".png", ".jpg", ".jpeg")):
            character_image = os.path.join("character_references", file)
            break

for i, vf in enumerate(video_files):
    if vf is None:
        print(f"   Creating static fallback for scene {i+1}")
        idx = i + 1
        # Use character image if available
        if character_image:
            subprocess.run([
                "ffmpeg",
                "-loop", "1",
                "-i", character_image,
                "-t", "4",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-vf", f"drawtext=text='Scene {idx}':fontsize=30:fontcolor=yellow:x=(w-text_w)/2:y=20,drawtext=text='{scenes[i]['description'][:40]}':fontsize=20:fontcolor=white:x=(w-text_w)/2:y=65",
                f"scene_{idx}.mp4",
                "-y"
            ], capture_output=True)
        else:
            # Just a blue screen
            subprocess.run([
                "ffmpeg",
                "-f", "lavfi",
                "-i", "color=c=blue:s=640x360:d=4",
                "-c:v", "libx264",
                f"scene_{idx}.mp4",
                "-y"
            ], capture_output=True)
        video_files[i] = f"scene_{idx}.mp4"

print("✅ All scenes ready!")

# ============================================================
# STEP 7: Merge video and audio
# ============================================================
print("✂️ Merging video and audio...")

for i in range(len(scenes)):
    idx = i + 1
    video_exists = os.path.exists(f"scene_{idx}.mp4")
    audio_exists = os.path.exists(f"scene_{idx}_audio.mp3")

    if not video_exists or not audio_exists:
        print(f"   ⚠️ Skipping merge for scene {idx} — missing file(s): "
              f"video={'OK' if video_exists else 'MISSING'}, audio={'OK' if audio_exists else 'MISSING'}")
        continue

    result = subprocess.run([
        "ffmpeg", "-i", f"scene_{idx}.mp4", "-i", f"scene_{idx}_audio.mp3",
        "-map", "0:v:0", "-map", "1:a:0",  # force video from clip, audio from narration
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        f"scene_{idx}_final.mp4", "-y"
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"   ⚠️ ffmpeg merge failed for scene {idx}: {result.stderr[-500:]}")
    elif not os.path.exists(f"scene_{idx}_final.mp4"):
        print(f"   ⚠️ ffmpeg reported success but scene_{idx}_final.mp4 was not created")
    else:
        print(f"   ✅ Merged scene {idx}")

# Create file list for concatenation — only include scenes that actually merged
merged_scenes = [i + 1 for i in range(len(scenes)) if os.path.exists(f"scene_{i+1}_final.mp4")]

if len(merged_scenes) < len(scenes):
    print(f"   ⚠️ Only {len(merged_scenes)}/{len(scenes)} scenes merged successfully — final video will be missing the rest")

if not merged_scenes:
    print("❌ No scenes merged successfully — cannot build final_episode.mp4")
    exit()

with open("file_list.txt", "w") as f:
    for idx in merged_scenes:
        f.write(f"file 'scene_{idx}_final.mp4'\n")

# Remove any stale output from a previous run so we can't mistake it for fresh output
if os.path.exists("final_episode.mp4"):
    os.remove("final_episode.mp4")

result = subprocess.run([
    "ffmpeg", "-f", "concat", "-safe", "0", "-i", "file_list.txt",
    "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
    "final_episode.mp4", "-y"
], capture_output=True, text=True)

if result.returncode != 0 or not os.path.exists("final_episode.mp4"):
    print(f"❌ ffmpeg concat failed: {result.stderr[-1000:]}")
    exit()

print("🎉🎉🎉 SUCCESS! 🎉🎉🎉")
video_path = os.path.abspath('final_episode.mp4')
print(f"✅ Your video is ready: {video_path}")

# ============================================================
# CLEANUP
# ============================================================
print("\n🧹 Cleaning up temporary files...")
for i in range(len(scenes)):
    idx = i+1
    for ext in ["_audio.mp3", ".mp4", "_final.mp4"]:
        try: os.remove(f"scene_{idx}{ext}")
        except: pass
try: os.remove("file_list.txt")
except: pass

print("\n✅ Done!")
print(f"📁 Open your moving video: {video_path}")