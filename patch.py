#!/usr/bin/env python3
"""
patch.py — In-place APK patch using standalone smali.jar (reliable).
"""
import os
import shutil
import subprocess
import zipfile
import re
from pathlib import Path

DECODED = Path("base_decoded")
FRIDA = Path("frida")


def log(msg):
    print(f"[PATCH] {msg}", flush=True)


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
    const-string v1, "Frida loaded"
    invoke-static {v0, v1}, Landroid/util/Log;->d(Ljava/lang/String;Ljava/lang/String;)I
    :try_end_shadow
    .catch Ljava/lang/Throwable; {:try_start_shadow .. :try_end_shadow} :catch_shadow
    goto :goto_shadow_done
    :catch_shadow
    move-exception v0
    const-string v0, "ShadowCloner"
    const-string v1, "Frida failed"
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
    # SHADOW CLONER: Load Frida Gadget
    invoke-static {}, Lorg/platform/app/ApplicationLoader;->shadowLoadFrida()V
'''

    content = content[:match2.end()] + call_code + content[match2.end():]
    smali_file.write_text(content)
    log("  ✅ Patched ApplicationLoader.smali")
    return True


def find_smali_dir_with_patch():
    """Find which smali_classesN folder has our patched ApplicationLoader."""
    for smali_dir in DECODED.glob("smali*"):
        candidate = smali_dir / "org" / "platform" / "app" / "ApplicationLoader.smali"
        if candidate.exists() and "shadowLoadFrida" in candidate.read_text():
            return smali_dir
    return None


def compile_smali_to_dex(smali_dir):
    """Compile using standalone smali.jar."""
    log(f"Compiling {smali_dir} → patched.dex using smali.jar...")
    dex_out = Path("patched_classes.dex")

    result = subprocess.run([
        "java", "-jar", "smali.jar",
        "assemble", str(smali_dir),
        "-o", str(dex_out)
    ], capture_output=True, text=True)

    if result.returncode != 0:
        log(f"  ❌ Compile failed:")
        log(result.stderr[:1000])
        return None

    log(f"  ✅ Created {dex_out.name} ({dex_out.stat().st_size} bytes)")
    return dex_out


def determine_dex_name(smali_dir):
    """Figure out the dex name based on the smali folder name."""
    name = smali_dir.name  # e.g., "smali_classes3" or "smali"
    if name == "smali":
        return "classes.dex"
    elif name.startswith("smali_classes"):
        num = name.replace("smali_classes", "")
        return f"classes{num}.dex"
    return "classes.dex"


def inject_into_apk(dex_file, dex_name):
    log(f"Injecting {dex_name} + Frida into original base.apk...")
    shutil.copy("base.apk", "1xbet_patched.apk")

    with zipfile.ZipFile("1xbet_patched.apk", "a") as zf:
        # 1. Replace the target classesN.dex
        log(f"  Replacing {dex_name}...")
        with open(dex_file, "rb") as f:
            dex_data = f.read()
        zf.writestr(dex_name, dex_data)

        # 2. Add Frida gadget
        log("  Adding libfrida-gadget.so...")
        zf.write(FRIDA / "libfrida-gadget.so", "lib/armeabi-v7a/libfrida-gadget.so")

        # 3. Add Frida script + config
        log("  Adding frida_script.js + config...")
        zf.write(FRIDA / "frida_script.js", "assets/frida_script.js")
        zf.write(FRIDA / "libfrida-gadget.config.so", "assets/libfrida-gadget.config.so")

        # 4. Add split native libs
        log("  Adding split native libs...")
        with zipfile.ZipFile("split_config.armeabi_v7a.apk") as split:
            for entry in split.namelist():
                if entry.startswith("lib/"):
                    try:
                        with split.open(entry) as src:
                            zf.writestr(entry, src.read())
                        log(f"    → {entry}")
                    except Exception as e:
                        log(f"    ⚠️ {entry}: {e}")

    log(f"✅ APK created: 1xbet_patched.apk ({Path('1xbet_patched.apk').stat().st_size} bytes)")
    return True


def main():
    log("=" * 60)
    log("  IN-PLACE APK PATCH (standalone smali.jar)")
    log("=" * 60)

    if not DECODED.exists():
        log("❌ base_decoded not found")
        return 1

    # Check smali.jar exists
    if not Path("smali.jar").exists():
        log("❌ smali.jar not found — download it first")
        return 1

    try:
        if not patch_application_smali():
            return 1

        patched_smali_dir = find_smali_dir_with_patch()
        if not patched_smali_dir:
            log("❌ Could not find patched smali folder")
            return 1

        log(f"Found patched smali: {patched_smali_dir}")
        dex_name = determine_dex_name(patched_smali_dir)
        log(f"Target dex name: {dex_name}")

        dex_file = compile_smali_to_dex(patched_smali_dir)
        if not dex_file:
            return 1

        if not inject_into_apk(dex_file, dex_name):
            return 1
    except Exception as e:
        log(f"❌ {e}")
        import traceback
        traceback.print_exc()
        return 1

    log("=" * 60)
    log("  ✅ PATCH COMPLETE")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())
