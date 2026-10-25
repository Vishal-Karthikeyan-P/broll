"""Create the hard-case sample inputs in samples/ (text files plus generated audio). Run: python scripts/make_samples.py"""
import json
import os
import subprocess

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
os.makedirs(D, exist_ok=True)

TEXTS = {
    "01_abstract": "Trust is earned slowly. Patience beats talent when talent does not work hard.",
    "02_statistics": "Sales grew 40% in 2025. Revenue crossed 3.5 million dollars by December.",
    "03_named_person_brand": "Elon Musk said Tesla would double production this year. Investors are watching closely.",
    "04a_bank_finance": "She opened a bank account and made a small deposit every single month.",
    "04b_bank_river": "We sat on the river bank and watched the muddy water flow past.",
    "04c_cloud_computing": "Moving to the cloud means your data and software run on remote servers.",
    "04d_cloud_weather": "Dark clouds covered the sky just before the storm arrived.",
    "04e_mouse_computer": "Click the mouse and scroll down the screen on your computer.",
    "04f_mouse_animal": "A tiny mouse squeaked and nibbled on the cheese in the kitchen.",
    "04g_python_code": "Python is a popular programming language for developers who work with data.",
    "04h_python_snake": "The python slithered slowly through the jungle looking for prey.",
    "04i_value_business": "Our core value is respect for every customer and every team member.",
    "05_sad_news": "A factory fire killed three workers last night. Their families are grieving, and the town is in mourning.",
    "06_tutorial": "Start by opening the settings menu. Choose the privacy tab, then switch on two factor sign in. Save your changes and you are done.",
}
for name, t in TEXTS.items():
    open(os.path.join(D, name + ".txt"), "w").write(t)

json.dump({"script": "A tall cyclist rides along the very edge of the frame near the road. The scene stays calm and bright.",
           "aspect_ratios": ["9:16"]}, open(os.path.join(D, "07_portrait_edge_9x16.json"), "w"), indent=2)
json.dump({"scenes": [{"text": "Meet the new way to make videos.", "visual_hint": "creator editing video"},
                      {"text": "It works in minutes, not hours.", "visual_hint": "stopwatch"}],
           "aspect_ratios": ["16:9", "1:1"]}, open(os.path.join(D, "08_scene_list_with_hints.json"), "w"), indent=2)
json.dump({"script": ""}, open(os.path.join(D, "09_empty_script.json"), "w"))
json.dump({"script": "नमस्ते, आज हम बचत के बारे में बात करेंगे। हर महीने थोड़ा पैसा अलग रखें।", "voice": "hi-IN-female"}, open(os.path.join(D, "10_hindi_voice.json"), "w"))
open(os.path.join(D, "11_wrong_file_type.pdf"), "wb").write(b"%PDF-1.4\n% not audio\n")


def speech(path, text, voice="en-gb+f3"):
    wav = path + ".w.wav"
    subprocess.run(["espeak-ng", "-v", voice, "-w", wav, text], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav, path], check=True)
    os.remove(wav)
    open(os.path.splitext(path)[0] + ".txt", "w").write(text)


speech(os.path.join(D, "12_voiceover.mp3"), "Saving money starts with one small habit. Put a little aside every month and let it grow.")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "3", os.path.join(D, "13_silent.wav")], check=True)
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", os.path.join(D, "14_music_only.mp3")], check=True)
open(os.path.join(D, "15_corrupt.mp3"), "wb").write(b"not really audio data " * 100)
print("samples written to", D)
