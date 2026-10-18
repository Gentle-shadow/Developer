#!/usr/bin/env python3
import os, shutil, subprocess, zipfile, re, xml.etree.ElementTree as ET
from pathlib import Path

DECODED = Path("base_decoded")
FRIDA = Path("frida")

def log(msg): print(f"[PATCH] {msg}", flush=True)

def find_application_smali():
    manifest_path = DECODED / "AndroidManifest.xml"
    if not manifest_path.exists():
        log("  ❌ AndroidManifest.xml missing")
        return None
    try:
        root = ET.parse(manifest_path).getroot()
        ns = "{http://schemas.android.com/apk/res/android}"
        app = root.find("application")
        if app is None:
            log("  ❌ No <application> tag")
            return None
        cls = app.get(f"{ns}name")
        if not cls:
            log("  ❌ No android:name")
            return None
        log(f"  Found Application class: {cls}")
        rel = cls.replace('.', '/') + ".smali"
        for d in DECODED.glob("smali*"):
            cand = d / rel
            if cand.exists():
                log(f"  Found smali: {cand}")
                return cand
        log(f"  ❌ smali not found for {cls}")
        return None
    except Exception as e:
        log(f"  ❌ Error: {e}")
        return None

def patch_smali(f):
    log(f"Patching {f.name}...")
    content = f.read_text()
    
    if "shadowLoadFrida" in content:
        log("  Already patched")
        return True

    # The helper method
    helper = '''
.method public static shadowLoadFrida()V
    .registers 2
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

    # Find onCreate (with any combination of public/final/protected)
    match = re.search(r'(\.method\s+(?:public|protected)(?:\s+final)?\s+onCreate\(\)V)', content)
    if not match:
        log("  ❌ onCreate()V not found")
        return False

    log(f"  Found onCreate at position {match.start()}")
    
    # Insert helper BEFORE onCreate
    content = content[:match.start()] + helper + content[match.start():]

    # Re-find onCreate AFTER helper insertion
    match2 = re.search(r'(\.method\s+(?:public|protected)(?:\s+final)?\s+onCreate\(\)V)', content)
    if not match2:
        log("  ❌ Could not re-find onCreate")
        return False

    # Find the .registers or .locals line after the method declaration
    after_match = re.search(
        r'(\.method\s+(?:public|protected)(?:\s+final)?\s+onCreate\(\)V\s*\n\s*(?:\.registers|\.locals)\s+\d+)',
        content
    )
    if not after_match:
        log("  ❌ Could not find .registers/.locals after onCreate")
        # Show what's actually there
        snippet = content[match2.start():match2.start()+200]
        log(f"  onCreate starts with:\n{snippet}")
        return False

    log(f"  Found .registers at position {after_match.end()}")

    # Build the call using FORWARD SLASHES
    actual_class = f.relative_to(DECODED).with_suffix('').as_posix()
    call = f'\n    invoke-static {{}}, L{actual_class};->shadowLoadFrida()V\n'
    log(f"  Injecting: invoke-static {{}}, L{actual_class};->shadowLoadFrida()V")

    content = content[:after_match.end()] + call + content[after_match.end():]
    f.write_text(content)
    log("  ✅ Patched successfully")
    return True

def rebuild():
    log("Rebuilding with apktool...")
    r = subprocess.run(
        ["java", "-jar", "apktool.jar", "b", str(DECODED), "-o", "unsigned.apk"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        log(f"  ❌ Build failed:\n{r.stderr[:2000]}")
        return False
    log("  ✅ Rebuilt")
    return True

def inject():
    log("Injecting Frida files...")
    with zipfile.ZipFile("unsigned.apk", "r") as zin, zipfile.ZipFile("1xbet_patched.apk", "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        
        if (FRIDA / "libfrida-gadget.so").exists():
            zout.write(FRIDA / "libfrida-gadget.so", "lib/armeabi-v7a/libfrida-gadget.so")
            log("  Added libfrida-gadget.so")
        if (FRIDA / "frida_script.js").exists():
            zout.write(FRIDA / "frida_script.js", "assets/frida_script.js")
            log("  Added frida_script.js")
        if (FRIDA / "libfrida-gadget.config.so").exists():
            zout.write(FRIDA / "libfrida-gadget.config.so", "assets/libfrida-gadget.config.so")
            log("  Added libfrida-gadget.config.so")
    log("  ✅ Files injected")
    return True

def main():
    if not DECODED.exists():
        log("❌ base_decoded missing")
        return 1

    f = find_application_smali()
    if not f:
        return 1

    if not patch_smali(f):
        return 1

    if not rebuild():
        return 1

    if not inject():
        return 1

    log("✅ PATCH COMPLETE")
    return 0

if __name__ == "__main__":
    exit(main())
