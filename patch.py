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


def patch_application_smali():
    """
    Insert a NEW standalone static method that loads Frida.
    Call it from onCreate using an existing register (v0).
    
    This avoids touching .locals of onCreate entirely.
    """
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

    # ─── Step 1: Add a new static helper method BEFORE onCreate ───
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

    # Find onCreate and insert helper before it
    pattern = r'(\.method public final onCreate\(\)V)'
    match = re.search(pattern, content)

    if not match:
        log("  ❌ onCreate not found")
        return False

    # Insert helper method BEFORE onCreate
    content = content[:match.start()] + helper_method + content[match.start():]

    # ─── Step 2: Call shadowLoadFrida() at start of onCreate ───
    # Find onCreate and after .locals line, insert call
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
    log("  ✅ Patched with static helper method")
    return True


def main():
    log("=" * 60)
    log("  SHADOW CLONER — 1XBET Patch v3")
    log("=" * 60)
    if not DECODED.exists():
        return 1
    try:
        extract_split_libs()
        copy_frida_files()
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
