"""Write SimCoach's Assetto Corsa helper app (SimCoach Weather Link: CSP weather + setup link) from the copy built
into sim_coach.py, for people who want to put it into <AC>\\apps\\lua by hand. SimCoach installs it by itself.
    python tools/release/export_csp_app.py SIM_COACH_PY OUT_DIR
Reads the strings with ast (sim_coach.py isn't run)."""
import ast
import base64
import os
import sys


def main(src, out):
    tree = ast.parse(open(src, encoding="utf-8").read())
    vals = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("CSP_WEATHER_MANIFEST", "CSP_WEATHER_LUA", "CSP_WEATHER_ICON", "CSP_WEATHER_APP_DIR"):
                vals[name] = ast.literal_eval(node.value)
    d = os.path.join(out, vals["CSP_WEATHER_APP_DIR"])
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "manifest.ini"), "w", encoding="utf-8", newline="").write(vals["CSP_WEATHER_MANIFEST"])
    open(os.path.join(d, "SimCoachWeather.lua"), "w", encoding="utf-8", newline="").write(vals["CSP_WEATHER_LUA"])
    open(os.path.join(d, "icon.png"), "wb").write(base64.b64decode("".join(vals["CSP_WEATHER_ICON"].split())))
    print(d)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
