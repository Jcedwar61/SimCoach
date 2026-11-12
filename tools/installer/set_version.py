"""Set SimCoach's version everywhere it appears, before building a release:

    python tools/installer/set_version.py 6.4

- sim_coach.py               APP_VERSION (window title, header, --version, update check)
- installer-source/install.ps1  DisplayVersion (Settings > Apps)
- installer-source/rsrc_windows_amd64.syso  the installer's Windows version info
- README.md                  "(Windows Installer, vX)" on the download link
Then rebuild the installer with tools/installer/build_installer.sh.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def sub(path, pattern, repl):
    p = os.path.join(REPO, path)
    s = open(p, encoding="utf-8", newline="").read()
    s2, n = re.subn(pattern, repl, s, count=1, flags=re.MULTILINE)
    if n != 1:
        sys.exit(f"couldn't find the version in {path}")
    open(p, "w", encoding="utf-8", newline="").write(s2)
    print(f"updated {path}")


def main(v):
    if not re.fullmatch(r"\d+(\.\d+){0,3}", v):
        sys.exit("version looks like 6.4 or 6.4.1")
    sub("sim_coach.py", r'^APP_VERSION = "[^"]*"$', f'APP_VERSION = "{v}"')
    sub("installer-source/install.ps1", r"(DisplayVersion\s*=\s*)'[^']*'", rf"\g<1>'{v}'")
    sub("README.md", r"\(Windows Installer, v[0-9.]+\)", f"(Windows Installer, v{v})")
    subprocess.check_call([sys.executable, os.path.join(HERE, "make_syso.py"), os.path.join(REPO, "SimCoach-Setup.exe"),
                           os.path.join(REPO, "installer-source", "rsrc_windows_amd64.syso"), v])
    print("Now add a \"What's new\" section to README.md and run tools/installer/build_installer.sh")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
