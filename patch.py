#!/usr/bin/env python3

import os
import shutil
import zipfile
import re
from pathlib import Path

DECODED = Path("base_decoded")
FRIDA_DIR = Path("frida")


def log(msg):
    print(f"[PATCH] {msg}", flush=True)


def extract_split_libs():
    log("Extracting native libs...")
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


def copy_frida_files():
    log("Copying Frida files...")
    target_lib = DECODED / "lib" / "armeabi-v7a"
    target_lib.mkdir(parents=True, exist_ok=True)
    shutil.copy(FRIDA_DIR / "libfrida-gadget.so", target_lib / "libfrida-gadget.so")

    target_assets = DECODED / "assets"
    target_assets.mkdir(parents=True, exist_ok=True)
    shutil.copy(FRIDA_DIR / "frida_script.js", target_assets / "frida_script.js")
    shutil.copy(FRIDA_DIR / "libfrida-gadget.config.so",
                target_assets / "libfrida-gadget.config.so")


def fix_manifest():
    """
    Remove ALL split-APK-related declarations from AndroidManifest.xml
    so it installs as a standalone APK.
    """
    log("Fixing AndroidManifest.xml (removing split declarations)...")

    manifest = DECODED / "AndroidManifest.xml"
    if not manifest.exists():
        log("  ❌ AndroidManifest.xml not found")
        return False

    content = manifest.read_text()
    original = content

    # Remove split-related attributes
    content = re.sub(r'\s+android:isSplit="[^"]*"', '', content)
    content = re.sub(r'\s+android:splitName="[^"]*"', '', content)
    content = re.sub(r'\s+android:isolatedSplits="[^"]*"', '', content)

    # Remove split <meta-data> entries
    content = re.sub(
        r'<meta-data[^>]*android:name="com\.android\.vending\.splits[^"]*"[^/]*/>',
        '', content
    )
    content = re.sub(
        r'<meta-data[^>]*android:name="com\.android\.vending\.splits[^"]*"[^>]*>\s*</meta-data>',
        '', content
    )

    # Remove <uses-split> tags
    content = re.sub(
        r'<uses-split[^>]*/>',
        '', content
    )

    # Remove "split" attributes in <manifest> tag
    content = re.sub(
        r'<manifest[^>]*android:splitTypes="[^"]*"',
        lambda m: m.group(0).replace(f'android:splitTypes="{re.search(chr(34) + "([^" + chr(34) + "]*)" + chr(34), m.group(0)).group(1)}"', ''),
        content
    )

    if content != original:
        manifest.write_text(content)
        log(f"  ✅ Removed split declarations ({len(original) - len(content)} bytes)")
    else:
        log("  No split declarations found — checking manually")

    # Show the <manifest> and <application> opening tags for verification
    log("  Manifest head:")
    for line in content.split('\n')[:5]:
        log(f"    {line[:120]}")

    return True


def patch_application_smali():
    log("Patching ApplicationLoader.smali...")

    smali_file = None
    for smali_dir in DECODED.glob("smali*"):
        candidate = smali_dir / "org" / "platform" / "app" / "ApplicationLoader.smali"
        if candidate.exists():
            smali_file = candidate
            break

    if not smali_file:
        log("  ❌ Not found")
        return False

    content = smali_file.read_text()

    if "shadowLoadFrida" in content:
        log("  Already patched")
        return True

    helper_method = '''
.method public static shadowLoadFrida()V
    .locals 2
    :try_start_shadow
    const-string v0, "frida-gadget"
    invoke-static {v0}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V
    const-string v0, "ShadowCloner"
    const-string v1, "Frida loaded OK"
    invoke-static {v0, v1}, Landroid/util/Log;->d(Ljava/lang/String;Ljava/lang/String;)I
    :try_end_shadow
    .catch Ljava/lang/Throwable; {:try_start_shadow .. :try_end_shadow} :catch_shadow
    goto :goto_shadow_done
    :catch_shadow
    move-exception v0
    const-string v0, "ShadowCloner"
    const-string v1, "Frida load failed"
    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I
    :goto_shadow_done
    return-void
.end method

'''

    pattern = r'(\.method public final onCreate\(\)V)'
    match = re.search(pattern, content)
    if not match:
        log("  ❌ onCreate not found")
        return False

    content = content[:match.start()] + helper_method + content[match.start():]

    pattern2 = r'(\.method public final onCreate\(\)V\s*\n\s*\.locals \d+)'
    match2 = re.search(pattern2, content)
    if not match2:
        log("  ❌ Could not re-find onCreate")
        return False

    call_code = '''
    # ═══ SHADOW CLONER: Load Frida Gadget ═══
    invoke-static {}, Lorg/platform/app/ApplicationLoader;->shadowLoadFrida()V
'''

    content = content[:match2.end()] + call_code + content[match2.end():]
    smali_file.write_text(content)
    log("  ✅ Patched with static helper")
    return True


def main():
    log("=" * 60)
    log("  SHADOW CLONER — 1XBET Patch v4")
    log("=" * 60)
    if not DECODED.exists():
        return 1
    try:
        extract_split_libs()
        copy_frida_files()
        fix_manifest()
        if not patch_application_smali():
            return 1
    except Exception as e:
        log(f"❌ {e}")
        return 1
    log("=" * 60)
    log("  ✅ COMPLETE")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())
