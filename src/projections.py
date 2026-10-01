"""Load the newest Data Driven Hockey rankings exports from projections/."""
import glob
import os
import re

import pandas as pd

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _newest(folder, prefix):
    files = glob.glob(os.path.join(folder, f"{prefix}*.csv"))
    if not files:
        raise FileNotFoundError(f"No {prefix}*.csv in {folder}")

    def key(f):
        m = DATE_RE.search(os.path.basename(f))
        return (m.group(1) if m else "", os.path.getmtime(f))
    f = max(files, key=key)
    m = DATE_RE.search(os.path.basename(f))
    return f, (m.group(1) if m else None)


def load(folder="projections"):
    sk_path, sk_date = _newest(folder, "skater-rankings")
    go_path, go_date = _newest(folder, "goalie-rankings")
    sk = pd.read_csv(sk_path)
    go = pd.read_csv(go_path)
    go["Position"] = "G"
    df = pd.concat([sk, go], ignore_index=True)
    df = df.rename(columns={"Player": "name", "Team": "nhl", "Position": "pos", "Fantasy Points": "fp", "GP": "gp"})
    df = df[["name", "nhl", "pos", "fp", "gp"]].copy()
    df["nhl"] = df.nhl.str.upper()
    df = df[df.gp > 0]
    df["ppg"] = df.fp / df.gp
    return df, {"skaters": os.path.basename(sk_path), "goalies": os.path.basename(go_path),
                "date": min(d for d in [sk_date, go_date] if d) if (sk_date or go_date) else None}
