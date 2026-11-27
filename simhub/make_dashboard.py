"""Writes the SimCoach dashboard for SimHub's Dash Studio: simhub/dashboard/SimCoach/SimCoach.djson (+ .metadata).

    python simhub/make_dashboard.py

Every value comes from the SimCoach plugin's SimCoach.* properties (simhub/plugin/SimCoachPlugin.cs). Edit this file
rather than the .djson, so the dashboard can be regenerated; it's also fine to open the result in Dash Studio and
change it by hand. 1280 x 720, scales to any screen. Four screens:

  0 Waiting    (idle)    SimCoach's status, today's goal and the target lap while no sim is running
  1 Coach      (in game) delta, the coach's last call, focus corners, goal, pace, laps, race info, status lights
  2 Corners    (in game) where the time goes: worst corners on the last lap, recent laps, goal progress
  3 Controls   (in game) touch buttons: repeat, mute, braking tones, overlay, setup sheet, data capture
"""
import json
import os
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "dashboard", "SimCoach")
W, H = 1280, 720
NS = uuid.UUID("5c0ac4e1-5e1a-4b1d-9c55-000000000001")

# SimCoach's own colours (the app and its phone page)
BG, PANEL, LINE = "#FF0B0F14", "#FF121821", "#FF263142"
FG, MUT, FAINT = "#FFE6EDF3", "#FF8D99A8", "#FF4A5566"
GOOD, BAD, TIP, ACC, WARN = "#FF34D399", "#FFF87171", "#FFFCD34D", "#FF3D8BFD", "#FFF59E0B"
SANS, MONO = "Roboto", "Cousine"
P = "SimCoach."
M = "SimHub.Plugins.OutputPlugins.GraphicalDash.Models."

_names = {}


def _name(base):
    _names[base] = _names.get(base, 0) + 1
    return base if _names[base] == 1 else f"{base}{_names[base]}"


def ncalc(expr):
    return {"Formula": {"Expression": expr}, "Mode": 2}


def js(body):
    return {"Formula": {"JSExt": 0, "Interpreter": 1, "Expression": body}, "Mode": 2}


def prop(name):
    return ncalc(f"[{P}{name}]")


def _base(kind, name, x, y, w, h, bindings=None, **extra):
    d = {"$type": f"{M}{kind}, SimHub.Plugins", **extra,
         "Height": float(h), "Left": float(x), "Top": float(y), "Visible": True, "BlinkPhasisInverted": False,
         "Width": float(w), "Name": _name(name)}
    if bindings:
        d["Bindings"] = bindings
    return d


def rect(name, x, y, w, h, color=PANEL, radius=10, border=None, bindings=None):
    bs = {"RadiusTopLeft": radius, "RadiusTopRight": radius, "RadiusBottomLeft": radius, "RadiusBottomRight": radius}
    if border:
        bs.update(BorderTop=1, BorderBottom=1, BorderLeft=1, BorderRight=1, BorderColor=border)
    return _base("RectangleItem", name, x, y, w, h, bindings, IsRectangleItem=True, BackgroundColor=color,
                 BorderStyle=bs)


def text(name, x, y, w, h, value="", size=20, color=FG, bold=False, align="left", font=SANS, valign="center",
         bindings=None, wrap=False):
    return _base("TextItem", name, x, y, w, h, bindings, IsTextItem=True, Font=font, TextWrapping=2 if wrap else 1,
                 FontWeight="Bold" if bold else "Normal", FontSize=float(size), Text=value, TextColor=color,
                 HorizontalAlignment={"left": 0, "center": 1, "right": 2}[align],
                 VerticalAlignment={"top": 0, "center": 1, "bottom": 2}[valign], BackgroundColor="#00FFFFFF")


def button(name, x, y, w, h, action=None, behavior=None):
    """A transparent touch area over whatever is drawn under it: runs a SimHub action, or changes screen."""
    d = _base("ButtonItem", name, x, y, w, h, None, AutoSize=False, SimulatedKey=0,
              SimulatedKeyV2={"Win": False, "Ctrl": False, "Alt": False, "Shift": False}, SimulateKey=True,
              TriggerAction=action or "None", TriggerSimHubInputName="MyButton" if action else "",
              TriggerControlMapperRoleName="", ButtonStyle=0, IsEnabled=True, DisabledOpacity=50,
              PressedOpacity=60, ChildsPositioning=0, ChildsPositioningAlignment=0, GroupPadding={},
              ChildsMargin={}, ChildAlignmentHorizontal=0, ChildAlignmentVertical=0, BackgroundColor="#00FFFFFF")
    if behavior:
        d["Behavior"] = {"$type": f"SimHub.Plugins.OutputPlugins.GraphicalDash.Behaviors.Buttons.{behavior}, SimHub.Plugins"}
    return d


def screen(name, items, ingame=True, idle=False):
    return {"RenderingSkip": 0, "Name": name, "InGameScreen": ingame, "IdleScreen": idle, "PitScreen": False,
            "ScreenId": str(uuid.uuid5(NS, name)), "AllowOverlays": True, "IsForegroundLayer": False,
            "IsOverlayLayer": False, "OverlayTriggerExpression": {"Expression": ""},
            "ScreenEnabledExpression": {"Expression": ""}, "OverlayMaxDuration": 0, "OverlayMinDuration": 0,
            "IsBackgroundLayer": False, "BackgroundColor": BG, "Items": items, "MinimumRefreshIntervalMS": 0.0}


# ---- shared pieces ----------------------------------------------------------------------------------------------
def visible(expr):
    return {"Visible": ncalc(expr)}


def pill(label, x, y, w, color, when):
    """A small status light: shown only while `when` is true."""
    return [rect("Pill", x, y, w, 34, color, radius=17, bindings=visible(when)),
            text("PillText", x, y, w, 34, label, 15, BG, bold=True, align="center", bindings=visible(when))]


def header(title):
    items = [rect("HeaderBar", 0, 0, W, 56, PANEL, radius=0),
             text("Brand", 20, 0, 200, 56, "SIMCOACH", 22, ACC, bold=True),
             text("ScreenTitle", 190, 0, 300, 56, title, 18, MUT)]
    x = W - 20
    for label, w, color, when in (("ON AIR", 100, GOOD, f"[{P}Talking]"),
                                  ("LISTENING", 120, ACC, f"[{P}Listening]"),
                                  ("MUTED", 90, BAD, f"[{P}Muted]"),
                                  ("TONES OFF", 116, WARN, f"[{P}Connected] and not [{P}BrakeTonesOn]")):
        x -= w + 8
        items += pill(label, x, 11, w, color, when)
        if label == "ON AIR":             # same slot: never both at once
            items += pill("OFFLINE", x, 11, w, FAINT, f"not [{P}Connected]")
    return items


def nav(prev_label, next_label):
    y = H - 52
    return [rect("NavBar", 0, y, W, 52, PANEL, radius=0),
            text("NavPrev", 20, y, 400, 52, "◀  " + prev_label, 17, MUT),
            text("NavNext", W - 420, y, 400, 52, next_label + "  ▶", 17, MUT, align="right"),
            text("Session", 420, y, W - 840, 52, "", 15, MUT, align="center", bindings={"Text": js(
                f"if (!$prop('{P}Connected')) return 'SimCoach not running';\n"
                f"const t = $prop('{P}Track');\n"
                f"return t ? ($prop('{P}Sim') + '  ·  ' + t + '  ·  ' + $prop('{P}Car')) : ($prop('{P}Status') || 'Waiting for a sim');")}),
            button("PrevScreen", 0, y, 420, 52, behavior="PreviousScreenBehavior"),
            button("NextScreen", W - 420, y, 420, 52, behavior="NextScreenBehavior")]


def card(label, x, y, w, h, value_binding, size=34, color=FG, font=MONO, sub=None):
    items = [rect("Card", x, y, w, h, PANEL, border=LINE),
             text("CardLabel", x + 16, y + 8, w - 32, 22, label.upper(), 13, MUT, bold=True, valign="top"),
             text("CardValue", x + 16, y + 30, w - 32, h - (60 if sub else 38), "–", size, color, bold=True, font=font,
                  bindings={"Text": value_binding})]
    if sub is not None:
        items.append(text("CardSub", x + 16, y + h - 32, w - 32, 24, "", 14, MUT, bindings={"Text": sub}))
    return items


def or_dash(name):
    return ncalc(f"isnull([{P}{name}], '–')")


# ---- screen 0: waiting -----------------------------------------------------------------------------------------
def waiting():
    cx = 140
    return [
        text("Logo", 0, 120, W, 90, "SIMCOACH", 72, ACC, bold=True, align="center"),
        text("Tagline", 0, 205, W, 40, "Drive. Hear where the time is. Fix one corner at a time.", 20, MUT,
             align="center"),
        rect("StatusCard", cx, 280, W - 2 * cx, 250, PANEL, border=LINE),
        text("StatusHead", cx + 30, 300, W - 2 * cx - 60, 44, "", 26, FG, bold=True, align="center", bindings={
            "Text": js(f"if (!$prop('{P}Connected')) return 'SimCoach is not running';\n"
                       f"if (!$prop('{P}Running')) return 'SimCoach is open: press Start coaching';\n"
                       f"return $prop('{P}Status') || 'Waiting for a sim…';"),
            "TextColor": ncalc(f"if([{P}Connected], '{GOOD}', '{BAD}')")}),
        text("StatusSub", cx + 30, 350, W - 2 * cx - 60, 40, "", 17, MUT, align="center", wrap=True, bindings={
            "Text": js(f"if (!$prop('{P}Connected')) return 'Start SimCoach 6.22 or later. Its Settings tab: Send coaching to SimHub dashboards.';\n"
                       f"const d = $prop('{P}Driver');\n"
                       f"return 'SimCoach ' + $prop('{P}Version') + (d ? '  ·  driver ' + d : '');")}),
        text("GoalIdle", cx + 30, 395, W - 2 * cx - 60, 60, "", 19, TIP, align="center", wrap=True, bindings={
            "Text": ncalc(f"isnull([{P}Goal], '')"), "Visible": ncalc(f"[{P}Connected]")}),
        text("TargetIdle", cx + 30, 460, W - 2 * cx - 60, 40, "", 18, FG, align="center", font=MONO, bindings={
            "Text": js(f"const t = $prop('{P}TargetLap'), b = $prop('{P}BestLap');\n"
                       f"if (!t && !b) return '';\n"
                       f"return (b ? 'Best ' + b : '') + (b && t ? '    ' : '') + (t ? 'Target ' + t : '');")}),
        text("IdleHint", 0, 600, W, 30,
             "Push-to-talk: map SimCoach.PushToTalk to a wheel button in SimHub › Controls and events", 15, FAINT,
             align="center"),
    ]


# ---- screen 1: coach --------------------------------------------------------------------------------------------
def coach():
    items = header("Coach")
    # delta: big number with a bar growing left (gaining, green) or right (losing, red) from the centre
    items += [rect("DeltaPanel", 20, 72, 600, 250, PANEL, border=LINE),
              text("DeltaLabel", 40, 82, 300, 24, "DELTA TO YOUR REFERENCE", 13, MUT, bold=True),
              text("Delta", 20, 100, 600, 160, "--.--", 120, FG, bold=True, align="center", font=MONO, bindings={
                  "Text": prop("DeltaText"),
                  "TextColor": ncalc(f"if(not [{P}DeltaValid], '{FAINT}', if(isnull([{P}Delta], 0) > 0, '{BAD}', '{GOOD}'))")}),
              rect("DeltaTrack", 40, 280, 560, 14, "#FF1B2330", radius=7),
              rect("DeltaMid", 318, 274, 4, 26, MUT, radius=1),
              rect("DeltaBar", 320, 280, 0, 14, GOOD, radius=7, bindings={
                  "Width": ncalc(f"min(abs(isnull([{P}Delta], 0)), 2) / 2 * 280"),
                  "Left": ncalc(f"if(isnull([{P}Delta], 0) < 0, 320 - min(abs([{P}Delta]), 2) / 2 * 280, 320)"),
                  "BackgroundColor": ncalc(f"if(isnull([{P}Delta], 0) > 0, '{BAD}', '{GOOD}')")}),
              text("DeltaScaleL", 40, 296, 100, 20, "-2.0", 12, FAINT, font=MONO),
              text("DeltaScaleR", 500, 296, 100, 20, "+2.0", 12, FAINT, align="right", font=MONO)]
    # the coach's last call, lit up while it's fresh
    items += [rect("CoachPanel", 640, 72, 620, 160, PANEL, border=LINE, bindings={
                  "BackgroundColor": ncalc(f"if([{P}CoachFresh], '#FF16263D', '{PANEL}')")}),
              rect("CoachAccent", 640, 72, 8, 160, ACC, radius=4, bindings=visible(f"[{P}CoachFresh]")),
              text("CoachLabel", 664, 82, 300, 24, "COACH", 13, MUT, bold=True),
              text("CoachAge", 960, 82, 280, 24, "", 13, FAINT, align="right", bindings={"Text": js(
                  f"const a = $prop('{P}CoachAge');\n"
                  f"if (a === null || a === undefined) return '';\n"
                  f"return a < 60 ? Math.round(a) + ' s ago' : Math.round(a / 60) + ' min ago';")}),
              text("Coach", 664, 106, 580, 120, "", 24, FG, valign="top", wrap=True, bindings={
                  "Text": ncalc(f"isnull([{P}Coach], 'Calls from the coach show here.')"),
                  "TextColor": ncalc(f"if([{P}CoachFresh], '{FG}', '{MUT}')")}),
              rect("FocusPanel", 640, 242, 620, 80, PANEL, border=LINE),
              text("FocusLabel", 664, 250, 300, 22, "FOCUS", 13, MUT, bold=True),
              text("FocusTurns", 960, 250, 280, 22, "", 14, TIP, bold=True, align="right", font=MONO, bindings={
                  "Text": js(f"const d = $prop('{P}Drill'); return d ? d : ($prop('{P}FocusTurns') || '');")}),
              text("Focus", 664, 270, 580, 50, "", 17, TIP, wrap=True, bindings={"Text": ncalc(f"isnull([{P}Focus], '–')")})]
    # goal + what the coach heard
    items += [rect("GoalPanel", 20, 334, 1240, 48, PANEL, border=LINE),
              text("Goal", 40, 334, 1200, 48, "", 17, TIP, wrap=True, bindings={"Text": js(
                  f"const h = $prop('{P}Heard');\n"
                  f"if (h && $prop('{P}HeardFresh')) return h;\n"
                  f"return $prop('{P}Goal') || 'No goal carried over from last session yet: finish a session and your worst corner becomes the next one.';"),
                  "TextColor": ncalc(f"if([{P}HeardFresh], '{ACC}', if(isnull([{P}Goal], '') = '', '{FAINT}', '{TIP}'))")})]
    # lap numbers
    y, cw, gap = 394, 196, 12
    cards = [("Lap", js(f"const l = $prop('{P}Lap'); return l ? String(l) : '–';"), FG, None),
             ("Last", or_dash("LastLap"), FG, None),
             ("Best", or_dash("BestLap"), GOOD, None),
             ("Theoretical", or_dash("TheoreticalBest"), ACC, None),
             ("Pace vs target", js(f"const p = $prop('{P}PacePercent'); return p ? p.toFixed(1) + '%' : '–';"), TIP,
              js(f"const t = $prop('{P}TargetLap'); return t ? 'target ' + t : 'no target here';")),
             ("Consistency", js(f"const c = $prop('{P}Consistency'); return c !== null && c !== undefined ? '±' + c.toFixed(2) + 's' : '–';"),
              FG, ncalc(f"isnull([{P}ConsistencyLabel], '')"))]
    for i, (label, b, col, sub) in enumerate(cards):
        items += card(label, 20 + i * (cw + gap), y, cw, 108, b, size=30, color=col, sub=sub)
    # pace bar: 100% = on the target, 110% or slower = empty
    items += [rect("PaceTrack", 20, 514, 1240, 10, "#FF1B2330", radius=5),
              rect("PaceBar", 20, 514, 0, 10, TIP, radius=5, bindings={
                  "Width": js(f"const p = $prop('{P}PacePercent');\n"
                             f"return p ? Math.max(0, Math.min(1, (110 - p) / 10)) * 1240 : 0;"),
                  "BackgroundColor": ncalc(f"if(isnull([{P}PacePercent], 200) <= 102, '{GOOD}', if(isnull([{P}PacePercent], 200) <= 105, '{TIP}', '{BAD}'))")})]
    # race row
    y, cw = 536, 240
    race = [("Position", js(f"const p = $prop('{P}Position'), n = $prop('{P}Cars'); return p ? 'P' + p + (n ? ' / ' + n : '') : '–';")),
            ("Gap ahead", js(f"const g = $prop('{P}GapAhead'); return g !== null && g !== undefined ? g.toFixed(1) + ' s' : '–';")),
            ("Gap behind", js(f"const g = $prop('{P}GapBehind'); return g !== null && g !== undefined ? g.toFixed(1) + ' s' : '–';")),
            ("Fuel", or_dash("Fuel")),
            ("Speed · gear", js(f"const s = $prop('{P}Speed'); return s !== null && s !== undefined ? s + ' · ' + ($prop('{P}Gear') || '') : '–';"))]
    for i, (label, b) in enumerate(race):
        items += card(label, 20 + i * (cw + 10), y, cw, 120, b, size=28,
                      sub=(js(f"const l = $prop('{P}FuelLaps'); return l !== null && l !== undefined ? 'about ' + l + ' laps left' : '';")
                           if label == "Fuel" else None))
    return items + nav("Controls", "Corners & laps")


# ---- screen 2: corners and laps -----------------------------------------------------------------------------------
def corners():
    items = header("Corners & laps")
    # worst corners on the last lap
    items += [rect("WorstPanel", 20, 72, 700, 432, PANEL, border=LINE),
              text("WorstLabel", 40, 82, 660, 26, "WHERE THE TIME WENT LAST LAP", 13, MUT, bold=True),
              text("WorstEmpty", 40, 140, 660, 80, "Corner losses show after your first full lap against a reference.",
                   18, FAINT, wrap=True, bindings=visible(f"[{P}WorstCount] = 0"))]
    for i in range(5):
        n, y = f"{P}Worst{i + 1}", 116 + i * 76
        has = f"isnull([{n}.Turn], 0) > 0"
        items += [rect("WorstRow", 36, y, 668, 66, "#FF0F141C", radius=8, bindings=visible(has)),
                  text("WorstTurn", 52, y, 90, 66, "", 28, FG, bold=True, font=MONO,
                       bindings={"Text": js(f"const t = $prop('{n}.Turn'); return t ? 'T' + t : '';"),
                                 "Visible": ncalc(has)}),
                  text("WorstLoss", 140, y + 4, 130, 34, "", 24, BAD, bold=True, font=MONO,
                       bindings={"Text": js(f"const l = $prop('{n}.Loss'); return l ? '+' + l.toFixed(2) + 's' : '';"),
                                 "Visible": ncalc(has)}),
                  rect("WorstBarTrack", 140, y + 44, 130, 8, "#FF1B2330", radius=4, bindings=visible(has)),
                  rect("WorstBar", 140, y + 44, 0, 8, BAD, radius=4, bindings={
                      "Width": js(f"const l = $prop('{n}.Loss'); return l ? Math.min(l, 1) * 130 : 0;"), "Visible": ncalc(has)}),
                  text("WorstIssue", 290, y, 400, 66, "", 17, FG, wrap=True, bindings={
                      "Text": ncalc(f"isnull([{n}.Issue], 'time lost here')"), "Visible": ncalc(has)})]
    # recent laps
    items += [rect("LapsPanel", 740, 72, 520, 432, PANEL, border=LINE),
              text("LapsLabel", 760, 82, 300, 26, "RECENT LAPS", 13, MUT, bold=True),
              text("LapsBest", 960, 82, 280, 26, "", 14, GOOD, align="right", font=MONO,
                   bindings={"Text": js(f"const b = $prop('{P}BestLap'); return b ? 'best ' + b : '';")})]
    for i in range(8):
        n, y = f"{P}Laps{i + 1}", 116 + i * 48
        has = f"isnull([{n}.Number], 0) > 0"
        items += [text("LapNo", 760, y, 70, 44, "", 18, MUT, font=MONO,
                       bindings={"Text": js(f"const n = $prop('{n}.Number'); return n ? 'L' + n : '';"), "Visible": ncalc(has)}),
                  text("LapTime", 830, y, 170, 44, "", 22, FG, bold=True, font=MONO,
                       bindings={"Text": ncalc(f"isnull([{n}.Time], '')"), "Visible": ncalc(has),
                                 "TextColor": ncalc(f"if(isnull([{n}.Gap], 1) = 0, '{GOOD}', '{FG}')")}),
                  text("LapGap", 1000, y, 140, 44, "", 18, MUT, align="right", font=MONO,
                       bindings={"Text": js(f"const g = $prop('{n}.Gap'); if (g === null || g === undefined) return ''; return g === 0 ? 'best' : '+' + g.toFixed(2);"),
                                 "Visible": ncalc(has)}),
                  text("LapFlag", 1150, y, 90, 44, "", 15, WARN, bold=True, align="right",
                       bindings={"Text": ncalc(f"isnull([{n}.Flag], '')"), "Visible": ncalc(has)})]
    # goals from last session
    items += [rect("GoalsPanel", 20, 516, 1240, 140, PANEL, border=LINE),
              text("GoalsLabel", 40, 524, 600, 26, "TODAY'S GOAL (THE CORNERS THAT COST YOU MOST LAST SESSION)", 13, MUT, bold=True),
              text("GoalsDone", 900, 524, 340, 26, "", 14, GOOD, bold=True, align="right",
                   bindings={"Text": js(f"const n = $prop('{P}GoalCount'), d = $prop('{P}GoalsDone'); return n ? d + ' of ' + n + ' done' : '';")}),
              text("GoalsEmpty", 40, 560, 1200, 80,
                   "No goal yet. When a session ends, its worst one or two corners become the goal for your next session here.",
                   17, FAINT, wrap=True, bindings=visible(f"isnull([{P}GoalCount], 0) = 0"))]
    for i in range(3):
        n, x = f"{P}Goals{i + 1}", 40 + i * 405
        has = f"isnull([{n}.Turn], 0) > 0"
        items += [rect("GoalChip", x, 560, 390, 80, "#FF0F141C", radius=8, border=LINE, bindings={
                      "Visible": ncalc(has), "BackgroundColor": ncalc(f"if([{n}.Done], '#FF0F2A20', '#FF0F141C')")}),
                  text("GoalText", x + 16, 560, 360, 80, "", 22, TIP, bold=True, font=MONO, bindings={
                      "Text": ncalc(f"isnull([{n}.Text], '')"), "Visible": ncalc(has),
                      "TextColor": ncalc(f"if([{n}.Done], '{GOOD}', if(isnull([{n}.Change], 0) < 0, '{FG}', '{TIP}'))")})]
    return items + nav("Coach", "Controls")


# ---- screen 3: controls ---------------------------------------------------------------------------------------------
def controls():
    items = header("Coach controls")
    pads = [("REPEAT", "Say the last call again", "Repeat", None, None),
            ("MUTE", "Coach quiet: answers only", "Mute",
             js(f"return $prop('{P}Muted') ? 'UNMUTE' : 'MUTE';"), f"[{P}Muted]"),
            ("BRAKING TONES", "Beeps before your focus corners", "BrakeTones",
             js(f"return $prop('{P}BrakeTonesOn') ? 'TONES ON' : 'TONES OFF';"), f"not [{P}BrakeTonesOn]"),
            ("OVERLAY", "Show / hide SimCoach's overlay", "Overlay", None, None),
            ("SETUP SHEET", "Show / hide the setup sheet", "SetupSheet", None, None),
            ("CAPTURE", "Start / stop a data capture", "Capture", None, None)]
    bw, bh = 400, 270
    for i, (label, sub, action, live_label, alert) in enumerate(pads):
        x, y = 20 + (i % 3) * (bw + 20), 76 + (i // 3) * (bh + 20)
        bg_bind = {"BackgroundColor": ncalc(f"if({alert}, '#FF3A1D1D', '{PANEL}')")} if alert else None
        items += [rect("Pad", x, y, bw, bh, PANEL, radius=16, border=LINE, bindings=bg_bind),
                  text("PadLabel", x, y + 70, bw, 70, label, 36, FG, bold=True, align="center",
                       bindings={"Text": live_label} if live_label else None),
                  text("PadSub", x + 20, y + 150, bw - 40, 50, sub, 17, MUT, align="center", wrap=True),
                  text("PadAction", x, y + bh - 44, bw, 30, f"SimCoach.{action}", 13, FAINT, align="center", font=MONO),
                  button(f"Btn{action}", x, y, bw, bh, action=f"SimCoach.{action}")]
    return items + nav("Corners & laps", "Coach")


def build():
    _names.clear()
    screens = [screen("Waiting", waiting(), ingame=False, idle=True), screen("Coach", coach()),
               screen("Corners", corners()), screen("Controls", controls())]
    dash = {"DashboardDebugManager": {}, "Version": 2, "Id": str(uuid.uuid5(NS, "SimCoach dashboard")),
            "BaseHeight": H, "BaseWidth": W, "BackgroundColor": BG, "Screens": screens, "SnapToGrid": False,
            "HideLabels": True, "ShowForeground": True, "ForegroundOpacity": 100.0, "ShowBackground": True,
            "BackgroundOpacity": 100.0, "ShowBoundingRectangles": False, "GridSize": 10, "Images": [],
            "Metadata": None, "ShowOnScreenControls": True, "IsOverlay": False, "EnableClickThroughOverlay": True,
            "EnableOnDashboardMessaging": True, "UseStrictJSIsolation": False, "UseStrictJSIsolationWarning": True}
    meta = {"ScreenCount": float(len(screens)), "InGameScreensIndexs": [1, 2, 3], "IdleScreensIndexs": [0],
            "MainPreviewIndex": 1, "IsOverlay": False, "OverlaySizeWarning": True, "MetadataVersion": 2.0,
            "EnableOnDashboardMessaging": True, "PitScreensIndexs": [], "SimHubVersion": "9.11.17",
            "Category": "SimCoach", "Title": "SimCoach",
            "Description": "Live coaching from SimCoach: delta, the coach's calls, focus corners, goals, pace, corner losses, laps and touch controls. Needs the SimCoach plugin.",
            "Author": "SimCoach", "Width": float(W), "Height": float(H), "DashboardVersion": "1.0"}
    dash["Metadata"] = meta
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "SimCoach.djson"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(dash, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT, "SimCoach.djson.metadata"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, indent=2)
    return dash


if __name__ == "__main__":
    d = build()
    n = sum(len(s["Items"]) for s in d["Screens"])
    print(f"Wrote {OUT} ({len(d['Screens'])} screens, {n} items)")
