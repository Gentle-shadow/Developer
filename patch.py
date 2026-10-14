#!/usr/bin/env python3
"""
patch.py — Frida injection + split merging into decoded base.

Runs inside GitHub Actions after apktool decompiles base.apk.
"""

import os
import shutil
import zipfile
import re
import subprocess
from pathlib import Path

DECODED = Path("base_decoded")
FRIDA_DIR = Path("frida")


def log(msg):
    print(f"[PATCH] {msg}", flush=True)


def run(cmd, check=True):
    log(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        log(f"  STDERR: {result.stderr[:500]}")
        raise RuntimeError(f"Command failed: {cmd}")
    return result


def extract_split_libs():
    """Extract lib/*.so from armeabi_v7a split"""
    log("Extracting native libs from split APK...")

    target_lib_dir = DECODED / "lib" / "armeabi-v7a"
    target_lib_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile("split_config.armeabi_v7a.apk", "r") as zf:
        for entry in zf.namelist():
            if entry.startswith("lib/") and entry.endswith(".so"):
                filename = os.path.basename(entry)
                target_file = target_lib_dir / filename
                with zf.open(entry) as src:
                    with open(target_file, "wb") as dst:
                        dst.write(src.read())
                log(f"  → {filename} ({target_file.stat().st_size} bytes)")


def copy_frida_files():
    """Copy Frida files into decoded structure"""
    log("Copying Frida files...")

    target_lib = DECODED / "lib" / "armeabi-v7a"
    target_lib.mkdir(parents=True, exist_ok=True)
    shutil.copy(FRIDA_DIR / "libfrida-gadget.so",
                target_lib / "libfrida-gadget.so")
    log("  → lib/armeabi-v7a/libfrida-gadget.so")

    target_assets = DECODED / "assets"
    target_assets.mkdir(parents=True, exist_ok=True)
    shutil.copy(FRIDA_DIR / "frida_script.js",
                target_assets / "frida_script.js")
    shutil.copy(FRIDA_DIR / "libfrida-gadget.config.so",
                target_assets / "libfrida-gadget.config.so")
    log("  → assets/frida_script.js")
    log("  → assets/libfrida-gadget.config.so")


def patch_application_smali():
    """Patch ApplicationLoader.smali to load Frida"""
    log("Patching ApplicationLoader.smali...")

    smali_file = None
    for smali_dir in DECODED.glob("smali*"):
        candidate = smali_dir / "org" / "platform" / "app" / "ApplicationLoader.smali"
        if candidate.exists():
            smali_file = candidate
            break

    if not smali_file:
        log("  ❌ ApplicationLoader.smali not found")
        return False

    log(f"  Found: {smali_file}")
    content = smali_file.read_text()

    if "frida-gadget" in content:
        log("  Already patched — skipping")
        return True

    # Find onCreate and increase locals
    pattern = r'(\.method public final onCreate\(\)V\s*\n\s*\.locals )(\d+)'
    match = re.search(pattern, content)
    if not match:
        log("  ❌ Could not find onCreate")
        return False

    locals_count = int(match.group(2)) + 3

    inject = f""".method public final onCreate()V
    .locals {locals_count}

    # ═══ SHADOW CLONER: Load Frida Gadget ═══
    :try_start_shadow
    const-string v0, "frida-gadget"
    invoke-static {{v0}}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V
    const-string v0, "ShadowCloner"
    const-string v1, "Frida loaded OK"
    invoke-static {{v0, v1}}, Landroid/util/Log;->d(Ljava/lang/String;Ljava/lang/String;)I
    :try_end_shadow
    .catch Ljava/lang/Throwable; {{:try_start_shadow .. :try_end_shadow}} :catch_shadow
    goto :goto_shadow_done

    :catch_shadow
    move-exception v0
    const-string v1, "ShadowCloner"
    new-instance v2, Ljava/lang/StringBuilder;
    invoke-direct {{v2}}, Ljava/lang/StringBuilder;-><init>()V
    const-string v3, "Frida load failed: "
    invoke-virtual {{v2, v3}}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {{v0}}, Ljava/lang/Throwable;->getMessage()Ljava/lang/String;
    move-result-object v3
    invoke-virtual {{v2, v3}}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {{v2}}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v2
    invoke-static {{v1, v2}}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I

    :goto_shadow_done"""

    new_content = content[:match.start()] + inject + content[match.end():]
    smali_file.write_text(new_content)
    log(f"  ✅ Patched: {smali_file}")
    return True


def fix_manifest_splits():
    """
    Remove split APK declarations from AndroidManifest.
    When we merge splits into base, we must clear split metadata.
    """
    log("Fixing AndroidManifest split declarations...")

    manifest = DECODED / "AndroidManifest.xml"
    if not manifest.exists():
        log("  ❌ AndroidManifest.xml not found")
        return False

    content = manifest.read_text()

    # Remove split-related attributes
    # Common patterns:
    # - android:isSplit="true"
    # - android:splitName="..."
    # - <meta-data android:name="com.android.vending.splits" ... />
    
    original_len = len(content)
    content = re.sub(r'\s*android:isSplit="[^"]*"', '', content)
    content = re.sub(r'\s*android:splitName="[^"]*"', '', content)
    
    # Remove split-required meta-data
    content = re.sub(
        r'<meta-data\s+android:name="com\.android\.vending\.splits[^"]*"[^/]*/>',
        '',
        content
    )
    content = re.sub(
        r'<meta-data\s+android:name="com\.android\.vending\.splits[^"]*"[^>]*></meta-data>',
        '',
        content
    )

    if len(content) != original_len:
        manifest.write_text(content)
        log(f"  ✅ Removed split declarations ({original_len - len(content)} bytes)")
    else:
        log("  No split declarations found (already standalone)")

    return True


def main():
    log("=" * 60)
    log("  SHADOW CLONER — 1XBET Patch Script")
    log("=" * 60)

    if not DECODED.exists():
        log(f"❌ Decoded folder not found: {DECODED}")
        return 1

    try:
        extract_split_libs()
        copy_frida_files()
        fix_manifest_splits()
        if not patch_application_smali():
            return 1
    except Exception as e:
        log(f"❌ Error: {e}")
        return 1

    log("=" * 60)
    log("  ✅ PATCH COMPLETE")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())
