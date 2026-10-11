#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIFA World Cup — MEN's all-time league table (MP4).

Landscape 720p (1280x720), 16:9, 2 min 30 sec.
Only FIFA World Cup finals matches are counted (qualification excluded).
Every team that has ever played a World Cup match is tracked; only the
CURRENT TOP 20 are shown at each date, so teams slide in and out of the
video as their rank changes.

Ranking: Points -> Goal Difference -> Goals For -> Goals Against.
Display: # | Team | W | D | L | GD | GF | GA | PTS

Run from PowerShell:
    python world_table_men.py
    python world_table_men.py -f "C:\\path\\to\\results.csv"
"""

import csv
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
CSV_PATH = r"C:\Users\liam\Documents\GitHub\Footballdata\data\international\games\results.csv"

OUTPUT         = "world_cup_table_men.mp4"
DISPLAY_SIZE   = 20                # show only the top 20 at each date
DURATION       = 150.0             # 2 min 30 sec
FPS            = 30
WIDTH, HEIGHT  = 1280, 720         # 16:9, 720p LANDSCAPE

# Only matches whose tournament column equals this (exact, case-insensitive)
# string are counted. "FIFA World Cup" alone excludes
# "FIFA World Cup qualification" automatically.
# Set to None to include every match in the CSV.
TOURNAMENT_FILTER = "FIFA World Cup"

PRESET         = "veryfast"
X264_TUNE      = "stillimage"
QUALITY        = 8
CHUNKSIZE      = 4

# Worker count — None = auto (cpu_count - 1), 1 = single-process (debug)
WORKERS        = None


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
        if os.path.isfile(cp) and _is_csv(cp):
            return cp
    if os.path.isfile(CSV_PATH) and _is_csv(CSV_PATH):
        return CSV_PATH
    for name in ("results.csv", "mens.csv", "men.csv"):
        if os.path.isfile(name):
            return os.path.abspath(name)
    return None


def resolve_output_path(positional):
    for p in positional[1:]:
        cp = clean(p)
        if cp and _is_csv(cp) and os.path.abspath(cp) != os.path.abspath(CSV_PATH):
            return cp
    return os.path.join(os.getcwd(), OUTPUT)


# ----------------------------------------------------------------------
# Fonts
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
    "home_team":  ["home_team", "home team", "home", "hometeam"],
    "away_team":  ["away_team", "away team", "away", "awayteam"],
    "home_score": ["home_score", "home score", "hg", "home_goals", "home goals"],
    "away_score": ["away_score", "away score", "ag", "away_goals", "away goals"],
    "tournament": ["tournament", "competition", "comp"],
}


def _norm(s):
    return s.strip().strip('"').strip("'").lstrip("\ufeff").lower()


def _find_column(header_cells, field):
    for alias in ALIASES[field]:
        if alias in header_cells:
            return header_cells.index(alias)
    return None


def load_matches(path, tournament_filter=TOURNAMENT_FILTER):
    if not _is_csv(path):
        print("[load_matches] Refusing to parse non-CSV file:", path)
        return []

    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        raw = list(csv.reader(f))

    rows = [r for r in raw if any(c.strip() for c in r)]
    if not rows:
        print("[load_matches] File appears empty:", path)
        return []

    header_idx = None
    idx = None
    tournament_required = tournament_filter is not None
    required_fields = ["date", "home_team", "away_team", "home_score", "away_score"]

    for i, r in enumerate(rows[:10]):
        cells = [_norm(c) for c in r]
        candidate = {field: _find_column(cells, field) for field in ALIASES}
        if all(candidate[f] is not None for f in required_fields):
            if tournament_required and candidate["tournament"] is None:
                continue
            header_idx = i
            idx = candidate
            break

    if header_idx is not None:
        data_rows = rows[header_idx + 1:]
        print("[load_matches] Header found on line {}".format(header_idx + 1))
    else:
        if tournament_required:
            sys.exit(
                "Could not find a 'tournament' column in {}.\n"
                "This script filters matches by tournament (currently "
                "'{}'). Either pass a CSV that has a tournament column or "
                "set TOURNAMENT_FILTER = None.".format(path, tournament_filter)
            )
        print("[load_matches] No header row detected — assuming "
              "standard column order.")
        idx = {"date": 0, "home_team": 1, "away_team": 2,
               "home_score": 3, "away_score": 4, "tournament": 5}
        data_rows = rows

    matches = []
    skipped = 0
    filtered_out = 0
    tgt = tournament_filter.strip().lower() if tournament_filter else None
    max_i = max(v for v in idx.values() if v is not None)

    for r in data_rows:
        if len(r) <= max_i:
            skipped += 1
            continue
        try:
            d  = datetime.strptime(_norm(r[idx["date"]]), "%Y-%m-%d").date()
            hs = int(float(r[idx["home_score"]]))
            ag = int(float(r[idx["away_score"]]))
            if hs < 0 or ag < 0:
                skipped += 1
                continue
        except (ValueError, IndexError, TypeError):
            skipped += 1
            continue

        if tgt is not None:
            t_idx = idx.get("tournament")
            if t_idx is None or len(r) <= t_idx:
                filtered_out += 1
                continue
            if r[t_idx].strip().lower() != tgt:
                filtered_out += 1
                continue

        matches.append({
            "date": d,
            "home": r[idx["home_team"]].strip(),
            "away": r[idx["away_team"]].strip(),
            "hs":   hs,
            "as":   ag,
        })

    if skipped:
        print("[load_matches] Skipped {} unparseable rows".format(skipped))
    if filtered_out:
        print("[load_matches] Filtered out {} non-'{}' matches".format(
            filtered_out, tournament_filter))

    matches.sort(key=lambda m: m["date"])
    return matches


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
    return {"P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "Pts": 0}


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


def rank(standings):
    def key(item):
        t, r = item
        return (-r["Pts"], -(r["GF"] - r["GA"]), -r["GF"], r["GA"], t)
    return sorted(standings.items(), key=key)


# ----------------------------------------------------------------------
# Snapshots
# ----------------------------------------------------------------------
def build_snapshots(matches, teams):
    by_date = defaultdict(list)
    for m in matches:
        by_date[m["date"]].append(m)

    sorted_dates = sorted(by_date)
    standings = {t: empty_row() for t in teams}
    snapshots = []
    for d in sorted_dates:
        for m in by_date[d]:
            apply_result(standings[m["home"]], m["hs"], m["as"])
            apply_result(standings[m["away"]], m["as"], m["hs"])
        frozen = [(t, dict(r)) for t, r in rank(standings)]
        snapshots.append((d, frozen))
    return snapshots


# ----------------------------------------------------------------------
# Rendering — LANDSCAPE 1280x720
# ----------------------------------------------------------------------
def render_frame(snapshot, w=WIDTH, h=HEIGHT, display_size=DISPLAY_SIZE):
    date, ranked = snapshot
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)

    # Font sizes tuned for landscape (less vertical space)
    f_title = load_font(28, bold=True)
    f_med   = load_font(16, bold=True)
    f_hdr   = load_font(15, bold=True)
    f_row   = load_font(16)

    # -------- Title block (top center) --------------------------------
    d.text((w // 2, 10), "FIFA WORLD CUP",
           font=f_title, fill=(10, 10, 60), anchor="mt")
    d.text((w // 2, 44), "MEN'S ALL-TIME TABLE  \u2022  TOP 20  \u2022  "
                         + date.strftime("%d %b %Y"),
           font=f_med, fill=(120, 120, 120), anchor="mt")

    # -------- Column layout ------------------------------------------
    # Left-anchored:  pos, team
    # Right-anchored: all seven numeric stats
    col_pos  = 60
    col_team = 120

    # Right-edge x-positions for numeric columns
    col_w    = 720
    col_d    = 790
    col_l    = 860
    col_gd   = 940
    col_gf   = 1010
    col_ga   = 1080
    col_pts  = 1210

    hdr_fill = (60, 60, 60)

    y_hdr = 78
    d.line([(50, y_hdr - 4), (w - 50, y_hdr - 4)], fill=(0, 0, 0), width=2)

    # Headers
    d.text((col_pos,  y_hdr), "#",    font=f_hdr, fill=hdr_fill)
    d.text((col_team, y_hdr), "TEAM", font=f_hdr, fill=hdr_fill)

    d.text((col_w,   y_hdr), "W",   font=f_hdr, fill=hdr_fill, anchor="ra")
    d.text((col_d,   y_hdr), "D",   font=f_hdr, fill=hdr_fill, anchor="ra")
    d.text((col_l,   y_hdr), "L",   font=f_hdr, fill=hdr_fill, anchor="ra")
    d.text((col_gd,  y_hdr), "GD",  font=f_hdr, fill=hdr_fill, anchor="ra")
    d.text((col_gf,  y_hdr), "GF",  font=f_hdr, fill=hdr_fill, anchor="ra")
    d.text((col_ga,  y_hdr), "GA",  font=f_hdr, fill=hdr_fill, anchor="ra")
    d.text((col_pts, y_hdr), "PTS", font=f_hdr, fill=hdr_fill, anchor="ra")

    y_hdr_end = y_hdr + 22
    d.line([(50, y_hdr_end), (w - 50, y_hdr_end)],
           fill=(170, 170, 170), width=1)

    # -------- Rows ----------------------------------------------------
    top = ranked[:display_size]
    n = len(top)
    top_y = y_hdr_end + 8
    avail = h - top_y - 14
    row_h = max(16, avail // max(n, 1))

    for i, (team, r) in enumerate(top):
        pos = i + 1
        y = top_y + i * row_h

        if pos <= 4:
            color = (0, 130, 0)
        elif n >= 6 and pos > n - 3:
            color = (190, 0, 0)
        else:
            color = (20, 20, 20)

        gd = r["GF"] - r["GA"]
        gd_txt = "+{}".format(gd) if gd > 0 else str(gd)

        d.text((col_pos,  y), str(pos), font=f_row, fill=color)
        d.text((col_team, y), team,     font=f_row, fill=color)

        d.text((col_w,   y), str(r["W"]),   font=f_row, fill=color, anchor="ra")
        d.text((col_d,   y), str(r["D"]),   font=f_row, fill=color, anchor="ra")
        d.text((col_l,   y), str(r["L"]),   font=f_row, fill=color, anchor="ra")
        d.text((col_gd,  y), gd_txt,        font=f_row, fill=color, anchor="ra")
        d.text((col_gf,  y), str(r["GF"]),  font=f_row, fill=color, anchor="ra")
        d.text((col_ga,  y), str(r["GA"]),  font=f_row, fill=color, anchor="ra")
        d.text((col_pts, y), str(r["Pts"]), font=f_row, fill=color, anchor="ra")

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
            "Could not find the men's results CSV.\n"
            "Make sure this file exists:\n"
            "    {}\n"
            "Or pass the path explicitly:\n"
            "    python world_table_men.py -f \"C:\\full\\path\\results.csv\""
            .format(CSV_PATH)
        )

    out_path = os.path.abspath(resolve_output_path(positional))
    print("Input:      {}".format(in_path))
    print("Output:     {}".format(out_path))
    print("Tournament: {}".format(TOURNAMENT_FILTER or "(all)"))
    print("Resolution: {}x{} (landscape)".format(WIDTH, HEIGHT))
    print("Workers:    {}".format(default_workers()))

    with tqdm(total=1, desc="Loading CSV", unit="file",
              bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}") as pbar:
        matches = load_matches(in_path, TOURNAMENT_FILTER)
        pbar.update(1)

    if not matches:
        sys.exit("No valid matches parsed from {} (filter: {})".format(
            in_path, TOURNAMENT_FILTER))
    print("  {} matches  ({} -> {})".format(
        len(matches), matches[0]["date"], matches[-1]["date"]))

    teams = all_teams(matches)
    print("  {} unique teams (all tracked)".format(len(teams)))

    snapshots = build_snapshots(matches, teams)
    n_snaps = len(snapshots)
    print("  {} unique match dates".format(n_snaps))
    if not snapshots:
        sys.exit("No snapshots built.")

    total_frames = int(DURATION * FPS)
    frame_counts = precompute_frame_counts(n_snaps, total_frames)
    print("  {} output frames at {} fps (~{:.0f}s)".format(
        total_frames, FPS, DURATION))

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
                        pool.imap(_render_worker, tasks, chunksize=CHUNKSIZE)):
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