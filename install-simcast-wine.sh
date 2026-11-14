#!/usr/bin/env bash
# SimCast for Linux and Steam Deck: install SimCast into the Wine/Proton prefix your sim runs in, and make a
# launcher that starts it there.
#
# Sims share their live data inside their own Wine prefix, so SimCast has to run in the same prefix, with the
# same Proton, as the game. This script finds both from the game's Steam app id, opens the normal SimCast setup
# wizard there (the same one as on Windows), and writes ~/.local/bin/simcast-<game>.sh plus a menu entry.
# Start the game first, then SimCast.
#
#   ./install-simcast-wine.sh --game lmu                  a known sim (see --list)
#   ./install-simcast-wine.sh --appid 2399420             any Steam game by app id
#   ./install-simcast-wine.sh --prefix ~/.wine            a plain Wine prefix (uses the 'wine' on your PATH)
# Options: --setup PATH (SimCast-Setup.exe; default: next to this script, else downloaded), --wine PATH,
#          --name NAME (for the launcher), --silent (no wizard: install with the default choices), --list
set -euo pipefail

declare -A GAMES=(
  [ac]=244210 [acc]=805550 [acevo]=3058630 [lmu]=2399420 [rf2]=365960 [ams2]=1066890 [raceroom]=211500
  [iracing]=266410 [f1-25]=3059520 [eawrc]=1849250 [dr2]=690790
)
declare -A GAME_NAMES=(
  [ac]="Assetto Corsa" [acc]="Assetto Corsa Competizione" [acevo]="Assetto Corsa EVO" [lmu]="Le Mans Ultimate"
  [rf2]="rFactor 2" [ams2]="Automobilista 2" [raceroom]="RaceRoom" [iracing]="iRacing" [f1-25]="F1 25"
  [eawrc]="EA SPORTS WRC" [dr2]="DiRT Rally 2.0"
)
SETUP_URL="https://github.com/Jcedwar61/SimCoach/raw/main/SimCast-Setup.exe"
HERE="$(cd "$(dirname "$0")" && pwd)"

say() { printf '%s\n' "$*"; }
die() { printf 'SimCast: %s\n' "$*" >&2; exit 1; }

APPID="" PREFIX="" WINE="" SETUP="" NAME="" SILENT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --game) g="${2:-}"; [ -n "${GAMES[$g]:-}" ] || die "unknown game '$g' (see --list)"; APPID="${GAMES[$g]}"; NAME="$g"; shift 2;;
    --appid) APPID="${2:-}"; NAME="${NAME:-app$APPID}"; shift 2;;
    --prefix) PREFIX="$(realpath -m "${2:-}")"; NAME="${NAME:-wine}"; shift 2;;
    --wine) WINE="${2:-}"; shift 2;;
    --setup) SETUP="$(realpath "${2:-}")"; shift 2;;
    --name) NAME="${2:-}"; shift 2;;
    --silent) SILENT=1; shift;;
    --list) for k in "${!GAMES[@]}"; do printf '  --game %-9s %-28s (app id %s)\n' "$k" "${GAME_NAMES[$k]}" "${GAMES[$k]}"; done | sort; exit 0;;
    -h|--help) sed -n '2,18p' "$0"; exit 0;;
    *) die "unknown option '$1' (try --help)";;
  esac
done
[ -n "$APPID$PREFIX" ] || die "say which game: --game NAME, --appid N or --prefix DIR (try --help)"

# ------------------------------------------------------------------ the Steam game's prefix and Proton
steam_libraries() {
  local roots=("$HOME/.steam/steam" "$HOME/.local/share/Steam" "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam")
  local r vdf
  for r in "${roots[@]}"; do
    [ -d "$r/steamapps" ] || continue
    echo "$r"
    vdf="$r/steamapps/libraryfolders.vdf"
    [ -f "$vdf" ] && grep -oP '"path"\s*"\K[^"]+' "$vdf"
  done | awk '!seen[$0]++'
}

PROTON=""
if [ -n "$APPID" ]; then
  COMPAT=""
  while read -r lib; do
    if [ -d "$lib/steamapps/compatdata/$APPID/pfx" ]; then COMPAT="$lib/steamapps/compatdata/$APPID"; break; fi
  done < <(steam_libraries)
  [ -n "$COMPAT" ] || die "no Proton prefix for app $APPID. Start the game once through Steam (with Proton), then run this again."
  PREFIX="$COMPAT/pfx"
  if [ -z "$WINE" ] && [ -f "$COMPAT/config_info" ]; then
    # config_info names files inside the Proton build the game last ran with
    PROTON="$(grep -m1 -oE '^/.*/(files|dist)/' "$COMPAT/config_info" | sed -E 's#/(files|dist)/$##' || true)"
  fi
  if [ -z "$WINE" ] && [ -n "$PROTON" ]; then
    for w in "$PROTON/files/bin/wine64" "$PROTON/files/bin/wine" "$PROTON/dist/bin/wine64" "$PROTON/dist/bin/wine"; do
      [ -x "$w" ] && { WINE="$w"; break; }
    done
  fi
fi
WINE="${WINE:-$(command -v wine64 || command -v wine || true)}"
[ -n "$WINE" ] && [ -x "$WINE" ] || die "no Wine found (install wine, or pass --wine PATH)"
[ -d "$PREFIX" ] || die "the prefix $PREFIX doesn't exist"

ENVV=(WINEPREFIX="$PREFIX" WINEDEBUG=-all)
if [ -n "$PROTON" ]; then
  LIBS="$PROTON/files/lib64:$PROTON/files/lib:$PROTON/dist/lib64:$PROTON/dist/lib"
  ENVV+=(LD_LIBRARY_PATH="$LIBS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" WINESERVER="$(dirname "$WINE")/wineserver")
fi

say "Game prefix: $PREFIX"
say "Wine:        $WINE${PROTON:+  (Proton: $(basename "$PROTON"))}"

# ------------------------------------------------------------------ the installer
if [ -z "$SETUP" ]; then
  if [ -f "$HERE/SimCast-Setup.exe" ]; then
    SETUP="$HERE/SimCast-Setup.exe"
  else
    SETUP="$(mktemp -d)/SimCast-Setup.exe"
    say "Downloading SimCast-Setup.exe ..."
    curl -fL --retry 3 -o "$SETUP" "$SETUP_URL" || die "couldn't download $SETUP_URL (pass --setup PATH)"
  fi
fi
[ -f "$SETUP" ] || die "$SETUP not found"

if [ -n "$SILENT" ]; then
  say "Installing SimCast into the prefix (it downloads Python and SimCast's packages: a few minutes) ..."
  env "${ENVV[@]}" "$WINE" "$SETUP" /S || die "the installer didn't finish"
else
  say "Opening the SimCast setup wizard. Click through it as on Windows (untick 'Start SimCast' on the last"
  say "page: start it later with the launcher this script makes) ..."
  env "${ENVV[@]}" "$WINE" "$SETUP" || die "the setup wizard was closed before it finished"
fi

EXE="$(ls -d "$PREFIX"/drive_c/users/*/AppData/Local/Programs/SimCast/SimCast.exe 2>/dev/null | head -1 || true)"
[ -n "$EXE" ] || die "SimCast.exe isn't in the prefix after installing; see install.log in the prefix's SimCast folder"
ICON="$(dirname "$EXE")/simcast/assets/icon-256.png"

# ------------------------------------------------------------------ the launcher
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
LAUNCH="$HOME/.local/bin/simcast-$NAME.sh"
{
  echo '#!/usr/bin/env bash'
  echo "# Starts SimCast in the same Wine/Proton prefix as ${GAME_NAMES[$NAME]:-the game}, so it can read the game's live data."
  echo "# Made by install-simcast-wine.sh. Start the game first."
  printf 'export %q\n' "${ENVV[@]}"
  printf 'exec %q %q "$@"\n' "$WINE" "$EXE"
} > "$LAUNCH"
chmod +x "$LAUNCH"
cat > "$HOME/.local/share/applications/simcast-$NAME.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=SimCast (${GAME_NAMES[$NAME]:-$NAME})
Comment=Live TV-style race commentary
Exec=$LAUNCH
Icon=$ICON
Categories=Game;
DESK

say ""
say "SimCast is installed."
say "  Start ${GAME_NAMES[$NAME]:-the game}, then run: $LAUNCH"
say "  (or 'SimCast (${GAME_NAMES[$NAME]:-$NAME})' in your applications menu)."
[ -n "$APPID" ] && say "  Steam Deck: add $LAUNCH to Steam as a non-Steam game to start it from Game Mode."
