#!/usr/bin/env python3
"""
patch.py — CLEAN build: merge splits, lower SDK, NO Frida.

Goal: verify a merged base.apk installs on Android 14.
"""

import os
import zipfile
import re
from pathlib import Path

DECODED = Path("base_decoded")


def log(msg):
    print(f"[PATCH] {msg}", flush=True)


def extract_split_libs():
    log("Extracting native libs from split...")
    target = DECODED / "lib" / "armeabi-v7a"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile("split_config.armeabi_v7a.apk", "r") as zf:
        for entry in zf.namelist():
            if entry.startswith("lib/") and entry.endswith(".so"):
                filename = os.path.basename(entry)
                with zf.open(entry) as src:
                    with open(target / filename, "wb") as dst:
                        dst.write(src.read())
                log(f"  → {filename}")


def fix_manifest():
    log("Fixing AndroidManifest.xml...")
    manifest = DECODED / "AndroidManifest.xml"
    if not manifest.exists():
        log("  ❌ AndroidManifest.xml not found")
        return False

    content = manifest.read_text()
    original = content

    for pat in [
        r'\s+android:isSplitRequired="[^"]*"',
        r'\s+android:isSplit="[^"]*"',
        r'\s+android:splitName="[^"]*"',
        r'\s+android:isolatedSplits="[^"]*"',
        r'\s+android:requiredSplitTypes="[^"]*"',
        r'\s+android:splitTypes="[^"]*"',
    ]:
        content = re.sub(pat, '', content)

    content = re.sub(r'<uses-split[^/]*/>', '', content)
    content = re.sub(r'<uses-split[^>]*>\s*</uses-split>', '', content)

    content = re.sub(
        r'<meta-data[^>]*android:name="com\.android\.vending\.splits[^"]*"[^/]*/>',
        '', content
    )
    content = re.sub(
        r'<meta-data[^>]*android:name="com\.android\.vending\.derived_apk[^"]*"[^/]*/>',
        '', content
    )

    if 'android:extractNativeLibs="false"' in content:
        content = content.replace(
            'android:extractNativeLibs="false"',
            'android:extractNativeLibs="true"'
        )
        log("  ✅ extractNativeLibs → true")
    elif 'android:extractNativeLibs="true"' not in content:
        content = re.sub(r'(<application\s)', r'\1android:extractNativeLibs="true" ', content, count=1)
        log("  ✅ Added extractNativeLibs=true")

    if content != original:
        manifest.write_text(content)
        log("  ✅ Manifest fixed")

    log("  Verification:")
    for term in ["isSplitRequired", "isSplit=", "splitName", "extractNativeLibs"]:
        log(f"    {term}: {content.count(term)}")

    return True


def fix_apktool_yml():
    log("Lowering SDK versions...")
    yml = DECODED / "apktool.yml"
    if not yml.exists():
        log("  ❌ apktool.yml not found")
        return False

    content = yml.read_text()
    original = content

    content = re.sub(r'minSdkVersion: \d+', 'minSdkVersion: 30', content)
    content = re.sub(r'targetSdkVersion: \d+', 'targetSdkVersion: 34', content)

    if content != original:
        yml.write_text(content)
        log("  ✅ SDK lowered to minSdk 30 / targetSdk 34")
    else:
        log("  ⚠️ No SDK lines matched — current:")
        for line in content.split('\n'):
            if 'Sdk' in line:
                log(f"    {line}")

    return True


def main():
    log("=" * 60)
    log("  CLEAN BUILD — SPLITS MERGED, NO FRIDA")
    log("=" * 60)
    if not DECODED.exists():
        log("❌ base_decoded not found")
        return 1
    try:
        extract_split_libs()
        fix_manifest()
        fix_apktool_yml()
    except Exception as e:
        log(f"❌ {e}")
        return 1
    log("=" * 60)
    log("  ✅ CLEAN PATCH DONE")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())
