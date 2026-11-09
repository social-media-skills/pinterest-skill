#!/usr/bin/env python3
"""Fail if the repo contains media that isn't documented example material.

    python3 tests/check_media.py

Every image, video or audio file tracked by git must be:
- inside skills/ in a folder (or under a parent) that has a CREDITS.md saying where it came from
  (or a LICENSE.txt for bundled assets such as generated sound effects), or the README showcase
  (skills/*/examples/showcase.png),
- a font or the repo's .github/cover.png.
And no file may carry camera or phone metadata (camera make/model, GPS, Apple/Android video
tags): that is the sign of a real personal photo or video, which never belongs in this repo.
"""
import os, subprocess, sys

MEDIA = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".jpg", ".jpeg", ".png", ".gif", ".webp",
         ".heic", ".wav", ".mp3", ".m4a", ".aac")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
files = [f for f in subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], capture_output=True, text=True).stdout.split("\0") if f]
problems = []


def has_credits(path):
    """A CREDITS.md (or, for bundled assets, a LICENSE.txt) in the file's folder or a parent under skills/."""
    d = os.path.dirname(path)
    while d.startswith("skills/"):
        if any(os.path.exists(os.path.join(d, x)) for x in ("CREDITS.md", "LICENSE.txt")):
            return True
        d = os.path.dirname(d)
    return False


def personal_metadata(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
        try:
            from PIL import Image
            with Image.open(path) as im:
                ex = im.getexif()
                tags = {0x010F: "camera make", 0x0110: "camera model", 0x8825: "GPS"}
                found = [name for tag, name in tags.items() if ex.get(tag)]
                return ", ".join(found)
        except Exception:
            return ""
    if ext in (".mp4", ".mov", ".m4v"):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", path],
                             capture_output=True, text=True).stdout.lower()
        for needle in ("com.apple.quicktime.make", "com.apple.quicktime.model", "location", "com.android"):
            if needle in out:
                return needle
    return ""


for f in files:
    if os.path.islink(f):
        problems.append(f"{f}: a symlink points outside the repo (it can carry a local path); remove it or add it to .gitignore")
        continue
    if not f.lower().endswith(MEDIA):
        continue
    if f == ".github/cover.png" or "/fonts/" in f:
        pass
    elif f.startswith("skills/") and f.endswith("/examples/showcase.png"):
        pass
    elif f.startswith("skills/") and has_credits(f):
        pass
    else:
        problems.append(f"{f}: media outside a credited example folder")
    meta = personal_metadata(f)
    if meta:
        problems.append(f"{f}: carries {meta} metadata, the sign of a personal photo or video")

if problems:
    print("Media check failed:\n  " + "\n  ".join(problems))
    sys.exit(1)
print(f"Media check passed ({sum(1 for f in files if f.lower().endswith(MEDIA))} media files, all documented).")
