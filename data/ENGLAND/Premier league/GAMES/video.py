#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Premier League — season table + ELO + all-time points (MP4).

Landscape 720p (1280x720), 16:9.

Updates every single game. Per-season stats (P/W/D/L/GF/GA/GD/PPG/Pts)
reset at the start of each season. All-time total points accumulate
forever. ELO starts at 1000 for every team and updates after every
match, weighted by goal difference.

Columns: # | Team | ELO | P | W | D | L | GF | GA | GD | PPG | Pts | Total

Playback speed: 4 games per second -> variable-length video.

Run from PowerShell:
    python video.py
    python video.py -f "C:\\path\\to\\folder_or_file"
"""

import csv
import glob
import os
import sys
import multiprocessing as mp
from functools import lru_cache
from collections import defaultdict
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import imageio.v2 as imageio
from tqdm.auto import tqdm


# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
CSV_PATH = r"C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND\Premier league\GAMES"

OUTPUT          = "premier_league_table.mp4"
DISPLAY_SIZE    = 20                # show only the top 20 at each snapshot
GAMES_PER_SECOND = 60.0              # playback speed (games per second)
FPS             = 30
WIDTH, HEIGHT   = 1280, 720         # 16:9, 720p landscape

PRESET          = "veryfast"        # x264 preset
X264_TUNE       = "stillimage"      # good for table/UI-style content
QUALITY         = 8                 # imageio quality 0-10
CHUNKSIZE       = 4                 # snapshots per pool task

# Worker count — None = auto (cpu_count - 1), 1 = single-process (debug)
WORKERS         = None

TITLE_MAIN      = "PREMIER LEAGUE"
TITLE_SUB       = "SEASON TABLE  \u2022  ELO  \u2022  ALL-TIME POINTS"

# ELO config
ELO_START       = 1000.0
ELO_K           = 20.0


# ----------------------------------------------------------------------
# Jupyter detection
# ----------------------------------------------------------------------
def _running_in_jupyter():
    if "ipykernel" in sys.modules or "ipykernel_launcher" in sys.modules:
        return True
    if "IPython" in sys.modules:
        try:
            from IPython import get_ipython  # noqa
            if get_ipython() is not None:
                return True
        except Exception:
            pass
    return False


IN_JUPYTER = _running_in_jupyter()

FLAG_TAKES_VALUE = {"-f", "--file", "--csv", "-i", "--input",
                    "-o", "--output"}


def parse_positional_args():
    if IN_JUPYTER:
        return []
    argv = sys.argv[1:]
    positional = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in FLAG_TAKES_VALUE:
            if i + 1 < len(argv):
                positional.append(argv[i + 1])
                i += 2
                continue
            i += 1
            continue
        if a.startswith("-"):
            i += 1
            continue
        positional.append(a)
        i += 1
    return positional


def clean(p):
    return p.strip().strip('"').strip("'")


def _is_csv(p):
    return p.lower().endswith(".csv")


# ----------------------------------------------------------------------
# Path resolution
# ----------------------------------------------------------------------
def resolve_csv_path(positional):
    for p in positional:
        cp = clean(p)
        if os.path.isdir(cp):
            return cp
        if os.path.isfile(cp) and _is_csv(cp):
            return cp
    if os.path.isdir(CSV_PATH):
        return CSV_PATH
    if os.path.isfile(CSV_PATH) and _is_csv(CSV_PATH):
        return CSV_PATH
    for name in ("results.csv", "premier_league.csv", "epl.csv"):
        if os.path.isfile(name):
            return os.path.abspath(name)
    return None


def resolve_output_path(positional):
    for p in positional[1:]:
        cp = clean(p)
        if cp and cp.lower().endswith(".mp4"):
            return cp
    return os.path.join(os.getcwd(), OUTPUT)


# ----------------------------------------------------------------------
# Fonts — cached so they load once per process, not per frame
# ----------------------------------------------------------------------
@lru_cache(maxsize=32)
def load_font(size, bold=False):
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ----------------------------------------------------------------------
# CSV loading
# ----------------------------------------------------------------------
ALIASES = {
    "date":       ["date", "match_date", "match date"],
    "home_team":  ["hometeam", "home_team", "home team", "home"],
    "away_team":  ["awayteam", "away_team", "away team", "away"],
    "home_score": ["fthg", "home_score", "home score", "hg", "home_goals",
                   "home goals"],
    "away_score": ["ftag", "away_score", "away score", "ag", "away_goals",
                   "away goals"],
}

DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y",
                "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d")


def _norm(s):
    return s.strip().strip('"').strip("'").lstrip("\ufeff").lower()


def _parse_date(s):
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError("Unparseable date: {!r}".format(s))


def _find_column(header_cells, field):
    for alias in ALIASES[field]:
        if alias in header_cells:
            return header_cells.index(alias)
    return None


def _load_single_csv(path):
    if not _is_csv(path):
        print("[load_matches] Skipping non-CSV file:", path)
        return []

    # Season identifier = source filename (without extension).
    season_name = os.path.splitext(os.path.basename(path))[0]

    try:
        with open(path, newline="", encoding="utf-8-sig",
                  errors="replace") as f:
            raw = list(csv.reader(f))
    except OSError as e:
        print("[load_matches] Could not read {}: {}".format(path, e))
        return []

    rows = [r for r in raw if any(c.strip() for c in r)]
    if not rows:
        print("[load_matches] File appears empty:", path)
        return []

    header_idx = None
    idx = None
    for i, r in enumerate(rows[:10]):
        cells = [_norm(c) for c in r]
        candidate = {field: _find_column(cells, field) for field in ALIASES}
        if all(v is not None for v in candidate.values()):
            header_idx = i
            idx = candidate
            break

    if header_idx is not None:
        data_rows = rows[header_idx + 1:]
    else:
        print("[load_matches] No header row detected in {} — assuming "
              "football-data.co.uk column order.".format(
                  os.path.basename(path)))
        idx = {"date": 1, "home_team": 3, "away_team": 4,
               "home_score": 5, "away_score": 6}
        data_rows = rows

    matches = []
    skipped = 0
    max_i = max(idx.values())
    for r in data_rows:
        if len(r) <= max_i:
            skipped += 1
            continue
        try:
            d  = _parse_date(r[idx["date"]])
            hs = int(float(r[idx["home_score"]]))
            ag = int(float(r[idx["away_score"]]))
            if hs < 0 or ag < 0:
                skipped += 1
                continue
        except (ValueError, IndexError, TypeError):
            skipped += 1
            continue
        home = r[idx["home_team"]].strip()
        away = r[idx["away_team"]].strip()
        if not home or not away:
            skipped += 1
            continue
        matches.append({
            "date":   d,
            "home":   home,
            "away":   away,
            "hs":     hs,
            "as":     ag,
            "season": season_name,
        })

    if skipped:
        print("[load_matches] {} — skipped {} unparseable rows".format(
            os.path.basename(path), skipped))

    return matches


def load_matches(path):
    if os.path.isdir(path):
        files = sorted(glob.glob(os.path.join(path, "*.csv")))
        if not files:
            files = sorted(glob.glob(os.path.join(path, "*", "*.csv")))
        if not files:
            print("[load_matches] No CSVs found in directory:", path)
            return []
        print("[load_matches] Loading {} CSV file(s) from {}".format(
            len(files), path))
        all_matches = []
        for f in files:
            all_matches.extend(_load_single_csv(f))
        # Stable sort so same-day games keep file order within season.
        all_matches.sort(key=lambda m: m["date"])
        return all_matches

    return _load_single_csv(path)


# ----------------------------------------------------------------------
# All teams
# ----------------------------------------------------------------------
def all_teams(matches):
    names = set()
    for m in matches:
        names.add(m["home"])
        names.add(m["away"])
    return sorted(names)


# ----------------------------------------------------------------------
# Standings
# ----------------------------------------------------------------------
def empty_row():
    return {"P": 0, "W": 0, "D": 0, "L": 0,
            "GF": 0, "GA": 0, "GD": 0, "Pts": 0, "PPG": 0.0}


def apply_result(row, gf, ga):
    row["P"] += 1
    row["GF"] += gf
    row["GA"] += ga
    if gf > ga:
        row["W"] += 1
        row["Pts"] += 3
    elif gf == ga:
        row["D"] += 1
        row["Pts"] += 1
    else:
        row["L"] += 1
    row["GD"] = row["GF"] - row["GA"]
    row["PPG"] = row["Pts"] / row["P"] if row["P"] else 0.0


def rank(combined):
    def key(item):
        t, r = item
        return (-r["Pts"], -r["GD"], -r["GF"],
                -r["TotalPts"], -r["Elo"], t)
    return sorted(combined.items(), key=key)


# ----------------------------------------------------------------------
# ELO — GD-weighted (World Football Elo-style goal multiplier)
# ----------------------------------------------------------------------
def elo_update(ra, rb, gd, k=ELO_K):
    """Return (new_ra, new_rb) after a match with goal difference `gd`
    from A's perspective (home)."""
    agd = abs(gd)
    if agd <= 1:
        g = 1.0
    elif agd == 2:
        g = 1.5
    else:
        g = (11.0 + agd) / 8.0

    ea = 1.0 / (1.0 + 10.0 ** ((rb - ra) / 400.0))
    if gd > 0:
        sa = 1.0
    elif gd == 0:
        sa = 0.5
    else:
        sa = 0.0

    change = k * g * (sa - ea)
    return ra + change, rb - change


# ----------------------------------------------------------------------
# Snapshots — one per game, reset per season
# ----------------------------------------------------------------------
def build_snapshots(matches, teams):
    season_rows = {t: empty_row() for t in teams}
    total_pts   = {t: 0 for t in teams}
    elo         = {t: ELO_START for t in teams}

    current_season = None
    snapshots = []

    for m in matches:
        season = m.get("season")
        if season != current_season:
            # New season -> reset current-season stats only.
            season_rows = {t: empty_row() for t in teams}
            current_season = season

        # Season stats
        apply_result(season_rows[m["home"]], m["hs"], m["as"])
        apply_result(season_rows[m["away"]], m["as"], m["hs"])

        # All-time total points
        if m["hs"] > m["as"]:
            total_pts[m["home"]] += 3
        elif m["hs"] == m["as"]:
            total_pts[m["home"]] += 1
            total_pts[m["away"]] += 1
        else:
            total_pts[m["away"]] += 3

        # ELO update (GD-weighted)
        gd = m["hs"] - m["as"]
        ra, rb = elo[m["home"]], elo[m["away"]]
        ra_new, rb_new = elo_update(ra, rb, gd)
        elo[m["home"]] = ra_new
        elo[m["away"]] = rb_new

        # Combined row for ranking + rendering
        combined = {}
        for t in teams:
            r = season_rows[t]
            combined[t] = {
                "P":        r["P"],
                "W":        r["W"],
                "D":        r["D"],
                "L":        r["L"],
                "GF":       r["GF"],
                "GA":       r["GA"],
                "GD":       r["GD"],
                "Pts":      r["Pts"],
                "PPG":      r["PPG"],
                "TotalPts": total_pts[t],
                "Elo":      elo[t],
            }

        frozen = rank(combined)
        snapshots.append((m["date"], frozen, current_season))

    return snapshots


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------
def render_frame(snapshot, w=WIDTH, h=HEIGHT, display_size=DISPLAY_SIZE):
    date, ranked, season = snapshot
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)

    f_big   = load_font(34, bold=True)
    f_med   = load_font(20, bold=True)
    f_row   = load_font(19)
    f_hdr   = load_font(16, bold=True)
    f_small = load_font(14, bold=True)

    d.text((w // 2, 14), TITLE_MAIN,
           font=f_big, fill=(10, 10, 60), anchor="mt")
    d.text((w // 2, 52), TITLE_SUB,
           font=f_med, fill=(120, 120, 120), anchor="mt")
    d.text((w // 2, 78), date.strftime("%d %b %Y"),
           font=f_med, fill=(0, 0, 0), anchor="mt")

    if season:
        d.text((w - 20, 18), str(season),
               font=f_small, fill=(150, 150, 150), anchor="rt")

    y_hdr = 112
    d.line([(20, y_hdr - 6), (w - 20, y_hdr - 6)], fill=(0, 0, 0), width=2)

    # Column x-positions --------------------------------------------------
    col_pos   = 30
    col_team  = 65
    col_elo   = 350
    col_p     = 430
    col_w     = 480
    col_d     = 530
    col_l     = 580
    col_gf    = 635
    col_ga    = 690
    col_gd    = 745
    col_ppg   = 810
    col_pts   = 885
    col_total = 1000

    d.text((col_pos,   y_hdr), "#",     font=f_hdr, fill=(60, 60, 60))
    d.text((col_team,  y_hdr), "TEAM",  font=f_hdr, fill=(60, 60, 60))
    d.text((col_elo,   y_hdr), "ELO",   font=f_hdr, fill=(60, 60, 60))
    d.text((col_p,     y_hdr), "P",     font=f_hdr, fill=(60, 60, 60))
    d.text((col_w,     y_hdr), "W",     font=f_hdr, fill=(60, 60, 60))
    d.text((col_d,     y_hdr), "D",     font=f_hdr, fill=(60, 60, 60))
    d.text((col_l,     y_hdr), "L",     font=f_hdr, fill=(60, 60, 60))
    d.text((col_gf,    y_hdr), "GF",    font=f_hdr, fill=(60, 60, 60))
    d.text((col_ga,    y_hdr), "GA",    font=f_hdr, fill=(60, 60, 60))
    d.text((col_gd,    y_hdr), "GD",    font=f_hdr, fill=(60, 60, 60))
    d.text((col_ppg,   y_hdr), "PPG",   font=f_hdr, fill=(60, 60, 60))
    d.text((col_pts,   y_hdr), "PTS",   font=f_hdr, fill=(60, 60, 60))
    d.text((col_total, y_hdr), "TOTAL", font=f_hdr, fill=(60, 60, 60))

    y_hdr_end = y_hdr + 26
    d.line([(20, y_hdr_end), (w - 20, y_hdr_end)],
           fill=(170, 170, 170), width=1)

    top = ranked[:display_size]
    n = len(top)
    top_y = y_hdr_end + 8
    avail = h - top_y - 20
    row_h = max(18, avail // max(n, 1))

    # Vertical grid separators (subtle)
    for x in (col_elo - 10, col_p - 10, col_gf - 10, col_ppg - 12,
              col_pts - 14, col_total - 14):
        d.line([(x, y_hdr_end), (x, h - 12)], fill=(225, 225, 225), width=1)

    for i, (team, r) in enumerate(top):
        pos = i + 1
        y = top_y + i * row_h

        if pos <= 4:
            color = (0, 130, 0)
        elif n >= 6 and pos > n - 3:
            color = (190, 0, 0)
        else:
            color = (20, 20, 20)

        gd_txt    = "+{}".format(r["GD"]) if r["GD"] > 0 else str(r["GD"])
        ppg_txt   = "{:.2f}".format(r["PPG"])
        elo_txt   = str(int(round(r["Elo"])))

        d.text((col_pos,   y), str(pos),           font=f_row, fill=color)
        d.text((col_team,  y), team,               font=f_row, fill=color)
        d.text((col_elo,   y), elo_txt,            font=f_row, fill=color)
        d.text((col_p,     y), str(r["P"]),        font=f_row, fill=color)
        d.text((col_w,     y), str(r["W"]),        font=f_row, fill=color)
        d.text((col_d,     y), str(r["D"]),        font=f_row, fill=color)
        d.text((col_l,     y), str(r["L"]),        font=f_row, fill=color)
        d.text((col_gf,    y), str(r["GF"]),       font=f_row, fill=color)
        d.text((col_ga,    y), str(r["GA"]),       font=f_row, fill=color)
        d.text((col_gd,    y), gd_txt,             font=f_row, fill=color)
        d.text((col_ppg,   y), ppg_txt,            font=f_row, fill=color)
        d.text((col_pts,   y), str(r["Pts"]),      font=f_row, fill=color)
        d.text((col_total, y), str(r["TotalPts"]), font=f_row, fill=color)

    return img


def _render_worker(args):
    snapshot, w, h, display_size = args
    img = render_frame(snapshot, w, h, display_size)
    return np.asarray(img, dtype=np.uint8).tobytes()


# ----------------------------------------------------------------------
# Output frame distribution
# ----------------------------------------------------------------------
def precompute_frame_counts(n_snapshots, total_frames):
    counts = [0] * n_snapshots
    if n_snapshots == 0 or total_frames <= 0:
        return counts
    for i in range(total_frames):
        idx = int(i * n_snapshots / total_frames)
        if idx >= n_snapshots:
            idx = n_snapshots - 1
        counts[idx] += 1
    return counts


def default_workers():
    if WORKERS is not None:
        return WORKERS
    try:
        n = mp.cpu_count() or 1
    except Exception:
        n = 1
    return max(1, n - 1)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    positional = parse_positional_args()

    in_path = resolve_csv_path(positional)
    if not in_path:
        sys.exit(
            "Could not find the Premier League data.\n"
            "Make sure this folder exists:\n"
            "    {}\n"
            "Or pass a path explicitly:\n"
            "    python video.py -f \"C:\\full\\path\""
            .format(CSV_PATH)
        )

    out_path = os.path.abspath(resolve_output_path(positional))
    print("Input:   {}".format(in_path))
    print("Output:  {}".format(out_path))
    print("Workers: {}".format(default_workers()))

    # --- Load CSV(s) --------------------------------------------------
    with tqdm(total=1, desc="Loading CSV", unit="file",
              bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}") as pbar:
        matches = load_matches(in_path)
        pbar.update(1)

    if not matches:
        sys.exit("No valid matches parsed from {}".format(in_path))
    print("  {} matches  ({} -> {})".format(
        len(matches), matches[0]["date"], matches[-1]["date"]))

    teams = all_teams(matches)
    print("  {} unique teams (all tracked)".format(len(teams)))

    # --- Snapshots (one per game) -------------------------------------
    snapshots = build_snapshots(matches, teams)
    n_snaps = len(snapshots)
    print("  {} game snapshots".format(n_snaps))
    if not snapshots:
        sys.exit("No snapshots built.")

    # --- Precompute how many output frames each snapshot gets ---------
    total_frames = max(1, int(round(n_snaps * FPS / GAMES_PER_SECOND)))
    frame_counts = precompute_frame_counts(n_snaps, total_frames)
    duration_sec = total_frames / FPS
    print("  {} output frames at {} fps (~{:.1f}s = {:d}m{:02d}s) — "
          "{:.1f} games/s".format(
              total_frames, FPS, duration_sec,
              int(duration_sec // 60), int(duration_sec % 60),
              n_snaps / duration_sec if duration_sec else 0.0))

    # --- Writer --------------------------------------------------------
    writer_kwargs = dict(
        fps=FPS, codec="libx264", quality=QUALITY,
        macro_block_size=None,
    )
    try:
        writer = imageio.get_writer(
            out_path,
            output_params=["-preset", PRESET, "-tune", X264_TUNE],
            **writer_kwargs
        )
    except Exception:
        writer = imageio.get_writer(out_path, **writer_kwargs)

    # --- Render + encode streaming ------------------------------------
    tasks = [(snap, WIDTH, HEIGHT, DISPLAY_SIZE) for snap in snapshots]
    n_workers = default_workers()

    pbar = tqdm(total=total_frames, desc="Render + encode", unit="frame",
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} "
                           "[{elapsed}<{remaining}, {rate_fmt}]")

    try:
        if n_workers > 1:
            pool = mp.Pool(processes=n_workers)
            try:
                for snap_idx, buf in enumerate(
                        pool.imap(_render_worker, tasks,
                                  chunksize=CHUNKSIZE)):
                    arr = np.frombuffer(buf, dtype=np.uint8).reshape(
                        HEIGHT, WIDTH, 3)
                    for _ in range(frame_counts[snap_idx]):
                        writer.append_data(arr)
                        pbar.update(1)
            finally:
                pool.close()
                pool.join()
        else:
            for snap_idx, snap in enumerate(snapshots):
                img = render_frame(snap, WIDTH, HEIGHT, DISPLAY_SIZE)
                arr = np.asarray(img, dtype=np.uint8)
                for _ in range(frame_counts[snap_idx]):
                    writer.append_data(arr)
                    pbar.update(1)
    finally:
        pbar.close()
        writer.close()

    print("Done: {}".format(out_path))


if __name__ == "__main__":
    main()