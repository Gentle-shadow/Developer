#!/usr/bin/env python3
import os, shutil, subprocess, zipfile, re, xml.etree.ElementTree as ET
from pathlib import Path

DECODED = Path("base_decoded")
FRIDA = Path("frida")

def log(msg): print(f"[PATCH] {msg}", flush=True)

def find_application_smali():
    manifest_path = DECODED / "AndroidManifest.xml"
    if not manifest_path.exists(): return None
    try:
        root = ET.parse(manifest_path).getroot()
        ns = "{http://schemas.android.com/apk/res/android}"
        app = root.find("application")
        if app is None: return None
        cls = app.get(f"{ns}name")
        if not cls: return None
        rel = cls.replace('.', '/') + ".smali"
        for d in DECODED.glob("smali*"):
            cand = d / rel
            if cand.exists(): return cand
        return None
    except: return None

def patch_smali(f):
    content = f.read_text()
    if "shadowLoadFrida" in content: return True
    
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
    match = re.search(r'(\.method (?:public|protected)(?: final)? onCreate\(\)V)', content)
    if not match: return False
    content = content[:match.start()] + helper + content[match.start():]
    
    match2 = re.search(r'(\.method (?:public|protected)(?: final)? onCreate\(\)V\s*\n\s*\.registers \d+)', content)
    if not match2: return False
        
    # 🔥 THE FIX: Use forward slashes (/) instead of dots (.)
    actual_class = f.relative_to(DECODED).with_suffix('').as_posix()
    call = f'\n    invoke-static {{}}, L{actual_class};->shadowLoadFrida()V\n'
    
    content = content[:match2.end()] + call + content[match2.end():]
    f.write_text(content)
    return True

def rebuild():
    log("Rebuilding with apktool...")
    r = subprocess.run(["java", "-jar", "apktool.jar", "b", str(DECODED), "-o", "unsigned.apk"], capture_output=True, text=True)
    if r.returncode != 0:
        log(f"❌ Build failed:\n{r.stderr[:1000]}")
        return False
    return True

def inject():
    log("Injecting Frida files...")
    with zipfile.ZipFile("unsigned.apk", "r") as zin, zipfile.ZipFile("1xbet_patched.apk", "w") as zout:
        for item in zin.infolist(): zout.writestr(item, zin.read(item.filename))
        if (FRIDA / "libfrida-gadget.so").exists(): zout.write(FRIDA / "libfrida-gadget.so", "lib/armeabi-v7a/libfrida-gadget.so")
        if (FRIDA / "frida_script.js").exists(): zout.write(FRIDA / "frida_script.js", "assets/frida_script.js")
        if (FRIDA / "libfrida-gadget.config.so").exists(): zout.write(FRIDA / "libfrida-gadget.config.so", "assets/libfrida-gadget.config.so")
    return True

def main():
    if not DECODED.exists(): log("❌ base_decoded missing"); return 1
    f = find_application_smali()
    if not f: log("❌ Application smali not found"); return 1
    if not patch_smali(f): log("❌ Patch failed"); return 1
    if not rebuild(): return 1
    if not inject(): return 1
    log("✅ PATCH COMPLETE")
    return 0

if __name__ == "__main__": exit(main())
