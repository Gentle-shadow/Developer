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

    content = smali_file.read_text()

    if "SHADOW CLONER" in content:
        log("  Already patched")
        return True

    # Match onCreate with original locals
    pattern = r'(\.method public final onCreate\(\)V\s*\n\s*\.locals )(\d+)'
    match = re.search(pattern, content)

    if not match:
        log("  ❌ onCreate not found")
        return False

    original_locals = int(match.group(2))
    log(f"  Original locals: {original_locals}")

    # Add 4 more registers — well above original
    new_locals = original_locals + 4
    log(f"  New locals: {new_locals}")

    # Use HIGH registers (last 4 added) so we don't clash with original low registers
    # If original locals was 15, new locals 19 gives v15, v16, v17, v18 as safe new registers
    r1 = original_locals       # v15
    r2 = original_locals + 1   # v16
    r3 = original_locals + 2   # v17

    inject = f'''
    # ═══ SHADOW CLONER: Load Frida Gadget ═══
    :try_start_shadow
    const-string v{r1}, "frida-gadget"
    invoke-static {{v{r1}}}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V
    :try_end_shadow
    .catch Ljava/lang/Throwable; {{:try_start_shadow .. :try_end_shadow}} :catch_shadow

    goto :goto_shadow_done

    :catch_shadow
    move-exception v{r1}
    const-string v{r2}, "ShadowCloner"
    const-string v{r3}, "Frida load failed"

    :goto_shadow_done'''

    # Replace the .locals line and insert our injection right after
    old_header = match.group(0)
    new_header = f'.method public final onCreate()V\n    .locals {new_locals}'

    content = content.replace(old_header, new_header + inject, 1)
    smali_file.write_text(content)
    log("  ✅ Patched")
    return True


def main():
    log("=" * 60)
    log("  SHADOW CLONER — 1XBET Patch")
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
