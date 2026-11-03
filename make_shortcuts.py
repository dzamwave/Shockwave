import os
import subprocess
from pathlib import Path

root = str(Path.cwd().resolve())
candidate_onedir = os.path.join(root, "dist", "Shockwave", "Shockwave.exe")
candidate_onefile = os.path.join(root, "dist", "Shockwave.exe")
exe = candidate_onedir if os.path.exists(candidate_onedir) else candidate_onefile
ico = os.path.join(root, "icons", "icon.ico,0")
s1_path = os.path.join(root, "Shockwave.lnk")
s2_path = os.path.join(root, "Shockwave-Widget.lnk")

if os.path.exists(s2_path):
    try:
        os.remove(s2_path)
    except Exception:
        pass

vbs_content = f"""
Set oWS = CreateObject("WScript.Shell")
Set oLink1 = oWS.CreateShortcut("{s1_path}")
oLink1.TargetPath = "{exe}"
oLink1.WorkingDirectory = "{root}"
oLink1.IconLocation = "{ico}"
oLink1.Save
"""

vbs_file = Path("make_shortcuts.vbs")
vbs_file.write_text(vbs_content, encoding="utf-8")
subprocess.run(["cscript", "//nologo", str(vbs_file)], check=True)
vbs_file.unlink()
print("Shortcuts successfully created!")
