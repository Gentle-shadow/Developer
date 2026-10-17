#!/usr/bin/env python3
import zipfile, shutil, os

def log(msg): print(f"[PATCH] {msg}")

def merge_splits():
    log("Merging split libs into base.apk...")
    # Copy original base
    shutil.copy("base.apk", "1xbet_merged.apk")
    
    # Add split libs
    with zipfile.ZipFile("1xbet_merged.apk", "a") as zf:
        with zipfile.ZipFile("split_config.armeabi_v7a.apk") as split:
            for entry in split.namelist():
                if entry.startswith("lib/"):
                    with split.open(entry) as src:
                        zf.writestr(entry, src.read())
                    log(f"  Added {entry}")
    log("✅ Merged APK ready: 1xbet_merged.apk")

if __name__ == "__main__":
    merge_splits()
