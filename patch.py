#!/usr/bin/env python3
"""
patch.py — In-place APK patch. Uses apktool for rebuild to avoid smali.jar dependencies.
Finds the real Application class from AndroidManifest.xml.
"""
import os
import shutil
import subprocess
import zipfile
import re
import xml.etree.ElementTree as ET
from pathlib import Path

DECODED = Path("base_decoded")
FRIDA = Path("frida")

def log(msg):
    print(f"[PATCH] {msg}", flush=True)

def find_application_smali():
    log("Reading AndroidManifest.xml to find Application class...")
    manifest_path = DECODED / "AndroidManifest.xml"
    if not manifest_path.exists():
        log("  ❌ AndroidManifest.xml not found")
        return None

    try:
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        android_ns = "{http://schemas.android.com/apk/res/android}"
        
        # Find <application> tag and get android:name
        app_tag = root.find("application")
        if app_tag is None:
            log("  ❌ <application> tag not found")
            return None
            
        app_class = app_tag.get(f"{android_ns}name")
        if not app_class:
            log("  ❌ No android:name in <application>")
            return None
            
        log(f"  Found Application class: {app_class}")
        
        # Convert class name to smali path (e.g. org.platform.app.XbetApp -> org/platform/app/XbetApp.smali)
        smali_rel_path = app_class.replace('.', '/') + ".smali"
        
        # Search for this file in all smali folders
        for smali_dir in DECODED.glob("smali*"):
            candidate = smali_dir / smali_rel_path
            if candidate.exists():
                log(f"  Found smali file: {candidate}")
                return candidate
                
        log(f"  ❌ smali file not found for {app_class}")
        return None
    except Exception as e:
        log(f"  ❌ Error parsing manifest: {e}")
        return None

def patch_application_smali(smali_file):
    log(f"Patching {smali_file.name}...")
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

    # Find onCreate (matches public, protected, final)
    match = re.search(r'(\.method (?:public|protected)(?: final)? onCreate\(\)V)', content)
    if not match:
        log("  ❌ onCreate()V not found. Cannot inject load call.")
        return False

    # Inject helper method BEFORE onCreate
    content = content[:match.start()] + helper_method + content[match.start():]

    # Now find onCreate again (after helper injection) and add the load call
    match2 = re.search(r'(\.method (?:public|protected)(?: final)? onCreate\(\)V\s*\n\s*\.locals \d+)', content)
    if not match2:
        log("  ❌ Could not re-find onCreate")
        return False

    call_code = '''
    # SHADOW CLONER: Load Frida Gadget
    invoke-static {}, Lshadow/Loader;->shadowLoadFrida()V
'''
    # Replace class name in the call with the actual class
    actual_class_smali = smali_file.relative_to(DECODED).with_suffix('').as_posix().replace('/', '.')
    call_code = call_code.replace("Lshadow/Loader;", f"L{actual_class_smali};")

    content = content[:match2.end()] + call_code + content[match2.end():]
    smali_file.write_text(content)
    log("  ✅ Patched successfully")
    return True

def inject_into_apk():
    log("Building patched APK from decoded sources...")
    
    if not (DECODED / "apktool.yml").exists():
        log("  ❌ apktool.yml not found. Did decode fail?")
        return False

    # Use apktool to rebuild (avoids smali.jar path issues)
    log("  Running apktool b...")
    result = subprocess.run([
        "java", "-jar", "apktool.jar", "b", str(DECODED), "-o", "shadow_patched.apk"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        log(f"  ❌ apktool build failed:\n{result.stderr[:1000]}")
        return False
        
    log("  ✅ APK rebuilt")
    
    # Now inject Frida files into the rebuilt APK
    log("Injecting Frida Gadget and Script...")
    temp_apk = Path("shadow_patched_frida.apk")
    shutil.move("shadow_patched.apk", temp_apk)
    
    with zipfile.ZipFile(temp_apk, "r") as zin, zipfile.ZipFile("shadow_final_unsigned.apk", "w") as zout:
        # Copy all original files, EXCEPT if they conflict with Frida files
        for item in zin.infolist():
            data = zin.read(item.filename)
            zout.writestr(item, data)
            
        # Add Frida files
        if (FRIDA / "libfrida-gadget.so").exists():
            zout.write(FRIDA / "libfrida-gadget.so", "lib/armeabi-v7a/libfrida-gadget.so")
            log("  Added libfrida-gadget.so")
        
        if (FRIDA / "frida_script.js").exists():
            zout.write(FRIDA / "frida_script.js", "assets/frida_script.js")
            log("  Added frida_script.js")
            
        if (FRIDA / "libfrida-gadget.config.so").exists():
            zout.write(FRIDA / "libfrida-gadget.config.so", "assets/libfrida-gadget.config.so")
            log("  Added libfrida-gadget.config.so")
            
    temp_apk.unlink()
    shutil.move("shadow_final_unsigned.apk", "1xbet_patched.apk")
    log("✅ APK created: 1xbet_patched.apk")
    return True

def main():
    log("=" * 60)
    log("  IN-PLACE APK PATCH (Bulletproof)")
    log("=" * 60)

    if not DECODED.exists():
        log("❌ base_decoded not found")
        return 1

    smali_file = find_application_smali()
    if not smali_file:
        return 1
        
    if not patch_application_smali(smali_file):
        return 1
        
    if not inject_into_apk():
        return 1

    log("=" * 60)
    log("  ✅ PATCH COMPLETE")
    log("=" * 60)
    return 0

if __name__ == "__main__":
    exit(main())
