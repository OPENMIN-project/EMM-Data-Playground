
from __future__ import annotations

from pathlib import Path
import csv
import pandas as pd
import unicodedata as u

# Expected file name in DATA_DIR
CIVIC_CODEBOOK_FILENAME = "civic_codebook.csv"

def _norm(s: str) -> str:
    s = u.normalize("NFKC", str(s or ""))
    return s.replace("\ufeff","").replace("\u200b","").replace("\xa0"," ").strip()

def _norm_var(v: str) -> str:
    return _norm(v).lower()

def load_civic_codebook(data_dir: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    """
    Load Civic & Political Integration codebook from DATA_DIR/civic_codebook.csv.

    The file contains quoted multi-line cells, so we use Python's csv.reader to
    correctly handle newlines inside quotes.

    Returns:
      meta_df with columns: variable, theme, subtheme
      labels dict: {variable(lower): label}
    """
    path = Path(data_dir) / CIVIC_CODEBOOK_FILENAME
    if not path.exists():
        # Return empty but safe structures
        meta = pd.DataFrame(columns=["variable","theme","subtheme"])
        return meta, {}

    rows = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f, delimiter=";", quotechar='"', doublequote=True, skipinitialspace=False)
        for r in reader:
            if not r:
                continue
            rows.append(r)

    if not rows:
        meta = pd.DataFrame(columns=["variable","theme","subtheme"])
        return meta, {}

    header = [ _norm(c).lower() for c in rows[0] ]
    data_rows = rows[1:]

    # Some broken exports have stray 1-col rows; drop those.
    width = len(header)
    clean = [r for r in data_rows if len(r) == width]

    df = pd.DataFrame(clean, columns=header)

    # Map expected columns
    # canonical names: variable, label, theme, subtheme
    colmap = {}
    for c in df.columns:
        if c in {"variable","var","code","qid"}:
            colmap[c] = "variable"
        elif c in {"label","question","text","name"}:
            colmap[c] = "label"
        elif c in {"theme","theme_name","topic"}:
            colmap[c] = "theme"
        elif c in {"subtheme","sub_theme","subcategory","subtopic"}:
            colmap[c] = "subtheme"
    df = df.rename(columns=colmap)

    for need in ["variable","theme","subtheme"]:
        if need not in df.columns:
            df[need] = ""

    df["variable"] = df["variable"].map(_norm_var)
    df["theme"] = df["theme"].map(_norm)
    df["subtheme"] = df["subtheme"].map(_norm)

    # labels mapping
    labels = {}
    if "label" in df.columns:
        for v, lab in zip(df["variable"].tolist(), df["label"].tolist()):
            v = _norm_var(v)
            lab = _norm(lab)
            if v and lab and v not in labels:
                labels[v] = lab

    meta = df[["variable","theme","subtheme"]].copy()
    meta = meta[meta["variable"] != ""]
    meta = meta.drop_duplicates(subset=["variable"])
    # Ensure themes exist (fallback: Unknown)
    meta["theme"] = meta["theme"].replace({"": "Unknown"})
    meta["subtheme"] = meta["subtheme"].replace({"": None})

    return meta, labels
