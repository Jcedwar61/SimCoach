"""Set SimCoach's version everywhere it appears, before building a release:

    python tools/installer/set_version.py 6.4

- sim_coach.py               APP_VERSION (window title, header, --version, update check)
- README.md                  "(Windows Installer, vX)" on the download link
The installer takes its version (wizard title, Settings > Apps, file properties) from APP_VERSION when
tools/installer/build_installer.sh builds it.
"""
import os
import re
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
    sub("sim_coach.py", r'^APP_VERSION = "[^"]*"(?=\r?$)', f'APP_VERSION = "{v}"')
    sub("README.md", r"\(Windows Installer, v[0-9.]+\)", f"(Windows Installer, v{v})")
    print("Now add a \"What's new\" section to README.md and run tools/installer/build_installer.sh")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
