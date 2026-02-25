# =============================================================================
# SECTION 1: IMPORTS AND LOGGING
# =============================================================================
# Imports all Python libraries needed by the application and sets up error
# logging. Errors are written to a file (path from DP_ERROR_LOG env variable).
#
# SAME FOR ANY DATASET — no changes needed unless adding a new survey adapter
# module (you would add a new "from my_new_adapter import ..." line).
# =============================================================================
from __future__ import annotations

from pathlib import Path
import time, errno, colorsys, csv, io, re, warnings, hashlib, os, base64
import dash
from dash import ctx
import logging, traceback, sys
from survey_localmultidem import LocalMultiAdapter
from survey_civic import CivicPolAdapter
from codebook_parser import load_civic_codebook

try:
    LOG_PATH = os.environ.get("DP_ERROR_LOG", os.path.expanduser("~/dataplayground.log"))
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.ERROR,
        format="%(asctime)s %(levelname)s %(message)s"
    )
except Exception:

    logging.basicConfig(stream=sys.stderr, level=logging.ERROR)

def _log_exc(e: Exception, where: str = ""):
    try:
        logging.error("%s: %s\n%s", where or "error", str(e), traceback.format_exc())
    except Exception:
        pass

from urllib.parse import parse_qs, urlparse  # parsing

# =============================================================================
# SECTION 2: DATA DIRECTORY, FILE PATHS, AND CATEGORY ORDERS
# =============================================================================
# Defines where all data files live. Reads DATA_DIR from the environment
# variable (set in the systemd service file on the server).
# Also loads category order from CSV so answer options appear in the right order.
#
# CHANGE FOR NEW DATASET — update the file names (DATA_PATH, CIVIC_CSV_PATH,
# etc.) if you use different data files. The fallback paths for local dev
# may also need updating.
# =============================================================================
import numpy as np
import pandas as pd
import csv

import plotly.express as px                 # fast graphics
import plotly.graph_objects as go

# ============================================================================
# CATEGORY ORDER FROM CSV
# ============================================================================

DATA_DIR = Path(os.environ.get("DATA_DIR", "/home/ekaterina_iakovleva/dataplayground-data"))

def _load_category_orders_from_csv():
    """
    Load category orders from localmultidem_category_labels.csv
    Returns dict: {variable: [ordered_labels_without_numbers]}
    """
    import ast
    csv_path = Path(DATA_DIR) / "localmultidem_category_labels.csv"
    
    if not csv_path.exists():
        print(f"Warning: Category labels CSV not found at {csv_path}")
        return {}
    
    try:
        df = pd.read_csv(csv_path, sep=";", encoding="utf-8")
        category_orders = {}
        
        for _, row in df.iterrows():
            var = str(row["Variable"]).strip().lower()
            labels_str = str(row["Labels"])
            
            try:
                labels = ast.literal_eval(labels_str)
                if isinstance(labels, list):
                    cleaned_labels = []
                    for label in labels:
                        # Remove number prefixes like "0. ", "1. ", etc.
                        cleaned = re.sub(r"^\d+\.\s*", "", str(label))
                        if cleaned and not cleaned.startswith("-"):
                            cleaned_labels.append(cleaned)
                    
                    if cleaned_labels:
                        category_orders[var] = cleaned_labels
            except (ValueError, SyntaxError):
                continue
        
        print(f"Loaded category orders for {len(category_orders)} variables from CSV")
        return category_orders
    
    except Exception as e:
        print(f"Error loading category orders from CSV: {e}")
        return {}

# Load category orders at module level
CATEGORY_ORDERS_FROM_CSV = _load_category_orders_from_csv()


# fonts and template
px.defaults.template = "plotly_white"

try:
    if hasattr(px.defaults, "font"):
        px.defaults.font = dict(
            family=globals().get("BRAND_FONT_BODY", "Merriweather, Georgia, 'Times New Roman', serif"),
            size=13,
            color="#222222",
        )
except Exception:
    pass

# Dash web
import dash_bootstrap_components as dbc
from dash import Dash, html, dcc, Input, Output, State, ALL, no_update
from dash import dash_table

# UI helper: horizontal scroll container for wide figures 
def hscroll(child):
    """Horizontally scrollable wrapper (prevents Plotly category compression)."""
    return html.Div(
        child,
        style={
            "overflowX": "auto",
            "overflowY": "auto",  # allow vertical scroll
            "width": "100%",
            "maxWidth": "100%",
        },
    )

warnings.filterwarnings("ignore", category=UserWarning)


# optional dependency:
try:
    import pyreadstat 
    try:
        from pyreadstat import ReadstatError
    except Exception:
        ReadstatError = Exception
except ModuleNotFoundError:
    pyreadstat = None
    ReadstatError = Exception

BASE = DATA_DIR

LABEL_PATH        = DATA_DIR / "localmultidem_category_labels.csv"
CODEBOOK_PATH     = DATA_DIR / "localmultidem_codebook.csv"
DATA_PATH         = DATA_DIR / "localmultidem_responses.tab"
# ▶ Civic & Political Integration (second survey)
CIVIC_CODEBOOK_PATH = DATA_DIR / "civic_codebook.csv"
CIVIC_CSV_PATH = DATA_DIR / "civic_responses.csv"
COUNTRY_META_PATH = DATA_DIR / "country_amount.csv"
POST_DTA_PATH     = DATA_DIR / "Post-harmonized country-specific variables for Data Playground.dta"
THEME_CANDIDATES = [
    DATA_DIR / "localmultidem_themes.csv",
    DATA_DIR / "variables_by_theme_clean.csv",
]


MEDIAN_CSV_PATH = Path(os.environ.get("MEDIAN_CSV", "/Users/ordi/Desktop/localmultidem_medians.csv"))

# =============================================================================
# SECTION 3: CIVIC CITY AND GROUP MAPPINGS
# =============================================================================
# The Civic survey data uses numeric LAU codes instead of city names (e.g.,
# 69123 = Lyon). This section has translation tables that convert those codes
# to readable names. Also maps numeric group codes to group names (e.g.,
# 1 = Turkish) and defines which groups are "native" (autochthonous).
#
# CHANGE FOR NEW DATASET — all mappings here are Civic-survey-specific.
# If you add new cities: add entries to CIVIC_CITY_MAPPING.
# If you add new groups: add entries to CIVIC_GROUP_LABELS and
# CIVIC_COUNTRY_MAPPING. If you add new native nationalities: add them to
# CIVIC_NATIVE_GROUP_NAMES. For a completely different survey: replace all.
# =============================================================================

# CIVIC & POLITICAL INTEGRATION SURVEY - CITY MAPPING
# Based on LAU (Local Administrative Units) codes
# Updated according to complete specification

CIVIC_CITY_MAPPING = {
    # Netherlands
    'GM0363': 'Amsterdam',
    'GM0599': 'Rotterdam',
    
    # Belgium
    '11002': 'Antwerp',
    '21004': 'Brussels',
    '62063': 'Liege',
    
    # Spain
    '08019': 'Barcelona',
    '080508': 'Faro',
    '28079': 'Madrid',
    
    # Switzerland
    'CH2701': 'Basel',
    'CH6621': 'Geneva',
    'CH0261': 'Zurich',
    
    # Germany
    '11000000': 'Berlin',
    '5112000': 'Duisburg',
    '06412000': 'Frankfurt (Main)',
    '8111000': 'Stuttgart',
    
    # Hungary
    '13578': 'Budapest',
    
    # UK - London Boroughs
    'E09000007': 'Camden (London)',
    'E09000012': 'Hackney (London)',
    'E09000014': 'Haringey (London)',
    'E09000019': 'Islington (London)',
    
    # Portugal
    '151205': 'Setubal',
    # Lisbon: 38 non-consecutive LAU codes between 110501 and 110731
    **{f'{code:06d}': 'Lisbon' for code in range(110501, 110732)},
    
    # France
    '69123': 'Lyon',
    '75056': 'Paris',
    '67482': 'Strasbourg',
    
    # Italy
    '015146': 'Milan',
    '63049': 'Naples',
    '001272': 'Turin',
    
    # Norway
    '0301': 'Oslo',
    
    # Sweden
    '0180': 'Stockholm',

    # Combined London boroughs
    'E09000007; E09000012; E09000014; E09000019': 'London',

    # Austria
    '40101': 'Vienna',
    '90001': 'Vienna',

    # Portugal (additional)
    'PT001C': 'Lisbon',

    # Germany (with leading zeros)
    '05112000': 'Duisburg',
    '08111000': 'Stuttgart',
    '063049': 'Naples',
}

# Group labels for rgroup column (numeric code -> label)
CIVIC_GROUP_LABELS = {
    -9: 'Answer not available',
    1: 'French', 2: 'British', 3: 'Italian', 4: 'Hungarian', 5: 'Swiss',
    6: 'Spanish', 7: 'Ethnic Hungarian', 8: 'Kosovar', 9: 'Turk', 10: 'Moroccan',
    11: 'Pakistani', 12: 'Bangladeshi', 13: 'Algerian', 14: 'Tunisian', 15: 'Egyptian',
    16: 'Philippine', 17: 'Ecuadorian', 18: 'Indian', 19: 'Chinese', 20: 'Caribbean',
    21: 'Andean Latin American', 22: 'Mixed Muslim', 23: 'Norwegian', 24: 'Bosnian',
    25: 'Mixed Race British', 26: 'Swedish', 27: 'Chilean', 28: 'Belgian', 29: 'Congolese',
    30: 'Mixed national origins', 31: 'Turk (2nd gen.)', 32: 'Moroccan (2nd gen.)',
    33: 'Former Yugoslavian (2nd gen.)', 34: 'Dutch (comp. group)', 35: 'German (comp. group)',
    36: 'Austrian (comp. group)', 37: 'Swedes (comp. group)',
    50: 'Non-EU–born immigrants', 51: 'Non-national residents',
}

# Native/autochthonous group names in the Civic survey — these should never
# appear in the group dropdown; they are collapsed into "Autochthonous".
CIVIC_NATIVE_GROUP_NAMES: set[str] = {
    "French", "British", "Italian", "Hungarian", "Swiss", "Spanish",
    "Norwegian", "Swedish", "Belgian", "Dutch", "German",
    "Dutch (comp. group)", "German (comp. group)",
    "Austrian (comp. group)", "Swedes (comp. group)",
}

def _decode_lau_civic(lau_code):
    """
    Decode LAU code to city name for Civic survey.
    Uses CIVIC_CITY_MAPPING.
    """
    if pd.isna(lau_code):
        return "Unknown"
    
    lau_str = str(lau_code).strip()
    
    # Try direct lookup
    if lau_str in CIVIC_CITY_MAPPING:
        return CIVIC_CITY_MAPPING[lau_str]
    
    # Try without leading zeros
    lau_no_zeros = lau_str.lstrip("0")
    if lau_no_zeros in CIVIC_CITY_MAPPING:
        return CIVIC_CITY_MAPPING[lau_no_zeros]
    
    # Try with leading zeros
    for length in [6, 8, 10]:
        lau_padded = lau_str.zfill(length)
        if lau_padded in CIVIC_CITY_MAPPING:
            return CIVIC_CITY_MAPPING[lau_padded]
    
    return f"LAU-{lau_str}"




# =============================================================================
# VARIABLE DISPLAY CONTROL - Forces specific chart types
# =============================================================================

# Variables that MUST display as box plots (numeric scales)
FORCE_BOX_PLOT_VARS = {
    "q1301",  # Attachment to same religion (0-7 scale)
    "q1308",  # Attachment to ethnic group (1-10 scale)
    "q3301",  # Society has negative attitude towards immigrants (0-10)
    "q3302", "q3303", "q3304", "q3305", "q3306", "q3307",
}

# Variables that MUST display as categorical bar charts (not curves)
FORCE_CATEGORICAL_BARS = {
    "q1604", "q1605", "q1606", "q1607",  # Interest in politics
}

# Fixed category order for "People concerned" variables
PEOPLE_CONCERNED_CATEGORY_ORDER = [
    "Only my ethnic group",
    "My ethnic group and other groups in this country",
    "All people in this country",
    "All people in Europe",
    "Whole world",
]

PEOPLE_CONCERNED_VARS = {
    "q24c01", "q24c02", "q24c03", "q24c04", "q24c05", "q24c06",
    "q24c07", "q24c08", "q24c09", "q24c10", "q24c11", "q24c12",
}

# Thermometer scale labels (0-10 scales with meaningful endpoints)
THERMOMETER_SCALE_LABELS = {
    "q34": ("Can't be too careful", "Most people can be trusted"),
    "q35": ("Can't be too careful", "Most people can be trusted"),
    "q3301": ("Not negative at all", "Very negative"),
    "q3302": ("Not negative at all", "Very negative"),
    "q3303": ("Not negative at all", "Very negative"),
    "q3304": ("Not negative at all", "Very negative"),
    "q3305": ("Not negative at all", "Very negative"),
    "q3306": ("Not negative at all", "Very negative"),
    "q3307": ("Not negative at all", "Very negative"),
    "q1301": ("Not at all attached", "Very attached"),
    "q1308": ("Not at all attached", "Very attached"),
}

# Add a helper function to handle unknown LAU codes
def map_lau_to_city(lau_code):
    """Map LAU code to city name, with fallback logic."""
    if pd.isna(lau_code):
        return "Unknown"
    
    lau_str = str(lau_code).strip()
    
    # Direct mapping
    if lau_str in CIVIC_CITY_MAPPING:
        return CIVIC_CITY_MAPPING[lau_str]
    
    # Fallback: try to identify country from prefix
    if lau_str.startswith("UK"):
        return f"UK-{lau_str}"
    elif lau_str.startswith("ES"):
        return f"Spain-{lau_str}"
    elif lau_str.startswith("FR"):
        return f"France-{lau_str}"
    elif lau_str.startswith("IT"):
        return f"Italy-{lau_str}"
    elif lau_str.startswith("DE"):
        return f"Germany-{lau_str}"
    elif lau_str.startswith("NL"):
        return f"Netherlands-{lau_str}"
    elif lau_str.startswith("BE"):
        return f"Belgium-{lau_str}"
    elif lau_str.startswith("CH"):
        return f"Switzerland-{lau_str}"
    elif lau_str.startswith("SE"):
        return f"Sweden-{lau_str}"
    elif lau_str.startswith("NO"):
        return f"Norway-{lau_str}"
    else:
        return f"Unknown-{lau_str}"


# ALSO UPDATE the country mapping if needed (around line 125)
# This should already be comprehensive, but here it is again:

CIVIC_COUNTRY_MAPPING = {
    # Major European countries
    "ITA": "Italian",
    "FRA": "French",
    "DEU": "German",
    "ESP": "Spanish",
    "GBR": "British",
    "NLD": "Dutch",
    "BEL": "Belgian",
    "CHE": "Swiss",
    "AUT": "Austrian",
    "SWE": "Swedish",
    "NOR": "Norwegian",
    "DNK": "Danish",
    "FIN": "Finnish",
    "IRL": "Irish",
    "PRT": "Portuguese",
    "GRC": "Greek",
    
    # Eastern Europe
    "POL": "Polish",
    "ROU": "Romanian",
    "BGR": "Bulgarian",
    "HUN": "Hungarian",
    "CZE": "Czech",
    "SVK": "Slovak",
    "HRV": "Croatian",
    "SRB": "Serbian",
    "SVN": "Slovenian",
    "LTU": "Lithuanian",
    "LVA": "Latvian",
    "EST": "Estonian",
    
    # Balkans
    "BIH": "Bosnian",
    "ALB": "Albanian",
    "MKD": "Macedonian",
    "MNE": "Montenegrin",
    "KOS": "Kosovar",
    
    # North Africa & Middle East
    "MAR": "Moroccan",
    "DZA": "Algerian",
    "TUN": "Tunisian",
    "EGY": "Egyptian",
    "TUR": "Turkish",
    "IRN": "Iranian",
    "IRQ": "Iraqi",
    "SYR": "Syrian",
    "AFG": "Afghan",
    "LBN": "Lebanese",
    "JOR": "Jordanian",
    "PSE": "Palestinian",
    
    # South Asia
    "PAK": "Pakistani",
    "IND": "Indian",
    "BGD": "Bangladeshi",
    "LKA": "Sri Lankan",
    
    # East Asia
    "CHN": "Chinese",
    "VNM": "Vietnamese",
    "PHL": "Filipino",
    "THA": "Thai",
    "KOR": "Korean",
    "JPN": "Japanese",
    
    # Sub-Saharan Africa
    "NGA": "Nigerian",
    "GHA": "Ghanaian",
    "SEN": "Senegalese",
    "ETH": "Ethiopian",
    "SOM": "Somali",
    "KEN": "Kenyan",
    "ZAF": "South African",
    
    # Americas
    "USA": "American",
    "BRA": "Brazilian",
    "COL": "Colombian",
    "MEX": "Mexican",
    "ARG": "Argentinian",
    "PER": "Peruvian",
    "ECU": "Ecuadorian",
    "CHL": "Chilean",
    
    # Other
    "RUS": "Russian",
    "UKR": "Ukrainian",
    "ISR": "Israeli",
}

# Helper function for country mapping
def map_country_to_group(country_code):
    """Map country code to group name."""
    if pd.isna(country_code):
        return "Unknown"
    
    code = str(country_code).strip().upper()
    return CIVIC_COUNTRY_MAPPING.get(code, f"Other-{code}")



# =============================================================================
# SECTION 4: CIVIC DATA PREPARATION
# =============================================================================
# _prepare_civic_dimensions() adds LOCALMULTIDEM-like columns to the Civic
# raw data (city_full, group_disp, gender, birth_year) so both surveys
# can share the same chart-building code.
# Autochthonous: rorigin==0 or group name in CIVIC_NATIVE_GROUP_NAMES.
#
# CHANGE FOR NEW DATASET — update if column names change (e.g., rgroup,
# rorigin) or coding scheme changes. For a new survey, write a similar
# preparation function.
# =============================================================================
def _prepare_civic_dimensions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add LOCALMULTIDEM-like columns to Civic raw data.

    Produces (when possible):
      - city_full  (from lau_1 via CIVIC_CITY_MAPPING)
      - group_name (from rgroup directly - already human-readable)
      - group_disp (alias of group_name, for consistency)
      - group      (stable integer id per group_name, for compatibility)
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df

    out = df.copy()

    # ---------------------------------------------------------------------
    # Civic → LOCALMULTIDEM-like dimensions
    #   city_full  : human-readable city label derived from lau_1
    #   city       : alias used by existing LOCALMULTIDEM filter logic
    #   group_name : DIRECTLY from rgroup (already human-readable in Civic DTA!)
    #   group_disp : display alias (kept for backwards compatibility)
    #   group      : stable integer id per group_name (compat with older code)
    # ---------------------------------------------------------------------

    # City: lau_1 -> city_full (decoded via CIVIC_CITY_MAPPING)
    if "city_full" not in out.columns:
        if "lau_1" in out.columns:
            out["city_full"] = out["lau_1"].astype(str).map(map_lau_to_city)
            print(f"[_prepare_civic_dimensions] Created city_full from lau_1")
            print(f"  Sample cities: {out['city_full'].value_counts().head(5).to_dict()}")
        else:
            out["city_full"] = "All cities"

    # Many existing LOCALMULTIDEM code paths filter on `city`.
    # For Civic, we alias `city` to `city_full` so the same filter logic works.
    if "city" not in out.columns:
        out["city"] = out["city_full"].astype(str)

    # Group: rgroup (numeric from CSV) -> group_name using CIVIC_GROUP_LABELS
    if "group_name" not in out.columns:
        if "rgroup" in out.columns:
            rg = pd.to_numeric(out["rgroup"], errors="coerce")
            out["group_name"] = rg.map(lambda x: CIVIC_GROUP_LABELS.get(int(x), f"Group {int(x)}") if pd.notna(x) else "Unknown")
            print(f"[_prepare_civic_dimensions] Created group_name from rgroup (numeric -> labels)")
            print(f"  Sample groups: {out['group_name'].value_counts().head(5).to_dict()}")
        elif "country" in out.columns:
            # Fallback to country if rgroup missing
            out["group_name"] = out["country"].map(map_country_to_group)
        else:
            out["group_name"] = "All groups"

    # Display alias used throughout the plotting code
    if "group_disp" not in out.columns:
        out["group_disp"] = out["group_name"].astype(str)

    # Mark autochthonous respondents:
    #  1) rorigin == 0  →  explicitly coded as autochthonous
    #  2) Any respondent whose group name is a native/host-country nationality
    #     (French, British, Italian, Dutch, German, etc.) — regardless of city
    #  3) "comp. group" labels (rgroup 34-37)  →  comparison/native populations
    is_auto = pd.Series(False, index=out.index)

    # (1) rorigin == 0
    if "rorigin" in out.columns:
        is_auto = is_auto | pd.to_numeric(out["rorigin"], errors="coerce").eq(0)

    # (2) All native group names → Autochthonous (uses CIVIC_NATIVE_GROUP_NAMES)
    is_auto = is_auto | out["group_disp"].isin(CIVIC_NATIVE_GROUP_NAMES)

    out["group_disp"] = out["group_disp"].mask(is_auto, "Autochthonous")

    # Numeric group id (useful if any filter logic expects a numeric 'group')
    if "group" not in out.columns:
        try:
            codes, _uniques = pd.factorize(out["group_name"].astype(str), sort=True)
            out["group"] = (codes + 1).astype(int)
        except Exception:
            out["group"] = 1

    # Gender: rgender (0=Female, 1=Male from CSV) -> gender
    if "gender" not in out.columns:
        if "rgender" in out.columns:
            g = pd.to_numeric(out["rgender"], errors="coerce")
            out["gender"] = np.where(g == 1, "Male", np.where(g == 0, "Female", "Other"))
        elif "r1" in out.columns:
            g = pd.to_numeric(out["r1"], errors="coerce")
            out["gender"] = np.where(g == 1, "Male", np.where(g == 2, "Female", "Other"))
        else:
            out["gender"] = "Other"

    # Birth year: r2c -> birth_year
    if "birth_year" not in out.columns:
        if "r2c" in out.columns:
            out["birth_year"] = pd.to_numeric(out["r2c"], errors="coerce")
        else:
            out["birth_year"] = np.nan

    return out



# =============================================================================
# SECTION 5: CATEGORY ORDERING AND LABEL UTILITIES
# =============================================================================
# Controls the order in which answer categories appear on charts (e.g.,
# "Strongly disagree" before "Disagree" before "Neither"...).
# _smart_sort_categories() uses CSV priority, then numeric, then alphabetical.
#
# SAME FOR ANY DATASET — the sorting logic is generic. However, the CSV file
# it reads (localmultidem_category_labels.csv) is specific
# to the current datasets; a new dataset needs a new labels CSV in the same
# format.
# =============================================================================
def _strip_number_prefix(text):
    """
    Remove number prefixes from response labels.
    Handles: "1. ", "01. ", "2) ", "3 - ", "4 "
    """
    if not isinstance(text, str):
        return str(text)
    
    # Pattern matches: digits at start, followed by . ) - or space
    pattern = r'^\d+[\.\)\-\s]+'
    cleaned = re.sub(pattern, '', text.strip())
    
    return cleaned if cleaned else text



def _smart_sort_categories(categories, var=None):
    """
    Sort categories with CSV order as PRIORITY 1.
    """
    # PRIORITY 1: CSV order from Column C
    if var and var in CATEGORY_ORDERS_FROM_CSV:
        csv_order = CATEGORY_ORDERS_FROM_CSV[var]
        sorted_cats = []
        cat_set = set(str(c) for c in categories if c is not None)
        
        # Match categories to CSV order
        for csv_cat in csv_order:
            if csv_cat in cat_set:
                for cat in categories:
                    if str(cat) == csv_cat and cat not in sorted_cats:
                        sorted_cats.append(cat)
                        break
            else:
                # Try matching without number prefix
                for cat in categories:
                    cat_stripped = re.sub(r"^\d+\.\s*", "", str(cat))
                    if cat_stripped == csv_cat and cat not in sorted_cats:
                        sorted_cats.append(cat)
                        break
        
        # Add any remaining categories
        for cat in categories:
            if cat not in sorted_cats and cat is not None:
                sorted_cats.append(cat)
        
        return sorted_cats if sorted_cats else list(categories)
    
    # PRIORITY 2: People concerned variables
    if var in PEOPLE_CONCERNED_VARS:
        sorted_cats = []
        for cat in PEOPLE_CONCERNED_CATEGORY_ORDER:
            if cat in categories:
                sorted_cats.append(cat)
        for cat in categories:
            if cat not in sorted_cats and cat is not None:
                sorted_cats.append(cat)
        return sorted_cats
    
    # PRIORITY 3+: Numbered responses, numeric, alphabetical
    cat_list = [c for c in categories if c is not None and str(c).strip() != ""]
    if not cat_list:
        return []
    
    numbered_pattern = re.compile(r"^(\d+)[\.\)\-\s]+")
    numbered_cats = []
    all_have_numbers = True
    
    for cat in cat_list:
        cat_str = str(cat).strip()
        match = numbered_pattern.match(cat_str)
        if match:
            num = int(match.group(1))
            numbered_cats.append((num, cat))
        else:
            all_have_numbers = False
            break
    
    if all_have_numbers and numbered_cats:
        return [c for _, c in sorted(numbered_cats)]
    
    try:
        numeric_cats = [(float(str(c).strip()), c) for c in cat_list]
        return [c for _, c in sorted(numeric_cats)]
    except (ValueError, TypeError):
        return sorted([str(c) for c in cat_list])


def _add_thermometer_axis_labels_v1(fig, var):
    """DEPRECATED: Use _add_thermometer_axis_labels instead. This is kept for reference."""
    # This function is overridden by the later definition
    return fig

# =============================================================================
# SECTION 6: BRANDING, LOGO, AND CSS
# =============================================================================
# Visual appearance: ETHMIG logo, brand colors, fonts, and global CSS.
# Also contains the questionnaire table reader and the variable exclusion list.
#
# _EXCLUDE_VARS_RAW — CHANGE FOR NEW DATASET (different internal vars to hide)
# Brand colors/logo — CHANGE only if rebranding the application
# Fonts/CSS — SAME unless you want a different look
# =============================================================================
LOGO_PATH = DATA_DIR / "ETHMIG_logo_cmyk.png"
try:
    _logo_bytes = LOGO_PATH.read_bytes()
    LOGO_SRC = "data:image/png;base64," + base64.b64encode(_logo_bytes).decode("ascii")
except Exception:
    
    LOGO_SRC = None

def ethmig_logo(style: dict | None = None):
    """
    Small reusable ETHMIG logo component to place on any page.
    """
    if not LOGO_SRC:
        return html.Div()
    base_style = {
        "height": "64px",
        "marginRight": "12px",
    }
    if style:
        base_style.update(style)
    return html.Img(src=LOGO_SRC, alt="ETHMIG survey data logo", style=base_style)

QUESTION_CSV_PRIMARY  = DATA_DIR / "localmultidem_questionnaire.csv"
QUESTION_CSV_FALLBACK = DATA_DIR / "localmultidem_questionnaire.csv"

def _read_questionnaire_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["ID", "Question"])

    # brunch Excel
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str).fillna("")
        if df.shape[1] >= 2:
            return df.iloc[:, :2].rename(columns={df.columns[0]: "ID", df.columns[1]: "Question"}).fillna("")
        if df.shape[1] == 1:
            out = df.iloc[:, :1].rename(columns={df.columns[0]: "ID"})
            out["Question"] = ""
            return out.fillna("")
        return pd.DataFrame(columns=["ID", "Question"])

   
    import sys, csv as _csv
    _limit = sys.maxsize
    while True:
        try:
            _csv.field_size_limit(_limit)
            break
        except OverflowError:
            _limit = int(_limit / 10)

    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            sample = f.read(4096)
    except Exception:
        with open(path, "r", encoding="latin-1", errors="replace") as f:
            sample = f.read(4096)

    # choice for the divider
    choices = [",", ";", "\t", "|"]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(choices))
        delim = dialect.delimiter
    except Exception:
        if "\t" in sample: delim = "\t"
        elif ";" in sample: delim = ";"
        elif "|" in sample: delim = "|"
        else: delim = ","

    # parsing ID Question
    rows = []
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
            rdr = _csv.reader(f, delimiter=delim, quotechar='"', escapechar="\\")
            for r in rdr:
                if not r or all(str(x).strip() == "" for x in r):
                    continue
                id_ = str(r[0]).strip()
                q   = delim.join(map(str, r[1:])).strip() if len(r) > 1 else ""
                if id_:
                    rows.append((id_, q))
    except Exception as e:
      
        raise SystemExit(f"[ERROR] Could not read questionnaire mapping: {path}\n↳ {e}")

    return pd.DataFrame(rows, columns=["ID", "Question"]).fillna("")

# ▶ Variables to EXCLUDE from the Playground (no visualizations).

_EXCLUDE_VARS_RAW = [
    "Q17DA01","Q17DA01FR","Q17DA02","Q17DA03",
    "Q17DB01","Q17DB01FR","Q17DB02","Q17DB03",
    "Q17DC01","Q17DC01FR","Q17DC02","Q17DC03",
    "Q17DD01","Q17DD01FR","Q17DD02","Q17DD03",
    "Q17DE01","Q17DE01FR","Q17DE02","Q17DE03",
    "Q17DF01","Q17DF01FR","Q17DF01NOR","Q17DF02","Q17DF03",
    "Q17DG01","Q17DG01FR","Q17DG01NOR","Q17DG02","Q17DG03",
    "Q17DH01","Q17DH01FR","Q17DH02","Q17DH03",
    "Q17DI01","Q17DI01FR","Q17DI02","Q17DI03",
    "Q17DJ01","Q17DJ01FR","Q17DJ02","Q17DJ03",
    "Q17DK01","Q17DK01FR","Q17DK02","Q17DK03",
    "Q17DL01","Q17DL01FR","Q17DL02","Q17DL03",
    "Q17DN01","Q17DN01FR","Q17DN02","Q17DN03",
    "Q17DO01","Q17DO01FR","Q17DO02","Q17DO03",
    "Q17DP01","Q17DP01FR","Q17DP02","Q17DP03",
    "Q17DQ01","Q17DQ01FR","Q17DQ02","Q17DQ03",
    "Q17DR01","Q17DR01FR","Q17DR02","Q17DR03",
    "Q17E01","Q17E02","Q17E03","Q17E04","Q17E05","Q17E06","Q17E07","Q17E08","Q17E09",
    "Q17E10","Q17E11","Q17E12","Q17E13","Q17E14","Q17E15","Q17E16","Q17E17","Q17E18 CITY",
    "CNTRY","GROUP",
    "Q7001"
    "Q2"
    "Q3",
    "Q4",
    "Q47",
    "Q702",
    "Q703",
    "Q801",
    "Q802",
    "Q803",
    "Q11",
    "OPT601",
    "OPT602",
    "OPT603",
    "Q12",
    "OPT701",
    "OPT702",
    "OPT703",
    "Q51",
]

# ── Brand palette (from ETHMIGSURVEYDATA Brand Manual) ─────────────────────────
BRAND_GREEN  = "#379E85"  # RGB 55 158 134
BRAND_BLUE   = "#009DE0"  # RGB 0 157 224
BRAND_YELLOW = "#F2E963"  # RGB 242 233 99
BRAND_BLACK  = "#000000"

# Typography (from Brand Manual)
BRAND_FONT_HEADING = "Lato, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
BRAND_FONT_BODY    = "Merriweather, Georgia, 'Times New Roman', serif"

# Cache-buster for assets (increment when updating CSS/fonts)
BRAND_ASSET_VER = "20260126-3"

# Navbar color: choose one brand color (blue/green/yellow)
NAVBAR_BG_COLOR = BRAND_BLUE   # alternatives: BRAND_GREEN or BRAND_YELLOW
# Ensure contrast: yellow needs black text, blue/green use white
NAVBAR_TEXT_COLOR = BRAND_BLACK if NAVBAR_BG_COLOR == BRAND_YELLOW else "#ffffff"

# Global CSS injected into the Dash layout (no assets/ folder needed)
BRAND_GLOBAL_CSS = f"""
/* Typography (ETHMIG brand) */
@import url('https://fonts.googleapis.com/css2?family=Lato:wght@400;700&family=Merriweather:wght@400;700&display=swap');

body {{
  font-family: 'Merriweather', Georgia, 'Times New Roman', serif;
  font-weight: 400;
}}

h1, h2, h3, h4, h5, h6,
.navbar-brand {{
  font-family: 'Lato', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
  font-weight: 700;
}}

/* Navbar background + text */
.navbar, .navbar.navbar-light, .navbar.navbar-expand, .navbar.navbar-expand-lg {{
  background-color: {NAVBAR_BG_COLOR} !important;
}}

.navbar .navbar-brand,
.navbar .navbar-brand:visited,
.navbar .navbar-brand:hover,
.navbar .nav-link,
.navbar .nav-link:visited,
.navbar .nav-link:hover {{
  color: {NAVBAR_TEXT_COLOR} !important;
}}

/* Menu button */
.navbar-toggler {{
  background-color: {BRAND_BLUE} !important;
  border-color: {BRAND_BLUE} !important;
}}

.navbar-toggler-icon {{
  filter: invert(1) brightness(2);
}}

.navbar-toggler:focus,
.navbar-toggler:hover {{
  background-color: {BRAND_BLUE} !important;
  box-shadow: 0 0 0 0.15rem rgba(255,255,255,0.35);
}}
"""

# =============================================================================
# SECTION 7: CHART LAYOUT DEFAULTS AND YES/NO ALIASES
# =============================================================================
# Default formatting for all charts (font sizes, margins, legend, axes).
# Also lists YES_ALIASES and NO_ALIASES (yes/no in many languages) to
# auto-detect binary variables.
#
# SAME FOR ANY DATASET — chart defaults are generic. Only add to the aliases
# if your survey has responses in a language not yet covered.
# =============================================================================
APP_TITLE       = "Data Playground — EMM Survey Data Playground"
AUTOCH_COLOR    = "#777777"
MIN_NONROUTING_N = 25  # Hide bars/boxes with fewer than this many non-routing responses

# ---------------------------------------------------------------------------
# Shared exclusion helpers (used by BOTH Civic and LOCALMULTIDEM callbacks)
# ---------------------------------------------------------------------------
def _compute_exclusion_info(df, var, primary_key, secondary_key):
    """Compute which City×Group units have < MIN_NONROUTING_N valid responses.

    Counts non-routing (>= 0) responses per City×Group for the given variable.
    Units with fewer than 25 valid responses are excluded from the chart and
    listed in the red exclusion message.

    Returns (filtered_df, excluded_units_info_list).
    """
    _excluded = []
    if df.empty or var not in df.columns:
        return df, _excluded
    if primary_key not in df.columns or secondary_key not in df.columns:
        return df, _excluded
    try:
        _val = pd.to_numeric(df[var], errors="coerce")
        _str_val = df[var].astype(str).str.strip()
        _valid_mask = df[var].notna() & (_str_val != "") & (_str_val.str.lower() != "nan")
        # Exclude ALL negative numeric values (routing/sentinel codes)
        _routing_mask = _val < 0
        _valid_mask = _valid_mask & ~_routing_mask
        _unit_label = df[primary_key].astype(str) + " > " + df[secondary_key].astype(str)
        _unit_counts = _unit_label[_valid_mask].value_counts()
        _small = _unit_counts[_unit_counts < MIN_NONROUTING_N]
        if not _small.empty:
            _excluded = [f"{u} (n={int(n)})" for u, n in _small.items()]
            _bad = _unit_label.isin(_small.index)
            df = df[~_bad].copy()
    except Exception:
        pass
    return df, _excluded


def _make_excl_node(excluded_units_info):
    """Build an html.P node with the red exclusion message, or empty string."""
    if not excluded_units_info:
        return ""
    excl_text = (
        f"Excluded (fewer than {MIN_NONROUTING_N} responses): "
        + ", ".join(excluded_units_info)
    )
    return html.P(excl_text, className="excl-msg")


def _append_excl_to_footnote(fnode, excluded_units_info):
    """Append exclusion message to an existing footnote node.

    Returns updated fnode.
    """
    excl_node = _make_excl_node(excluded_units_info)
    if not excl_node:
        return fnode
    if isinstance(fnode, list):
        fnode.append(excl_node)
        return fnode
    elif fnode and fnode != "":
        return html.Div([fnode, excl_node])
    else:
        return excl_node

def _range_is_active(rng, lo_default, hi_default):
    """Return True if a RangeSlider value represents an actual filter (not full range)."""
    if rng is None or rng == []:
        return False
    if isinstance(rng, (list, tuple)) and len(rng) >= 2:
        return float(rng[0]) > float(lo_default) or float(rng[1]) < float(hi_default)
    return False

REQUIRED_RAW    = {"city","group","qtype","q1","q35"}
Q6_MAX_HARD   = 80
YC_LIFE_CODES = {"99","7777"}
# Chart configuration
TITLE_FONT_SIZE = 18
SEP_LINE_COLOR = "rgba(0,0,0,.28)"
SEP_LINE_WIDTH = 1.0
BAR_GAP        = 0.02
BAR_GROUP_GAP  = 0.00
# Scale factors for readability / sizing
# (These apply to bar-type charts. Box plots have their own sizing logic.)
STACKED_TEXT_SCALE = 1.4
HORIZONTAL_HEIGHT_SCALE = 1.8
# Make bars a bit thicker (categorical units)
BAR_TRACE_WIDTH = 0.9  # 10% thinner than 1.20
DEFAULT_ORIENT = "h"  # global default: horizontal charts
# Bigger default layout for ALL non-boxplot bar charts
DEFAULT_BAR_LAYOUT = dict(
    bargap=BAR_GAP,
    bargroupgap=BAR_GROUP_GAP,
    margin=dict(l=64, r=22, t=54, b=150),
    height=600,
    autosize=True,

    # ⬇️ SET TITLE FONT DIRECTLY (prevents duplicate title kwarg)
    title_font=dict(family=BRAND_FONT_HEADING),

    font=dict(size=12),
    transition={"duration": 0},
    xaxis=dict(
        automargin=True,
        tickangle=-25,
        tickfont=dict(size=10),
    ),
    yaxis=dict(
        automargin=True,
        tickfont=dict(size=10),
    ),
    legend=dict(
        orientation="h",
        yanchor="top",
        y=-0.25,
        xanchor="left",
        x=0,
        font=dict(size=10),
    ),
)
def _hbar_compact_height(n_cat: int) -> int:
    return 520
STACK_LABEL_SHOW = True
STACK_LABEL_FMT  = "{pct:.1f}% | n={n}"


YES_ALIASES = {
    "yes","oui","ja","si","sí","evet","да","tak","hai","haii","haa","ye","ya","igen","ano",
    "verdadero","true","agree","oui, tout à fait","плутôt d'accord".replace("плут", "plut") 
}
NO_ALIASES = {
    "no","non","nein","nie","não","нет","hayir","pas du tout","plutôt pas d'accord","false","disagree"
}


# =============================================================================
# SECTION 8: COLORBLIND-SAFE PALETTES
# =============================================================================
# Defines color palettes accessible to people with color vision deficiency.
# Uses the Okabe-Ito palette. Also creates lighter/darker shade variants
# and pattern fills for stacked bars.
#
# SAME FOR ANY DATASET — color palettes are completely generic.
# =============================================================================
# Okabe-Ito palette (color-blind safe)
_OKABE_ITO_BASE = [
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#009E73",  # bluish green
    "#F0E442",  # yellow
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#CC79A7",  # reddish purple
    "#000000",  # black
]


def _add_thermometer_axis_labels(fig, var):
    """Add descriptive labels to thermometer scale plots (0-10, 0-7, etc.)."""
    v_norm = str(var or "").strip().lower()

    # Try THERMOMETER_SCALE_LABELS first, then fallback to SPECTRUM_LABELS
    if v_norm in THERMOMETER_SCALE_LABELS:
        min_label, max_label = THERMOMETER_SCALE_LABELS[v_norm]
    elif v_norm in SPECTRUM_LABELS:
        min_label, max_label = SPECTRUM_LABELS[v_norm]
    else:
        return fig

    # Determine scale range
    if v_norm == "q1301":  # 0-7 scale
        tick_vals = [0, 3.5, 7]
        tick_text = [f"0<br>{min_label}", "Neutral", f"7<br>{max_label}"]
    elif v_norm == "q1308":  # 1-10 scale
        tick_vals = [1, 5.5, 10]
        tick_text = [f"1<br>{min_label}", "Neutral", f"10<br>{max_label}"]
    else:  # 0-10 scale
        tick_vals = [0, 5, 10]
        tick_text = [f"0<br>{min_label}", "5", f"10<br>{max_label}"]

    fig.update_xaxes(
        tickvals=tick_vals,
        ticktext=tick_text,
        tickfont=dict(size=10)
    )

    return fig
# Local helpers for Okabe–Ito palette shade variants

def _shade_hex_local(base_hex: str, l_target: float) -> str:
    """Lighten/darken a hex color by setting HLS lightness to l_target (0..1)."""
    try:
        hx = str(base_hex).lstrip("#")
        r = int(hx[0:2], 16) / 255.0
        g = int(hx[2:4], 16) / 255.0
        b = int(hx[4:6], 16) / 255.0
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        l2 = max(0.0, min(1.0, float(l_target)))
        r2, g2, b2 = colorsys.hls_to_rgb(h, l2, s)
        return "#{:02x}{:02x}{:02x}".format(int(r2 * 255), int(g2 * 255), int(b2 * 255))
    except Exception:
        return str(base_hex)


def _shade_local(base_hex: str, i: int, n: int, l_min: float = 0.35, l_max: float = 0.65) -> str:
    """Generate a stable shade variant of base_hex without relying on global _shade()."""
    try:
        i = max(0, min(int(i), max(0, int(n) - 1)))
        if int(n) <= 1:
            return str(base_hex)
        l_values = np.linspace(float(l_min), float(l_max), int(n))
        return _shade_hex_local(base_hex, float(l_values[i]))
    except Exception:
        return str(base_hex)

def _expand_palette(base: list[str], target_n: int = 15) -> list[str]:
    """Expand a base qualitative palette by generating lightness variants.

    This keeps hues consistent (good for color-blind safety) while providing
    more distinct categories when there are many stacked segments.
    """
    out = list(base)
    if target_n <= len(out):
        return out[:target_n]

    # Add lightness variants 
    variants = []
    for cyc in range(1, 6):
        for col in base:
            if col.lower() == "#000000":
                continue
            # Alternate lighter/darker bands by cycling the lightness window.
            if cyc % 2 == 1:
                variants.append(_shade_local(col, 0, 2, l_min=0.55, l_max=0.78))  # lighter
            else:
                variants.append(_shade_local(col, 0, 2, l_min=0.28, l_max=0.45))  # darker
            if len(out) + len(variants) >= target_n:
                break
        if len(out) + len(variants) >= target_n:
            break

    out.extend(variants)
    return out[:target_n]

# Public palette used by stacked bars
OKABE_ITO = _expand_palette(_OKABE_ITO_BASE, target_n=15)
STACK_PATTERN_SHAPES = ["", ".", "/", "\\", "x", "-", "|", "+", "o", "*"]
# Toggle patterns on/off (colors always apply for stacked bars)
USE_STACK_PATTERNS = True

def _stack_accessibility_maps(levels: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Return (color_map, pattern_map) for stacked-bar categories."""
    lvls = [str(x) for x in levels]
    cmap = {lvl: OKABE_ITO[i % len(OKABE_ITO)] for i, lvl in enumerate(lvls)}
    pmap = {lvl: STACK_PATTERN_SHAPES[i % len(STACK_PATTERN_SHAPES)] for i, lvl in enumerate(lvls)}
    return cmap, pmap

def _apply_stack_accessibility(fig: go.Figure) -> None:
    """Apply color-blind-safe colors + optional patterns to stacked-bar-like figures."""
    try:
        levels = [str(t.name) for t in fig.data if getattr(t, "name", None) is not None]
        levels = list(dict.fromkeys(levels))
        cmap, pmap = _stack_accessibility_maps(levels)

        for t in fig.data:
            nm = str(getattr(t, "name", ""))
            if nm in cmap:
                try:
                    t.marker.color = cmap[nm]
                except Exception:
                    pass
            if USE_STACK_PATTERNS:
                try:
                    t.marker.pattern = dict(shape=pmap.get(nm, ""), solidity=0.35)
                except Exception:
                    pass

        # Subtle borders so segments don’t melt together
        try:
            fig.update_traces(marker_line_width=0.6, marker_line_color="rgba(0,0,0,0.45)")
        except Exception:
            pass
    except Exception:
        pass
# =============================================================================
# SECTION 9: SPECIAL VARIABLE SETS
# =============================================================================
# Groups of variables that get special chart types (instead of default stacked
# bar): timeline line charts, pre-selected ready-made graphs, or region
# heatmaps.
#
# CHANGE FOR NEW DATASET — these lists contain LOCALMULTIDEM variable names.
# Replace with your variable names if your data is different.
# =============================================================================
TIME_LINE_VARS = {"q2", "q4"}  # Q2 = Year of birth, Q4 = Year of arrival
READYMADE_VARS = ["q1604", "q24c07", "q24a11", "q3704", "q2302", "q33"]

REGION_HEATMAP_VARS = {
    "q3",      # country of birth (respondent)
    "q7001", "q702", "q703",      # 1st, 2nd, 3rd citizenship (current)
    "q801", "q802", "q803",       # citizenship at birth (respondent)
    "q11",                         # mother's country of birth
    "opt601", "opt602", "opt603", # mother's citizenship at birth
    "q12",                         # father's country of birth
    "opt701", "opt702", "opt703", # father's citizenship at birth
}


# =============================================================================
# SECTION 10: COUNTRY AND REGION MAPPING
# =============================================================================
# Maps country names/ISO codes to world regions (Europe, Asia, Americas,
# Africa, Oceania). Used for region heatmap charts.
# Tries to load country_region_map.csv; falls back to hardcoded dictionary.
#
# SAME FOR ANY DATASET — universal mapping. You might need to add new
# countries if your data includes ones not in the current list.
# =============================================================================

COUNTRY_REGION_CSV = DATA_DIR / "country_region_map.csv"

_FALLBACK_COUNTRY_REGION_MAP = {
    
    "FR": "Europe",
    "GB": "Europe", "UK": "Europe",
    "IT": "Europe",
    "ES": "Europe",
    "HU": "Europe",
    "CH": "Europe",
    "SE": "Europe",
    "NO": "Europe",
    "TR": "Asia",
    "MA": "Africa",
    "DZ": "Africa",
    "TN": "Africa",
    "EG": "Africa",
    "PK": "Asia",
    "BD": "Asia",
    "IN": "Asia",
    "CN": "Asia",
    "PH": "Asia",
    "EC": "Americas",
    "BO": "Americas",
    "CL": "Americas",
    "VE": "Americas",
}

def _load_country_region_map() -> dict[str, str]:
    """
   
    Expected CSV structure:
      • Name   
      • Code   
      • Region (broad region label; if missing, we fall back to a minimal built-in map)
    """
    if not COUNTRY_REGION_CSV.exists():
        return _FALLBACK_COUNTRY_REGION_MAP.copy()
    try:
        # Use robust CSV reader 
        df = _read_csv_salvage(COUNTRY_REGION_CSV)
        # Normalize column names
        cols = {str(c).strip().lower(): c for c in df.columns}
        code_col = cols.get("code")
       
        region_col = cols.get("region")

        if not code_col:
            warnings.warn(
                f"[WARN] country_region_map.csv should have a 'Code' column; got {list(df.columns)}"
            )
            return _FALLBACK_COUNTRY_REGION_MAP.copy()

        if not region_col:
            
            warnings.warn(
                "[WARN] country_region_map.csv has no 'Region' column; "
                "using built-in fallback mapping for regions."
            )
            return _FALLBACK_COUNTRY_REGION_MAP.copy()

        df = df[[code_col, region_col]].dropna()
        mapping: dict[str, str] = {}
        for _, r in df.iterrows():
            cc = str(r[code_col]).strip().upper()
            reg = str(r[region_col]).strip()
            if len(cc) == 2 and cc.isalpha() and reg:
                mapping[cc] = reg

       
        return mapping or _FALLBACK_COUNTRY_REGION_MAP.copy()
    except Exception as e:
        _log_exc(e, where="load_country_region_map")
        return _FALLBACK_COUNTRY_REGION_MAP.copy()


def _country_code_to_region(code: str) -> str:
    s = str(code or "").strip()
    if s == "":
        return "Missing"

    # DK
    if s in {"8", "88", "8888"}:
        return "DK"
    if s in {"9", "99", "9999"}:
        return "Refusal"

    # Negative
    try:
        iv = int(s)
        if iv < 0:
            return "Routing / Not asked"
    except Exception:
        pass

    # Proper 2-letter ISO alpha-2 country code
    if len(s) == 2 and s.isalpha():
        s_up = s.upper()
        return COUNTRY_REGION_MAP.get(s_up, "Other / Unknown")

  
    return "Other / Unknown"

def sentence_case(s: str) -> str:
    """Первую букву — в верхний регистр, остальное — как есть; пустые строки возвращаются как есть."""
    s = str(s or "").strip().lower()
    return s[:1].upper() + s[1:] if s else s

def _city_key(s: str) -> str:
    """Ключ нормализации города: только латинские буквы, нижний регистр. Нужен для маппинга сокращений."""
    return re.sub(r"[^A-Za-z]", "", str(s)).lower()
# =============================================================================
# SECTION 11: REGION HEATMAP CHARTS
# =============================================================================
# build_region_heatmap() creates a heatmap showing respondents' countries of
# origin grouped by world region. Rows = cities/groups, columns = regions.
#
# SAME FOR ANY DATASET — generic visualization that works with any data
# having country-related variables.
# =============================================================================
def build_region_heatmap(
    df: pd.DataFrame,
    var: str,
    axis: str = "city",
):
    """
    Build a region-by-city or region-by-group heatmap for country-of-birth
    and citizenship variables.

    • df: already-filtered raw slice (city/group/gender/migration filters applied)
    • var: one of REGION_HEATMAP_VARS (case-insensitive)
    • axis: "city" → rows are cities; "group" → rows are group_name
    """
    v = str(var or "").strip().lower()
    # Guard: if filters (e.g., Born in interview country) leave no rows, return a friendly empty figure.
    if df is None or (hasattr(df, "empty") and df.empty):
        fig = go.Figure()
        fig.update_layout(
            template="plotly_white",
            height=520,
            margin=dict(l=60, r=30, t=70, b=60),
            title={"text": "No data for this filter combination", "x": 0.5, "xanchor": "center"},
        )
        fig.add_annotation(
            text="No respondents remain after applying the current filters.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            align="center",
            font=dict(size=14),
        )
        empty_df = pd.DataFrame()
        return fig, empty_df

    try:
        if v not in df.columns:
            fig = px.imshow([[0]], labels=dict(color="Share (%)"))
            fig.update_layout(title=f"No data for {var}")
            return fig, pd.DataFrame(columns=["row", "region", "pct"])

        df_use = df.copy()
        df_use["region"] = df_use[v].astype(str).map(_country_code_to_region)

        drop_regions = {"Routing / Not asked", "DK", "Refusal", "Missing"}
        df_use = df_use[~df_use["region"].isin(drop_regions)].copy()
        if df_use.empty:
            fig = px.imshow([[0]], labels=dict(color="Share (%)"))
            fig.update_layout(title=f"No substantive responses for {var}")
            return fig, pd.DataFrame(columns=["row", "region", "pct"])

        if axis == "group":
            row_dim = "group_name"
        else:
            row_dim = "city_full"

        if row_dim not in df_use.columns:
            row_dim = None

        if row_dim is None:
            g = df_use.groupby("region", dropna=False).size().reset_index(name="n")
            total = float(g["n"].sum())
            g["pct"] = g["n"] / total * 100.0
            g["row"] = "All respondents"
        else:
            g = (
                df_use.groupby([row_dim, "region"], dropna=False)
                .size()
                .reset_index(name="n")
            )
            g["total_row"] = g.groupby(row_dim)["n"].transform("sum")
            g["pct"] = g["n"] / g["total_row"].where(g["total_row"] > 0, np.nan) * 100.0
            g = g.drop(columns=["total_row"])
            g = g.rename(columns={row_dim: "row"})

        g = g.replace([np.inf, -np.inf], np.nan).dropna(subset=["pct"])
        if g.empty:
            fig = px.imshow([[0]], labels=dict(color="Share (%)"))
            fig.update_layout(title=f"No usable data for {var}")
            return fig, pd.DataFrame(columns=["row", "region", "pct"])

        pivot = (
            g.pivot(index="row", columns="region", values="pct")
            .fillna(0.0)
            .sort_index(axis=0)
            .sort_index(axis=1)
        )

        fig = px.imshow(
            pivot,
            aspect="auto",
            labels=dict(x="Region", y="City / Group", color="Share of respondents (%)"),
        )

        label_key = v.strip().lower()
        nice_label = dict_labels.get(label_key, var.upper())

        fig.update_layout(
            title={
                "text": nice_label,
                "x": 0.5,
                "xanchor": "center",
            },
            xaxis_side="top",
            transition={"duration": 0},
        )
        return fig, g.reset_index(drop=True)
    except Exception as e:
        _log_exc(e, where="draw_figure")

        # Always return a valid Plotly figure so Dash doesn't crash the callback.
        fig = go.Figure()
        fig.update_layout(
            template="plotly_white",
            height=520,
            margin=dict(l=60, r=30, t=70, b=60),
            title={"text": "Error while drawing figure", "x": 0.5, "xanchor": "center"},
        )
        fig.add_annotation(
            text=(
                "This filter combination produced no usable data or triggered a plotting error.<br>"
                "Try widening filters (e.g., select ‘No filter’) or choose another variable."
            ),
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            align="center",
            font=dict(size=14),
        )

        # IMPORTANT: Never return None for multi-output callbacks.
        # Preserve the callback's expected return shape by returning safe defaults.
        # If the callback returns (figure, table) -> return (fig, empty_df)
        # If it returns (figure, table, something_else) -> return (fig, empty_df, no_update)
        empty_df = pd.DataFrame()
        return fig, empty_df

# =============================================================================
# SECTION 12: TIMELINE CHARTS
# =============================================================================
# build_time_line_area() creates line charts for year-based variables (e.g.,
# year of birth, year of arrival). One line per group showing distribution.
#
# SAME FOR ANY DATASET — works with any numeric year-type variable.
# =============================================================================
def build_time_line_area(df: pd.DataFrame, var: str, title: str | None = None):
    """
    For time-like variables (e.g. Year of birth, Year of arrival):
    draw a multi-line chart (one line per group_name) showing the distribution of
    years among the CURRENTLY FILTERED respondents.

    Each line is scaled within its group (percent of that group's respondents).
    Returns (fig, table_df), where table_df has columns [group_name, year, n, pct].
    """
    v = str(var or "").strip().lower()
    if v not in df.columns:
        fig = px.line(title=f"No data for {var}")
        return fig, pd.DataFrame(columns=["group_name", "year", "n", "pct"])

    # Numeric year values
    s = pd.to_numeric(df[v], errors="coerce")

    # Keep a reasonable range to exclude obvious mis-codes
    mask = (s >= 1900) & (s <= 2100)
    if not mask.any():
        fig = px.line(title=f"No valid values for {var}")
        return fig, pd.DataFrame(columns=["group_name", "year", "n", "pct"])

    df_year = df.loc[mask].copy()
    df_year["year"] = s[mask].astype(int)

    
    if "group_name" not in df_year.columns:
        df_year["group_name"] = "All respondents"

    
    counts = (
        df_year.groupby(["group_name", "year"], dropna=False)
        .size()
        .reset_index(name="n")
    )

    # group percentages
    counts["total_group"] = counts.groupby("group_name")["n"].transform("sum")
    counts["pct"] = counts["n"] / counts["total_group"].where(counts["total_group"] > 0, np.nan) * 100.0
    counts = counts.drop(columns=["total_group"])
    counts = counts.replace([np.inf, -np.inf], np.nan).dropna(subset=["pct"])

    if counts.empty:
        fig = px.line(title=f"No usable values for {var}")
        return fig, pd.DataFrame(columns=["group_name", "year", "n", "pct"])

    # label for title
    label_key = v.strip().lower()
    nice_label = dict_labels.get(label_key, var.upper())
    if not title:
        title = nice_label

   
    try:
        cmap = _group_color_map_for(counts["group_name"])
    except Exception:
        cmap = None

    fig = px.line(
        counts,
        x="year",
        y="pct",
        color="group_name",
        color_discrete_map=(cmap or None),
    )
    fig.update_traces(
        mode="lines",
        line={"width": 2},
        hovertemplate="Year %{x}<br>%{y:.1f}% of respondents in %{fullData.name}<extra></extra>",
    )
    fig = px.line(
        counts,
        x="year",
        y="pct",
        color="group_name",
        color_discrete_map=(cmap or None),
    )
    fig.update_traces(
        mode="lines",
        line={"width": 2},
        hovertemplate="Year %{x}<br>%{y:.1f}% of respondents in %{fullData.name}<extra></extra>",
    )
    fig.update_layout(
        title={"text": title, "x": 0.5, "xanchor": "center"},
        xaxis_title="Year",
        yaxis_title="Share of respondents within group (%)",
        uniformtext_minsize=9,
        uniformtext_mode="hide",
        transition={"duration": 0},
        yaxis=dict(range=[0, 10]),
    )

    table_df = (
        counts[["group_name", "year", "n", "pct"]]
        .sort_values(["group_name", "year"])
        .reset_index(drop=True)
    )
    return fig, table_df


# =============================================================================
# SECTION 13: CITY NAME MAPPING
# =============================================================================
# Standardizes city names so the same city always has the same display name.
# CITY_FULL_MAP maps coded city names -> display names.
# to_city_full() converts any variant to its standard form.
#
# CHANGE FOR NEW DATASET — add your cities to CITY_FULL_MAP if they are
# different. The function logic stays the same.
# =============================================================================
CITY_FULL_MAP_RAW = {
    "Bar": "Barcelona",
    "Bud": "Budapest",
    "Gen": "Geneva",
    "LON": "London",
    "Lyo": "Lyon",
    "Mad": "Madrid",
    "Mil": "Milano",
    "Osl": "Oslo",
    "Sto": "Stockholm",
    "Zur": "Zurich",
    "Tur": "Turin",
}

CITY_FULL_MAP: dict[str, str] = {}
for k, v in CITY_FULL_MAP_RAW.items():
    CITY_FULL_MAP[_city_key(k)] = v
    CITY_FULL_MAP[_city_key(v)] = v

def to_city_full(x) -> str:
    """Преобразует любое представление города к "красивому" полному названию."""
    if pd.isna(x): return x
    key = _city_key(x)
    if key in CITY_FULL_MAP: return CITY_FULL_MAP[key]
    s = str(x).strip()
    return s.replace("_"," ").replace("-", " ").title()

# =============================================================================
# SECTION 14: AUTOCHTHONOUS (NATIVE) GROUP HANDLING
# =============================================================================
# Identifies respondents who are "native" to their survey city (e.g., French
# in Lyon). NATIVE_BY_CITY maps each city to its native group name(s).
# _is_native_pair() checks if a city-group pair is autochthonous.
#
# CHANGE FOR NEW DATASET — update NATIVE_BY_CITY if you add new cities or
# the native groups are different. This is CRITICAL for autochthonous to work.
# =============================================================================
NATIVE_BY_CITY: dict[str, set[str]] = {
    "London": {"British"},
    "Lyon": {"French"},
    "Stockholm": {"Swedish"},
    "Budapest": {"Hungarian"},
    "Zurich": {"Swiss"},
    "Geneva": {"Swiss"},
    "Oslo": {"Norwegian"},
    "Milano": {"Italian", "Italian "},
    "Barcelona": {"Spanish"},
    "Madrid": {"Spanish"},
    "Turin": {"Italian"},
}

def _is_native_pair(city_full: str, group_name: str) -> bool:
    try:
        city_full = to_city_full(city_full)
        g = str(group_name).strip().casefold()
        natives = {x.strip().casefold() for x in NATIVE_BY_CITY.get(city_full, set())}
        return g in natives
    except Exception:
        return False
    

# =============================================================================
# SECTION 15: GROUP COLOR PALETTE SYSTEM
# =============================================================================
# Assigns a stable, distinctive color to each immigrant group across all
# charts. Groups from the same world region get similar hues.
# GROUP_NAMES maps group codes to names, GROUP_REGIONS to world regions.
# build_group_palette() creates the complete color mapping.
#
# CHANGE FOR NEW DATASET — update GROUP_NAMES and GROUP_REGIONS if you have
# different groups or regional assignments. The color logic is generic.
# =============================================================================
COLORS_REGIONS = {"Europe":"#F1C40F","Asia":"#27AE60","Americas":"#2980B9","Africa":"#E74C3C"}
COLOR_OTHER = "#95A5A6"
GROUP_NAMES = {
     1:"French", 2:"British", 3:"Italian", 4:"Hungarian", 5:"Swiss", 6:"Spanish",
     7:"Ethnic Hungarian", 8:"Kosovar", 9:"Turk", 10:"Moroccan", 11:"Pakistani",
    12:"Bangladeshi", 13:"Algerian", 14:"Tunisian", 15:"Egyptian", 16:"Philippine",
    17:"Ecuadorian", 18:"Indian", 19:"Chinese", 20:"Caribbean",
    21:"Andean Latin American", 22:"Mixed Muslim", 23:"Norwegian", 24:"Bosnian",
    25:"Mixed race British", 26:"Swedish", 27:"Chilean"
}
GROUP_REGION = {
     1:'Europe',2:'Europe',3:'Europe',4:'Europe',5:'Europe',6:'Europe',
     7:'Europe',8:'Europe',9:'Asia',10:'Africa',11:'Asia',12:'Asia',
    13:'Africa',14:'Africa',15:'Africa',16:'Asia',17:'Americas',18:'Asia',
    19:'Asia',20:'Americas',21:'Americas',22:'Asia',23:'Europe',24:'Europe',
    25:'Europe',26:'Europe',27:'Americas'
}


def _hex_to_hls(hex_color: str):
    """#RRGGBB → (h, l, s) в [0..1]."""
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16)/255.0
    g = int(hex_color[2:4], 16)/255.0
    b = int(hex_color[4:6], 16)/255.0
    return colorsys.rgb_to_hls(r, g, b)

def _hls_to_hex(h: float, l: float, s: float) -> str:
    """(h, l, s) → #RRGGBB."""
    r,g,b = colorsys.hls_to_rgb(h, l, s)
    return "#{:02x}{:02x}{:02x}".format(int(r*255), int(g*255), int(b*255))

def _shade(base_hex: str, i: int, n: int, l_min: float=0.35, l_max: float=0.65) -> str:
  
    i = max(0, min(int(i), max(0, n-1)))
    h, l, s = _hex_to_hls(base_hex)
    if n <= 1: return base_hex
    l_values = np.linspace(l_min, l_max, n)
    return _hls_to_hex(h, float(l_values[i]), s)

def _stable_index(key: str, n: int) -> int:

    if n <= 1: return 0
    h = hashlib.md5(key.encode("utf-8", errors="ignore")).hexdigest()
    return int(h[:8], 16) % n




REGION_QUAL_PALETTES: dict[str, list[str]] = {
    # Yellow/orange family (high contrast within family)
    "Europe": [
        "#b15928", "#e6ab02", "#ffd92f", "#fdbf6f", "#ff7f00", "#fb9a99",
        "#cab2d6", "#6a3d9a", "#ffff99", "#d95f02",
    ],
    # Greens/teals
    "Asia": [
        "#1b9e77", "#66a61e", "#a6d854", "#00a087", "#4daf4a", "#2ca25f",
        "#8dd3c7", "#7fc97f", "#4dbbd5", "#00bfc4",
    ],
    # Blues/purples
    "Americas": [
        "#1f78b4", "#377eb8", "#4e79a7", "#6baed6", "#3182bd", "#756bb1",
        "#9ecae1", "#807dba", "#a6cee3", "#8da0cb",
    ],
    # Reds/magentas
    "Africa": [
        "#e31a1c", "#fb6a4a", "#ef3b2c", "#f781bf", "#d62728", "#c51b8a",
        "#e41a1c", "#ff9896", "#b2182b", "#dd1c77",
    ],
}


def build_group_palette() -> dict[str, str]:
    """Return a mapping group_name -> color.

    Design goals:
      - groups within the same continent are clearly distinguishable
      - continents still look like different "families" (Europe warm, Asia green, Americas blue, Africa red)
      - stable assignment (order determined by GROUP_REGION / GROUP_NAMES)
    """
    out: dict[str, str] = {}

    for region in ["Europe", "Asia", "Americas", "Africa"]:
        ids_in_region = [gid for gid, reg in GROUP_REGION.items() if reg == region]
        names_in_region = [GROUP_NAMES[gid] for gid in sorted(ids_in_region)]
        if not names_in_region:
            continue

        pal = REGION_QUAL_PALETTES.get(region, [])
        base = COLORS_REGIONS.get(region, COLOR_OTHER)

        for i, gname in enumerate(names_in_region):
            if pal:
                # palette colors first
                col = pal[i % len(pal)]
                cyc = i // len(pal)
                if cyc > 0:
                    col = _shade(col, cyc, cyc + 2, l_min=0.35, l_max=0.70)
            else:
                
                n = max(1, len(names_in_region))
                col = _shade(base, i, n)

            out[gname] = col

    return out



GROUP_COL = build_group_palette()

GROUP_NAME_TO_REGION = {GROUP_NAMES[i]: GROUP_REGION[i] for i in GROUP_NAMES.keys() if i in GROUP_REGION}

def _group_color_for(name: str) -> str:
   
    name = str(name or "").strip()
    if name in GROUP_COL:
        return GROUP_COL[name]
    region = GROUP_NAME_TO_REGION.get(name, None)
    base = COLORS_REGIONS.get(region, COLOR_OTHER)
    return base

def _group_color_map_for(values_iterable) -> dict[str, str]:
   
    names = [str(v) for v in pd.Series(list(values_iterable)).dropna().astype(str).unique().tolist()]
    cmap: dict[str, str] = {}
    by_region: dict[str, list[str]] = {}
    for nm in names:
        reg = GROUP_NAME_TO_REGION.get(nm, "OTHER")
        by_region.setdefault(reg, []).append(nm)
    for reg, nms in by_region.items():
        base = COLORS_REGIONS.get(reg, COLOR_OTHER)
        n = max(1, len(nms))
        for i, nm in enumerate(sorted(nms)):
            cmap[nm] = _shade(base, i, n)
   
    if "Autochthonous" in names:
        cmap["Autochthonous"] = AUTOCH_COLOR
    return cmap


PRECOOKED_GROUP_COL = GROUP_COL.copy()
PRECOOKED_GROUP_COL["Autochthonous"] = AUTOCH_COLOR

def _build_high_contrast_group_palette(names: list[str]) -> dict[str, str]:
    """
    alternative palette
    """
    phi = 0.6180339887498949
    h = 0.11
    ring = []
    for _ in range(64):
        h = (h + phi) % 1.0
        ring.append(_hls_to_hex(h, 0.48, 0.85))
    ordered = sorted(names, key=lambda n: _stable_index(n, 2**31-1))
    return {name: ring[i % len(ring)] for i, name in enumerate(ordered)}

# =============================================================================
# SECTION 16: BOX PLOT AND NUMERIC VARIABLE CONFIGURATION
# =============================================================================
# Defines which variables are shown as box plots, which are forced to
# categorical bars, and scale endpoint labels (e.g., 0="Very negative",
# 10="Very positive"). Also includes scale heatmap color gradient builder.
#
# CHANGE FOR NEW DATASET — the variable names in these sets are all
# LOCALMULTIDEM-specific. Replace with your variable names. Civic variables
# are configured separately in survey_civic.py (VAR_CONFIG dictionary).
# =============================================================================
BOXPLOT_NUMERIC_VARS = {
    #  rendered as numeric/median box plots
    "q33", "q34", "q1302", "q2302", "q2304",
    "q3601", "q3602", "q3603", "q3604", "q3606", "q3608", "q3609",
    "q3610", "q3611", "q3612",
    "q3701", "q3702", "q3703", "q3704", "q3705", "q3706", "q3707", "q3708", "q3709",
    "q45", "3709"

    # these variables to be box plots regardless of letter case
    "q1301", "q35", "q1308", "opt36", "opt37", "opt8",
    "q3605", "q3607",

    # (they will only matter if such columns actually exist in the data)
    "q370q35", "q13083",
    "q1301",  # Attachment to same religion (0-7 scale)
    "q1308",  # Attachment to ethnic group (1-10 scale)
    "q3301",  # Society has negative attitude towards immigrants (0-10)
    "q3302",  # Society has negative attitude - Moroccans (0-10)
    "q3303",  # Society has negative attitude - Turks (0-10)
    "q3304",  # Society has negative attitude - ex-Yugoslavs (0-10)
    "q3305",  # Society has negative attitude - Ecuadorians (0-10)
    "q3306",  # Society has negative attitude - Romanians (0-10)
    "q3307",  # Society has negative attitude - Pakistanis (0-10)
}

# Variables that MUST display as categorical bar charts (not curves)
FORCE_CATEGORICAL_BARS = {
    "q1604",  # Interest in election under study (4 categories)
    "q1605",  # Interest in politics host country (4 categories)
    "q1606",  # Interest in politics homeland (4 categories)
    "q1607",  # Interest in politics in general (4 categories)
}

# Fixed category order for "People concerned" variables to ensure consistency
PEOPLE_CONCERNED_CATEGORY_ORDER = [
    "Only my ethnic group",
    "My ethnic group and other groups in this country",
    "All people in this country",
    "All people in Europe",
    "Whole world",  # Note: Fixed typo from "whols world"
]

PEOPLE_CONCERNED_VARS = {
    "q24c01", "q24c02", "q24c03", "q24c04", "q24c05", "q24c06",
    "q24c07", "q24c08", "q24c09", "q24c10", "q24c11", "q24c12",
}

THERMOMETER_SCALE_LABELS = {
    "q34": ("Can't be too careful (0)", "Most people can be trusted (10)"),
    "q35": ("Can't be too careful (0)", "Most people can be trusted (10)"),
    "q3301": ("Not negative at all (0)", "Very negative (10)"),
    "q3302": ("Not negative at all (0)", "Very negative (10)"),
    "q3303": ("Not negative at all (0)", "Very negative (10)"),
    "q3304": ("Not negative at all (0)", "Very negative (10)"),
    "q3305": ("Not negative at all (0)", "Very negative (10)"),
    "q3306": ("Not negative at all (0)", "Very negative (10)"),
    "q3307": ("Not negative at all (0)", "Very negative (10)"),
    "q1301": ("Not at all attached (0)", "Very attached (7)"),
    "q1308": ("Not at all attached (1)", "Very attached (10)"),
}


BOXPLOT_NUMERIC_VARS = {str(v).strip().lower() for v in BOXPLOT_NUMERIC_VARS}

HEATMAP_STACK_VARS: set[str] = set()
def _build_scale_heatmap_colors(levels: list[str]) -> dict[str, str]:
    """
    Build a green → yellow → red → violet heatmap for ordered scale categories.

    The first level in `levels` gets green, the last gets violet, with a smooth
    gradient in between passing through yellow and red.
    """
    anchors = [
        (0.0,     (0.0, 0.6, 0.0)),   # green
        (1.0/3.0, (1.0, 1.0, 0.0)),   # yellow
        (2.0/3.0, (1.0, 0.0, 0.0)),   # red
        (1.0,     (0.5, 0.0, 0.5)),   # violet
    ]

    def _interp(c1, c2, t_rel: float):
        return tuple(c1[i] + (c2[i] - c1[i]) * t_rel for i in range(3))

    def _to_hex(rgb):
        r, g, b = (max(0, min(1, float(x))) for x in rgb)
        return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

    n = len(levels)
    if n <= 1:
        
        return {str(levels[0]): "#009966"} if n == 1 else {}

    out: dict[str, str] = {}
    for idx, level in enumerate(levels):
        t = idx / (n - 1)  
        
        for (t0, c0), (t1, c1) in zip(anchors[:-1], anchors[1:]):
            if t <= t1 or t1 == 1.0:
                span = t1 - t0 if t1 > t0 else 1.0
                t_rel = (t - t0) / span if span > 0 else 0.0
                rgb = _interp(c0, c1, t_rel)
                out[str(level)] = _to_hex(rgb)
                break
    return out

# =============================================================================
# SECTION 17: FILE READING UTILITIES
# =============================================================================
# Robust functions for reading CSV/TSV files with multiple fallback strategies
# (encoding, delimiter, engine). Also _icloud_touch() waits for iCloud files
# on macOS.
#
# SAME FOR ANY DATASET — these are generic file-reading utilities that work
# with any CSV/TSV file.
# =============================================================================
def _icloud_touch(p: Path, min_bytes=128, settle_checks=3, settle_sleep=0.5):

    last = -1
    for i in range(6):
        try:
            if not p.exists(): raise SystemExit(f"[ERROR] Missing file: {p}")
            with open(p, "rb") as f:
                if not f.read(max(min_bytes,1)):
                    time.sleep(0.6*(i+1)); continue
            stable = True
            for _ in range(settle_checks):
                sz = p.stat().st_size
                if last != -1 and sz != last: stable = False
                last = sz; time.sleep(settle_sleep)
            if stable and last >= min_bytes: return
        except (TimeoutError, OSError) as e:
            if isinstance(e, TimeoutError) or getattr(e, "errno", None) in {errno.ECANCELED, errno.EAGAIN, errno.EPERM, errno.ETIMEDOUT, 60}:
                time.sleep(0.6*(i+1)); continue
            raise

def _sniff_delimiter_text(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text).delimiter
    except Exception:
        if "\t" in text: return "\t"
        if ";" in text:  return ";"
        if "|" in text:  return "|"
        return ","

def _sniff_delimiter_file(path: Path) -> str:
   
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        sample = f.read(10000)
    return _sniff_delimiter_text(sample)

def _read_csv_c_first(path: Path, sep_hint: str|None=None) -> pd.DataFrame:
  
    sep = sep_hint or _sniff_delimiter_file(path)
    try:
        return pd.read_csv(path, engine="c", sep=sep, encoding="utf-8",
                           low_memory=False, on_bad_lines="skip", dtype=str)
    except UnicodeDecodeError:
        pass
    except Exception:
        try:
            return pd.read_csv(path, engine="c", sep=sep, encoding="utf-8",
                               low_memory=False, dtype=str)
        except UnicodeDecodeError:
            pass
    try:
        return pd.read_csv(path, engine="c", sep=sep, encoding="latin-1",
                           low_memory=False, on_bad_lines="skip", dtype=str)
    except Exception:
        try:
            return pd.read_csv(path, engine="c", sep=sep, encoding="latin-1",
                               low_memory=False, dtype=str)
        except Exception:
            pass
    try:
        return pd.read_csv(path, engine="python", sep=sep, encoding="utf-8",
                           on_bad_lines="skip", dtype=str)
    except UnicodeDecodeError:
        return pd.read_csv(path, engine="python", sep=sep, encoding="latin-1",
                           on_bad_lines="skip", dtype=str)

def _read_csv_salvage(path: Path) -> pd.DataFrame:
  
    _icloud_touch(path)
    last_err = None
    try:
        return _read_csv_c_first(path)
    except Exception as e:
        last_err = e
    try:
        if path.suffix.lower() in {".xlsx",".xls"}:
            import openpyxl
            df_x = pd.read_excel(path, engine="openpyxl", dtype=str)
            df_x.columns = [str(c).strip().lower() for c in df_x.columns]
            return df_x
    except Exception as e:
        last_err = e
    try:
        with open(path, "rb") as f: raw = f.read()
        raw = raw.replace(b"\x00", b"")  
        raw = re.sub(br"[^\x09\x0A\x0D\x20-\x7E\xC2-\xF4][\x80-\xBF]?", b"", raw)
        text = None
        for enc in ("utf-8","utf-8-sig","latin-1"):
            try: text = raw.decode(enc, errors="replace"); break
            except Exception: continue
        if text is None: text = raw.decode("utf-8", errors="replace")
        sep = _sniff_delimiter_text(text[:10000])
        tmp = io.StringIO(text)
        df_tmp = pd.read_csv(tmp, sep=sep, engine="python",
                             on_bad_lines="skip", dtype=str)
        df_tmp.columns = [str(c).strip().lower() for c in df_tmp.columns]
        return df_tmp
    except Exception as e:
        last_err = e
    raise SystemExit(f"[ERROR] Cannot read (even lenient): {path}\n↳ Last error: {last_err}")

# Initialize COUNTRY_REGION_MAP
COUNTRY_REGION_MAP = _load_country_region_map()

# =============================================================================
# SECTION 18: COLUMN NORMALIZATION
# =============================================================================
# Standardizes column names: "City", "CITY", " city " all become "city".
#
# SAME FOR ANY DATASET — generic utility.
# =============================================================================
def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase and strip whitespace from all column names."""
    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    return out

def _norm_varname(s: str) -> str:
    """
    Normalize a variable name for comparisons:
      • lowercase
      • strip edges
      • remove all internal whitespace
    """
    return re.sub(r"\s+", "", str(s or "").strip().lower())

# =============================================================================
# SECTION 19: VARIABLE EXCLUSION AND WHITELIST
# =============================================================================
# Controls which variables appear in dropdown menus. EXCLUDE_VARS hides
# technical variables. _ALLOWED_VARS_RAW is a whitelist (~330 LOCALMULTIDEM
# variable names) — only these appear in the dropdown. Civic variables are
# managed separately in survey_civic.py (VAR_CONFIG dictionary).
#
# CHANGE FOR NEW DATASET — _ALLOWED_VARS_RAW must be REPLACED entirely
# with your new variable names. _EXCLUDE_VARS_RAW may also need updating.
# =============================================================================
EXCLUDE_VARS = {_norm_varname(v) for v in _EXCLUDE_VARS_RAW}
# ▶ Variables to INCLUDE in the Playground (whitelist).
#    Only variables whose normalized name is in ALLOWED_VARS will be offered
#    in the theme/subtheme/variable selectors. Everything else is hidden.
_ALLOWED_VARS_RAW = [
   "q17h16",
    "q17h10",
    "q24b03",
    "q24c03",
    "q17h14",
    "q17g16",
    "q24b04",
    "q24c04",
    "q17g10",
    "q17h13",
    "q17g05",
    "q24b12",
    "q24c12",
    "q24c13",
    "q24b13",
    "q24b11",
    "q24c11",
    "q17g14",
    "q17h17",
    "q24b05",
    "q17h09",
    "q24c05",
    "q24b01",
    "q24c01",
    "q17h02", 
    "q24c09",
    "q24b09",
    "q17g13",
    "q24b02",
    "q24c02",
    "q17g09",
    "q17g17",
    "q17h04",
    "q24c10",
    "q24b10",
    "q24b07",
    "q24c07",
    "q17h01",
    "q24b08",
    "q24c08",
    "q17g02",
    "q17g04",
    "q24b06",
    "q24c06",
    "q17g01",
    "q4",
    "q1903",
    "q54",
    "q44",
    "q46",
    "q24a09",
    "q24a01",
    "group",
    "q24a07",
    "q24a10",
    "q24a12",
    "q25",
    "q24a13",
    "q24a11",
    "q24a08",
    "q24a06",
    "q1902",
    "q24a05",
    "q24a04",
    "q24a03",
    "q24a02",
    "q1901",
    "q1",
    "qtype",
    "q17h08",
    "q17h07",
    "q17h05",
    "q17h18",
    "q17g15",
    "q17h11",
    "q17g11",
    "q17g08",
    "q17g07",
    "q17g18",
    "q17h06",
    "q17g06",
    "q56",
    "q15",
    "q58",
    "q57",
    "q6",
    "q33",
    "q55",
    "q27",
    "id",
    "q17h15",
    "q17h12",
    "q17h03",
    "q17f16",
    "q17c16",
    "q17g12",
    "q17f15",
    "q17c15",
    "q17f10",
    "q17f08",
    "q17c08",
    "q17c10",
    "q17f05",
    "q17g03",
    "q17c05",
    "q17f18",
    "q17c18",
    "q17f07",
    "q17c07",
    "q17f14",
    "q17c14",
    "q17f13",
    "q17c13",
    "q17f17",
    "q17c17",
    "q17c09",
    "q17f06",
    "q17f02",
    "q17c06",
    "q17c02",
    "q1601",
    "q17f04",
    "q17c04",
    "q1607",
    "q1602",
    "q1612",
    "q17f01",
    "q17c01",
    "q48",
    "q18b02",
    "q18b01",
    "q9",
    "q29",
    "q1308",
    "q1311",
    "q18a02",
    "q18a01",
    "q2003",
    "q47",
    "q68",
    "q45",
    "q1301",
    "i2",
    "i4",
    "i1",
    "i3",
    "i8",
    "q31",
    "q3610",
    "q3609",
    "q1306",
    "q3604",
    "q3606",
    "q3611",
    "q1302",
    "q3602",
    "q3601",
    "q2002",
    "q2001",
    "change",
    "q34",
    "q17j16",
    "q17i16",
    "q17f12",
    "q17c12",
    "q17i15",
    "q17j15",
    "q17f11",
    "q17i18",
    "q17j10",
    "q17i10",
    "q17j18",
    "q17i08",
    "q17j08",
    "q17c11",
    "q17i05",
    "q17j05",
    "q17i03",
    "q17f03",
    "q17j03",
    "q17c03",
    "q17j07",
    "q17i07",
    "q17i17",
    "q17j17",
    "q17i14",
    "q17j14",
    "q17i13",
    "q17j13",
    "q17f09",
    "q17i09",
    "q17j09",
    "q17i04",
    "q17j04",
    "q17i06",
    "q17j02",
    "q17i02",
    "q17j06",
    "q1604",
    "q1608",
    "q1603",
    "q1605",
    "q1611",
    "q1610",
    "q1609",
    "q64",
    "q63",
    "q62",
    "q17j01",
    "q17i01",
    "q18c02",
    "q18c01",
    "q38a02",
    "q38e02",
    "q38b02",
    "q38d02",
    "q38c02",
    "q18b03",
    "q38b03",
    "q38c03",
    "q38a03",
    "q38d03",
    "q38e03",
    "q53",
    "q10",
    "q18a03",
    "q61",
    "q17b11",
    "q17a11",
    "q35",
    "q2103",
    "q2203",
    "q42",
    "isco88",
    "q3706",
    "q3709",
    "q71",
    "q17b10",
    "q17b01",
    "q17b02",
    "q17b13",
    "q17b09",
    "q17b05",
    "q17b04",
    "q17b15",
    "q17b18",
    "q17b12",
    "q17b14",
    "q17b16",
    "q17b17",
    "q6a",
    "i12",
    "i5",
    "i10",
    "q39d01",
    "q39c01",
    "q17a08",
    "q17a15",
    "q17a02",
    "q17a13",
    "q17a12",
    "q17a14",
    "q17a10",
    "q17a16",
    "q17a17",
    "q17a06",
    "q17a09",
    "q17a07",
    "q17a18",
    "q17a05",
    "q17a04",
    "q17a03",
    "q17a01",
    "q67",
    "q3608",
    "q1305",
    "q3704",
    "q3703",
    "q3705",
    "q3612",
    "q3603",
    "q3702",
    "q3701",
    "q2202",
    "q2102",
    "q3901",
    "q2201",
    "q2101",
    "q17j12",
    "q17i12",
    "q17i11",
    "q17j11",
    "q1606",
    "q18c03",
    "i606",
    "i602",
    "i601",
    "i605",
    "i603",
    "i604",
    "isco88mi",
    "q14",
    "q7202",
    "q38b04",
    "q38e04",
    "q38a04",
    "q38d04",
    "q39d03",
    "q39c03",
    "opt23",
    "q70",
    "q39d02",
    "q51",
    "q39c02",
    "q17b06",
    "q17b08",
    "q17b07",
    "q69",
    "q39a01",
    "control3c",
    "q3707",
    "q3708",
    "q7201",
    "i11",
    "q1303",
    "q2304",
    "q2302",
    "q41",
    "q40",
    "q3903",
    "q3902",
    "q12",
    "q801",
    
]

# Temporarily hide all q17c.. variables from the Playground visualisations.

_Q17C_BLOCK = {
    "q17c01", "q17c02", "q17c03", "q17c04", "q17c05", "q17c06",
    "q17c07", "q17c08", "q17c09", "q17c10", "q17c10sw", "q17c11",
    "q17c11fr", "q17c12", "q17c13", "q17c14", "q17c15", "q17c16",
    "q17c17", "q17c18",
}
ALLOWED_VARS = {_norm_varname(v) for v in _ALLOWED_VARS_RAW}
ALLOWED_VARS -= {_norm_varname(v) for v in _Q17C_BLOCK}
ALLOWED_VARS.discard("q24f")  # Remove "Other ethnic organisation" - text variable
ALLOWED_VARS.discard("opt23")  # Remove "Other ethnic organisation(OPT23)" - text variable
ALLOWED_VARS.discard("qtype")  # Remove "Respondent's origin(QTYPE)" - internal variable

# =============================================================================
# SECTION 20: LABELS CSV AND SPECTRUM LABELS
# =============================================================================
# Reads the labels CSV describing what each answer code means. Also extracts
# "spectrum" endpoint labels for 0-10 scale variables (e.g., "Not close" ...
# "Very close").
#
# CHANGE FOR NEW DATASET — the labels CSV is LOCALMULTIDEM-specific. You need
# a new labels CSV in the same format. The reading code is generic.
# =============================================================================
labels_src = _norm_cols(_read_csv_salvage(LABEL_PATH)).rename(columns={
    "variable":"variable","var":"variable","name":"variable","code":"variable",
    "qid":"variable_name","question":"variable_name",
    "labels":"labels","label":"labels","label_en":"labels","labels_en":"labels",
    "codes":"codes","code_values":"codes","values":"codes",
    "type":"type","qtype":"type","vartype":"type","dtype":"type","class":"type",
})
labels_src["variable"] = labels_src["variable"].astype(str).str.strip().str.lower()
if "type" in labels_src.columns:
    
    labels_src["type"] = pd.to_numeric(labels_src["type"], errors="coerce").fillna(-1).astype(int)

# Numeric / categorical flag from labels file (column F) 
NUMERIC_VARS_FROM_LABELS: set[str] = set()
try:
    if labels_src.shape[1] >= 6:
        colF = labels_src.columns[5]
        colF_series = labels_src[colF].astype(str).str.strip().str.lower()
        numeric_markers = {"numeric", "num", "scale", "continuous", "avg"}
        mask_num = colF_series.isin(numeric_markers)
        NUMERIC_VARS_FROM_LABELS = set(
            labels_src.loc[mask_num, "variable"].astype(str).str.strip().str.lower()
        )
except Exception as e:
    _log_exc(e, where="NUMERIC_VARS_FROM_LABELS")
    NUMERIC_VARS_FROM_LABELS = set()

# ▶ Manual override:
MANUAL_NUMERIC_MEDIAN_VARS = {
    # opt13xx block (keep as numeric/median too)
    "opt1301", "opt1302", "opt1303", "opt1304", "opt1305", "opt1306",
    "opt1307", "opt1308", "opt1309", "opt1310", "opt1311", "opt1312",
    "opt1314", "opt1315", "opt1316", "opt1317", "opt1318",

    # q17f.. block – ALWAYS treat as numeric median variables
    "q17f01", "q17f02", "q17f03", "q17f04", "q17f05", "q17f06",
    "q17f07", "q17f08", "q17f09", "q17f10", "q17f11", "q17f12",
    "q17f13", "q17f14", "q17f15", "q17f16", "q17f17", "q17f18",

    # q17i.. block – ALWAYS treat as numeric median variables
    "q17i01", "q17i02", "q17i03", "q17i04", "q17i05", "q17i06",
    "q17i07", "q17i08", "q17i09", "q17i10", "q17i11", "q17i12",
    "q17i13", "q17i14", "q17i15", "q17i16", "q17i17", "q17i18",

    # q17c.. block – ALSO treat as numeric median variables
    "q17c01", "q17c02", "q17c03", "q17c04", "q17c05", "q17c06",
    "q17c07", "q17c08", "q17c09", "q17c10", "q17c10sw", "q17c11",
    "q17c11fr", "q17c12", "q17c13", "q17c14", "q17c15", "q17c16",
    "q17c17", "q17c18",

    # explicitly include q17h18 in the same median family
    "q17h18",

    # q54-related (still forced numeric/median)
    "q54nor", "q54sw", "q54bnor",

    # q67 / q68 / q69 / q71 family – FORCE to numeric/median
    "q67", "q68", "q69", "q71", "q71en", "q71fr", "q71nor",

    # additional median-coded variants used in the data
    "q17f10sw",
    "q17f11fr",
    "q17i11fr",
}


# normalize to lowercase once
MANUAL_NUMERIC_MEDIAN_VARS = {str(v).strip().lower() for v in MANUAL_NUMERIC_MEDIAN_VARS}
# Force former heatmap/stack variables to be treated as numeric/median scales
MANUAL_NUMERIC_MEDIAN_VARS |= {str(v).strip().lower() for v in BOXPLOT_NUMERIC_VARS}

def _is_numeric_scale_from_labels(var: str) -> bool:
    """Return True if this variable is flagged as numeric in column F of the labels CSV
    or is in the manual median/numeric override list."""
    v = str(var or "").strip().lower()
    return (v in NUMERIC_VARS_FROM_LABELS) or (v in MANUAL_NUMERIC_MEDIAN_VARS)

_LABELS_EXPECTED = {"variable","codes","labels","type","variable_name"}
LAST_COL = [c for c in labels_src.columns][-1] if labels_src.columns.size else None
DIAGRAM_COL = LAST_COL if (LAST_COL and LAST_COL not in _LABELS_EXPECTED) else None

def _is_diagram_var(var: str) -> bool:
    """Возвращает True, если переменная помечена как diagram в последней нестандартной колонке."""
    if DIAGRAM_COL is None: return False
    row = labels_src.loc[labels_src["variable"]==str(var).strip().lower()]
    if row.empty: return False
    val = str(row.iloc[0][DIAGRAM_COL]).strip().lower()
    return val == "diagram"

# ▶ SPECTRUM_LABELS: extract endpoint labels (0 and 10) for scale variables
# This dictionary maps variable names to a tuple (low_label, high_label) for the endpoints of the scale
SPECTRUM_LABELS: dict[str, tuple[str, str]] = {}
try:
    import ast
    for _, row in labels_src.iterrows():
        var = str(row.get("variable", "")).strip().lower()
        labels_str = str(row.get("labels", ""))
        codes_str = str(row.get("codes", ""))
        if not var or not labels_str or labels_str in ("nan", ""):
            continue
        try:
            # Parse the labels list from string representation
            labels_list = ast.literal_eval(labels_str)
            codes_list = ast.literal_eval(codes_str) if codes_str and codes_str not in ("nan", "") else []
            if not isinstance(labels_list, list) or len(labels_list) < 2:
                continue
            # Find labels for code 0 and code 10 (or the min/max of the main scale)
            code_label_map = {}
            for i, lbl in enumerate(labels_list):
                if i < len(codes_list):
                    code_label_map[codes_list[i]] = lbl
            # Extract the label text (remove the numeric prefix like "00. " or "10. ")
            def clean_label(lbl):
                lbl = str(lbl).strip()
                # Remove prefix patterns like "00. ", "0. ", "10. "
                if ". " in lbl:
                    parts = lbl.split(". ", 1)
                    if len(parts) == 2 and parts[0].replace("-", "").isdigit():
                        return parts[1].strip()
                return lbl
            # Get labels for 0 and 10 if they exist (typical 0-10 scale)
            low_label = code_label_map.get(0, "")
            high_label = code_label_map.get(10, "")
            # Only store if we have meaningful endpoint labels (not just numbers)
            low_clean = clean_label(low_label)
            high_clean = clean_label(high_label)
            if low_clean and high_clean and low_clean != "0" and high_clean != "10":
                SPECTRUM_LABELS[var] = (low_clean, high_clean)
        except Exception:
            continue
except Exception as e:
    _log_exc(e, where="SPECTRUM_LABELS parsing")

# =============================================================================
# SECTION 21: CODEBOOK LOADING
# =============================================================================
# Loads the codebook CSV that describes each variable (label, theme, subtheme).
# Both LOCALMULTIDEM and Civic codebooks are loaded here.
#
# CHANGE FOR NEW DATASET — you need new codebook files. The code handles minor
# column name differences automatically. Required columns: variable, label,
# theme, subtheme, type.
# =============================================================================
codebook_df = _norm_cols(_read_csv_salvage(CODEBOOK_PATH)).rename(columns={
    "variable":"variable","var":"variable","name":"variable","code":"variable","qid":"variable",
    "label":"label","labels":"label","label_en":"label","text":"label","question":"label",
    "title":"label","libellé":"label","libelle":"label","libellé ":"label"
})

print("[DEBUG] codebook_df columns:", list(codebook_df.columns))
print("[DEBUG] sample Categories (first non-empty):",
      codebook_df.loc[codebook_df["categories"].astype(str).str.strip().ne(""), "categories"].head(1).tolist())

# =============================================================================
# SECTION 22: MAIN DATA LOADING
# =============================================================================
# Loads the actual survey data into memory at startup.
# "raw" = LOCALMULTIDEM data (~26 MB tab-separated file).
# "raw_civic" = Civic data (~46 MB semicolon-separated CSV, Latin-1 encoding).
# Also loads the Civic codebook and creates label dictionaries.
#
# CHANGE FOR NEW DATASET — update DATA_PATH for a new main dataset.
# Update CIVIC_CSV_PATH for a new second dataset. Encoding might change.
# If adding a third survey, add another loading block.
# =============================================================================
raw = _norm_cols(_read_csv_salvage(DATA_PATH))
# Ensure a human-readable city name column exists everywhere (many plots expect it)
if "city_full" not in raw.columns:
    if "city" in raw.columns:
        raw["city_full"] = raw["city"].map(to_city_full)
    else:
        raw["city_full"] = "All cities"
# ▶ Load Civic & Political Integration survey from CSV
raw_civic = pd.DataFrame()
try:
    if CIVIC_CSV_PATH.exists():
        print(f"[INFO] Loading Civic survey from CSV: {CIVIC_CSV_PATH}")
        _civ_df = pd.read_csv(str(CIVIC_CSV_PATH), encoding='latin-1', low_memory=False)
        print(f"[INFO] CSV load SUCCESS: {len(_civ_df)} rows, {len(_civ_df.columns)} columns")
        raw_civic = _norm_cols(_civ_df)

        # Debug: check if rgroup loaded correctly
        if 'rgroup' in raw_civic.columns:
            sample_groups = raw_civic['rgroup'].value_counts().head(5).to_dict()
            print(f"[DEBUG] rgroup sample values: {sample_groups}")

        # Initialize empty label maps (CSV doesn't have value labels like DTA)
        global CIVIC_VALUE_LABELS_BY_VAR, CIVIC_VARIABLE_LABELS
        CIVIC_VALUE_LABELS_BY_VAR = {}
        CIVIC_VARIABLE_LABELS = {}

        print(f"[SUCCESS] raw_civic loaded: {len(raw_civic)} rows, {len(raw_civic.columns)} columns")
        print(f"[SUCCESS] raw_civic columns (first 10): {list(raw_civic.columns)[:10]}")
    else:
        print(f"[WARN] Civic CSV not found at: {CIVIC_CSV_PATH}")
        raw_civic = pd.DataFrame()

except Exception as e:
    print(f"[ERROR] Exception loading Civic CSV: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    raw_civic = pd.DataFrame()

print(f"[FINAL] raw_civic shape: {raw_civic.shape}")

# Ensure Civic label maps exist even if Civic .dta failed to load
try:
    CIVIC_VALUE_LABELS_BY_VAR
except NameError:
    CIVIC_VALUE_LABELS_BY_VAR = {}

try:
    CIVIC_VARIABLE_LABELS
except NameError:
    CIVIC_VARIABLE_LABELS = {}

civic_codebook_df = pd.DataFrame(columns=["variable","label","description","theme","subtheme","type","values"])
try:
    if CIVIC_CODEBOOK_PATH.exists():
        civic_codebook_df = _norm_cols(_read_csv_salvage(CIVIC_CODEBOOK_PATH))
        # Map column names to standard names
        civic_codebook_df = civic_codebook_df.rename(columns={
            "lable": "label",
            "viz_type": "type",                   # Column F: viz_type → type
            "type of visualisation": "type",
            "type_of_visualisation": "type",
            "visualisation": "type",
            "visualization": "type",
        })
        # Ensure all required columns exist
        for c in ["variable","label","description","theme","subtheme","type","values"]:
            if c not in civic_codebook_df.columns:
                civic_codebook_df[c] = ""
        civic_codebook_df["variable"] = civic_codebook_df["variable"].astype(str).str.strip().str.lower()
        civic_codebook_df["theme"] = civic_codebook_df["theme"].astype(str).str.strip()
        civic_codebook_df["subtheme"] = civic_codebook_df["subtheme"].astype(str).str.strip()
        civic_codebook_df["label"] = civic_codebook_df["label"].astype(str).str.strip()
        civic_codebook_df["description"] = civic_codebook_df["description"].astype(str).str.strip()
        civic_codebook_df["type"] = civic_codebook_df["type"].astype(str).str.strip().str.lower()
        civic_codebook_df["values"] = civic_codebook_df["values"].astype(str).str.strip()  # Keep values for routing legend
        print(f"[DEBUG] civic_codebook types: {civic_codebook_df['type'].unique().tolist()}")
except Exception as e:
    _log_exc(e, where="load_civic_codebook")
    civic_codebook_df = pd.DataFrame(columns=["variable","label","description","theme","subtheme","type","values"])

print(f"[DEBUG] raw_civic loaded: {len(raw_civic)} rows, {len(raw_civic.columns)} columns")
print(f"[DEBUG] raw_civic columns (first 20): {list(raw_civic.columns)[:20]}")

def civic_routing_summary(s: pd.Series) -> pd.DataFrame:
    try:
        ser = s.copy()
        num = pd.to_numeric(ser, errors="coerce")
        special_mask = (num < 0)
        txt = ser.astype(str).str.strip()
        for tok in ["-995", "-999", "-998", "-997", "-996"]:
            special_mask = special_mask | (txt == tok)
        sub = txt[special_mask].copy()
        if sub.empty:
            return pd.DataFrame(columns=["code", "n"])
        out = sub.value_counts(dropna=False).reset_index()
        out.columns = ["code", "n"]
        out["code"] = out["code"].astype(str)
        out["n"] = pd.to_numeric(out["n"], errors="coerce").fillna(0).astype(int)
        return out
    except Exception:
        return pd.DataFrame(columns=["code", "n"])
print(f"[DEBUG] civic_codebook_df: {len(civic_codebook_df)} rows")
print(f"[DEBUG] civic_codebook themes: {civic_codebook_df['theme'].unique().tolist()[:10]}")
print(f"[DEBUG] civic_codebook variables (first 10): {civic_codebook_df['variable'].tolist()[:10]}")

# =============================================================================
# SECTION 23: SURVEY ADAPTER REGISTRY
# =============================================================================
# The "adapter" system handles multiple surveys with a single UI. Each survey
# has an adapter that knows how to draw its charts. SURVEYS_REGISTRY holds
# all adapters. _norm_survey() normalizes names, get_adapter() returns the
# right adapter, SURVEY_OPTIONS defines the dropdown choices.
#
# CHANGE IF ADDING A NEW SURVEY — add entry to SURVEY_OPTIONS and register
# a new adapter in init_adapters(). The adapter system itself is generic.
# =============================================================================
def _norm_survey(s: str | None) -> str:
    ss = str(s or "localmulti").strip().lower()
    if ss in {"localmultidem", "localmulti", "lmd"}:
        return "localmulti"
    if ss in {"civic", "civicpol", "civic_political", "civic&political", "civic and political"}:
        return "civicpol"
    return ss

SURVEYS_REGISTRY = {}

def get_adapter(survey: str | None):
    # Initialize adapters once, lazily
    if not SURVEYS_REGISTRY:
        init_adapters()

    key = _norm_survey(survey)
    ad = SURVEYS_REGISTRY.get(key)
    if ad is None:
        ad = SURVEYS_REGISTRY.get("localmulti")
    return ad

def _meta_for_survey(survey: str|None):
    key = _norm_survey(survey)
    if key == 'civicpol':
        ad = SURVEYS_REGISTRY.get('civicpol')
        if ad is not None:
            return ad.codebook
        return pd.DataFrame()
    return var_meta

def _labels_for_survey(survey: str|None):
    key = _norm_survey(survey)
    if key == 'civicpol':
        ad = SURVEYS_REGISTRY.get('civicpol')
        if ad is not None:
            return ad.dict_labels
        return {}
    return dict_labels



SURVEY_OPTIONS = [
    {"label": "LOCALMULTIDEM", "value": "localmulti"},
    {"label": "Civic & Political Integration", "value": "civicpol"},
]
DEFAULT_SURVEY = "localmulti"
    
# =============================================================================
# SECTION 24: VARIABLE FILTERING BY CITY COUNT
# =============================================================================
# Hides variables that only have data in too few cities. A variable must have
# valid data in at least MIN_CITIES_FOR_VAR cities to appear in the dropdown.
#
# SAME FOR ANY DATASET — generic quality filtering. Adjust the threshold if
# needed.
# =============================================================================
MIN_CITIES_FOR_VAR = 7
_VAR_CITYCOUNT_CACHE: dict[str, int] = {}

_ROUTING_CODES_TXT = {"", "nan", "none"}

def _city_count_for_var_default(v: str) -> int:
    """Number of distinct cities with at least one valid response for v (default universe)."""
    vv = _norm_varname(v)
    if vv in _VAR_CITYCOUNT_CACHE:
        return _VAR_CITYCOUNT_CACHE[vv]

    if vv not in raw.columns or "city" not in raw.columns:
        _VAR_CITYCOUNT_CACHE[vv] = 0
        return 0

    s_txt = raw[vv].astype(str).str.strip().str.lower()

    # drop routing/refusal/missing tokens
    mask = ~s_txt.isin(_ROUTING_CODES_TXT)

    # drop negative routing codes like -1, -9
    s_num = pd.to_numeric(s_txt, errors="coerce")
    mask &= ~(s_num < 0)

    if not mask.any():
        _VAR_CITYCOUNT_CACHE[vv] = 0
        return 0

    cities = raw.loc[mask, "city"].map(to_city_full)
    n_cities = int(pd.Series(cities).dropna().astype(str).nunique())

    _VAR_CITYCOUNT_CACHE[vv] = n_cities
    return n_cities

def _var_has_min_cities(v: str, min_cities: int = MIN_CITIES_FOR_VAR) -> bool:
    return _city_count_for_var_default(v) >= int(min_cities)
missing = REQUIRED_RAW - set(raw.columns)
if missing:
    raise SystemExit(f"[ERROR] RAW missing base columns: {sorted(missing)}")
# =============================================================================
# SECTION 25: POST-HARMONIZATION DATA
# =============================================================================
# Loads additional country-specific variables from a Stata .dta file and
# merges them into the main LOCALMULTIDEM data. Variables ending in "_post"
# override their original counterparts.
#
# CHANGE FOR NEW DATASET — specific to LOCALMULTIDEM post-harmonization.
# If your new data has no post-harmonized variables, remove or skip this.
# =============================================================================
_post_df = None
if str(os.environ.get("DP_DISABLE_POST_DTA", "0")).strip() not in {"1", "true", "yes", "on"}:
    if POST_DTA_PATH.exists():
        try:
            try:
                _icloud_touch(POST_DTA_PATH, min_bytes=1024)
            except Exception:
                pass

            if pyreadstat is None:
                raise ModuleNotFoundError("pyreadstat")

            _post_df, _meta = pyreadstat.read_dta(
                str(POST_DTA_PATH),
                apply_value_formats=False, 
                formats_as_category=False,
            )
            _post_df = _norm_cols(_post_df)
        except (OSError, ReadstatError, ModuleNotFoundError) as e:
            try:
                logging.warning("load_post_dta: disabled (%s)", str(e))
            except Exception:
                pass
            _post_df = None
        except Exception as e:
            _log_exc(e, where="load_post_dta")
            _post_df = None

if _post_df is not None and not _post_df.empty:
    n_post, n_raw = len(_post_df), len(raw)
    if n_post != n_raw:
        msg = (
            f"[WARN] post .dta has {n_post} rows, but RAW has {n_raw} rows; "
            "post-overrides are DISABLED (row counts must match)."
        )
        warnings.warn(msg)
        try:
            logging.error(msg)
        except Exception:
            pass
    else:
        
        for col in _post_df.columns:
            name_lower = str(col).strip().lower()
            if not name_lower.endswith("_post"):
                continue
            base = name_lower[:-5] 
            raw[name_lower] = _post_df[col].values
            if base in raw.columns:
                if base.startswith(("q17c", "q17f", "q17i")):
            
                    continue
                raw[base] = _post_df[col].values
# =============================================================================
# SECTION 26: LABELS, ROUTING, AND COUNTRY METADATA
# =============================================================================
# Creates dict_labels (variable -> human-readable label), identifies routing
# columns, and loads country metadata (respondent counts per country).
#
# CHANGE FOR NEW DATASET — manual label overrides are LOCALMULTIDEM-specific.
# The routing detection logic is generic.
# =============================================================================
dict_labels = dict(zip(codebook_df["variable"].astype(str).str.strip().str.lower(),
                       codebook_df.get("label", pd.Series(dtype=str)).fillna("").astype(str)))
MANUAL_LABEL_OVERRIDES: dict[str, str] = {
    "q45": "How often attend religious services (apart from special occasions)",
    "q54": "Highest level of education",
    "q57": "Employment relation",
    "q55": "Main activity in the last 7 days",
    "q42": "How often visit homeland country",
    "q53": "How well speak host-country language",
    "q14": "Self-identification",
    # NEW LABELS ADDED:
    "q15": "Discrimination last 12 months",
    "q71": "Household's total net monthly income (euro)",
    "q34": "Most people can be trusted or you can't be too careful",
    "q35": "Most people can be trusted or you can't be too careful [ethnic group]",
    "q29": "Voted last homeland country election",
    "q27": "Voted last local election",
    "q40": "Help to borrow money",
}
dict_labels.update(MANUAL_LABEL_OVERRIDES)

_ROUTING_COL_CANDIDATES = {
    "routing",
    "routing_notes",
    "routing_universe",
    "universe",
    "universe_notes",
    "filter",
    "filtering",
    "universe_filter",
}
ROUTING_COL = None
for c in codebook_df.columns:
    cname = str(c).strip().lower()
    if cname in _ROUTING_COL_CANDIDATES:
        ROUTING_COL = c
        break

if ROUTING_COL is not None:
    dict_routing = dict(
        zip(
            codebook_df["variable"].astype(str).str.strip().str.lower(),
            codebook_df[ROUTING_COL].fillna("").astype(str),
        )
    )
else:
    dict_routing = {}
country_meta = None
if COUNTRY_META_PATH.exists():
    try:
        _tmp = _norm_cols(_read_csv_salvage(COUNTRY_META_PATH))
        for c in ["variable","country","code","title"]:
            if c not in _tmp.columns:
                _tmp[c] = None
        _tmp["variable"] = _tmp["variable"].astype(str).str.strip().str.lower()
        country_meta = _tmp[["variable","country","code","title"]]
    except Exception:
        country_meta = None

def country_line_for_var(var: str) -> str:
    if country_meta is None: return ""
    row = country_meta[country_meta["variable"]==str(var).strip().lower()]
    if row.empty: return ""
    r = row.iloc[0]
    parts = []
    if pd.notna(r.get("title")) and str(r.get("title")).strip():
        parts.append(str(r.get("title")).strip())
    else:
        parts.append(str(dict_labels.get(var, var.upper())))
    if pd.notna(r.get("country")) and str(r.get("country")).strip():
        parts.append(f"({str(r.get('country')).strip().upper()})")
    if pd.notna(r.get("code")) and str(r.get("code")).strip():
        parts.append(str(r.get("code")).strip().upper())
    return " ".join(parts)

# =============================================================================
# SECTION 27: MEDIANS CSV LOADING
# =============================================================================
# Loads pre-calculated median values from a CSV. These medians were calculated
# externally and provide fast median charts without recalculating from raw data.
#
# CHANGE FOR NEW DATASET — the medians CSV is LOCALMULTIDEM-specific. If your
# new data needs median charts, pre-calculate a new medians CSV. If not,
# this section can be skipped.
# =============================================================================
def _load_medians_csv(path: Path) -> pd.DataFrame | None:
    try:
        df = _norm_cols(_read_csv_salvage(path))
    except Exception as e:
        warnings.warn(f"[WARN] Could not load medians CSV: {path} → {e}")
        return None
    if df is None or df.empty:
        warnings.warn(f"[WARN] Medians CSV is empty: {path}")
        return None

    cols = set(df.columns)
    rename_map = {}

    # variable
    for c in ("variable","var","code","qid","name"):
        if c in cols:
            rename_map[c] = "variable"
            break
    # city
    for c in ("city_full","city","cityname","city_name"):
        if c in cols:
            rename_map[c] = "city"
            break
    # group-ish
    group_col = None
    for c in ("group_disp","group_name","group_label","group"):
        if c in cols:
            group_col = c
            break
    # gender
    for c in ("gender","sex"):
        if c in cols:
            rename_map[c] = "gender"
            break
    # values
    for c in ("median","med","value","val"):
        if c in cols:
            rename_map[c] = "median"
            break
    for c in ("n","count","size","num","samples"):
        if c in cols:
            rename_map[c] = "n"
            break

    df = df.rename(columns=rename_map)

    
    if "variable" in df.columns:
        df["variable"] = df["variable"].astype(str).str.strip().str.lower()
    if "city" in df.columns:
        df["city"] = df["city"].map(to_city_full)
    if group_col is None:
        df["group_disp"] = "All groups"
    else:
        def _to_group_disp(x):
            try:
                xi = int(float(str(x)))
                return GROUP_NAMES.get(xi, f"Group {xi}")
            except Exception:
                s = str(x).strip()
                return s if s else "All groups"

        df["group_disp"] = df[group_col].map(_to_group_disp)

        # Drop synthetic/invalid group -9 when group column is numeric-like
        try:
            mask_bad = pd.to_numeric(df[group_col], errors="coerce") == -9
            df = df[~mask_bad].copy()
        except Exception:
            pass

    
    if "city" in df.columns and "group_disp" in df.columns:
        df["group_disp"] = [
            "Autochthonous" if _is_native_pair(cf, gd) else gd
            for cf, gd in zip(df["city"], df["group_disp"])
        ]

    # gender → Male/Female/ALL
    if "gender" not in df.columns:
        df["gender"] = "ALL"
    else:
        df["gender"] = (
            df["gender"].astype(str).str.strip().replace(
                {"1":"Male","2":"Female","M":"Male","F":"Female","male":"Male","female":"Female"}
            )
        )
        df.loc[~df["gender"].isin(["Male","Female"]), "gender"] = "ALL"

    if "median" in df.columns:
        df["median"] = pd.to_numeric(df["median"], errors="coerce")
    else:
        warnings.warn("[WARN] Medians CSV has no 'median' column after normalization.")
    if "n" in df.columns:
        df["n"] = pd.to_numeric(df["n"], errors="coerce")
    else:
        df["n"] = np.nan

    df["group_disp"] = df["group_disp"].replace({"autochthonous": "Autochthonous"})

    need = {"variable","city","group_disp","median"}
    missing = [c for c in need if c not in df.columns]
    if missing:
        warnings.warn(f"[WARN] Medians CSV lacks required columns: {missing}")
    df = df.dropna(subset=[c for c in need if c in df.columns]).copy()

    return df

MEDIANS_DF = None

# =============================================================================
# SECTION 28: MEDIAN CHART BUILDING
# =============================================================================
# build_median_from_csv() creates horizontal bar charts from pre-calculated
# medians. Adds alternating background bands and separators between groups.
#
# SAME FOR ANY DATASET — generic chart logic. Works with any medians CSV.
# =============================================================================
def build_median_from_csv(
    med_df: pd.DataFrame,
    var: str,
    cities=None,
    groups=None,
    genders=None,
    include_autochthonous: bool=True,
    orient: str="h",
    primary: str="city",
    secondary: str="group_disp",
    sep: bool=True,
    sort_asc: bool=False,
):
    
    if med_df is None or med_df.empty:
        return px.bar(title="No median values are available for this indicator.")

    v = str(var or "").strip().lower()
    sub = med_df[med_df.get("variable", "").astype(str).str.lower() == v].copy()
    if sub.empty:
      return px.bar(title=f"No median values could be found for variable {var.upper()}.")
    if cities:
        sub = sub[sub["city"].isin(cities)]
    want_auto = False
    want_groups = None
    if groups:
        gset = set(groups)
        want_auto = (AUTOCH_KEY in gset)
        want_groups = []
        for g in gset:
            if g == AUTOCH_KEY:
                continue
            try:
                want_groups.append(GROUP_NAMES.get(int(g), f"Group {int(g)}"))
            except Exception:
                pass
        if want_groups:
            sub = sub[sub["group_disp"].isin(want_groups)]
    if not include_autochthonous:
        sub = sub[sub["group_disp"] != "Autochthonous"]
    else:
        if groups and not want_auto:
            sub = sub[sub["group_disp"] != "Autochthonous"]
    if "gender" in sub.columns:
        if (sub["gender"] == "ALL").any():
            sub = sub[sub["gender"] == "ALL"].copy()
        elif genders:
            sub = sub[sub["gender"].isin(genders)].copy()

    if sub.empty:
       return px.bar(title="No median values remain after applying the current filters.")
    primary = primary or "city"
    secondary = secondary or "group_disp"
    if primary == "city_full" and "city" in sub.columns:
        primary = "city"
    if secondary == "city_full" and "city" in sub.columns:
        secondary = "city"
    missing_axes = [ax for ax in (primary, secondary) if ax not in sub.columns]
    if missing_axes:
        _log_exc(KeyError(", ".join(missing_axes)), where="build_median_from_csv:axes")
        if "city" in sub.columns:
            primary = "city"
        else:
            primary = sub.columns[0]
        if "group_disp" in sub.columns:
            secondary = "group_disp"
        elif "group" in sub.columns:
            secondary = "group"
        else:
            secondary = sub.columns[min(1, len(sub.columns) - 1)]

    primaries = sorted(sub[primary].dropna().unique().tolist(), key=lambda x: str(x))
    secs = sorted(sub[secondary].dropna().unique().tolist(), key=lambda x: str(x))
    order_rows = []
    cursor = 0
    band_ranges = []
    for p in primaries:
        part = sub[sub[primary] == p][[secondary, "median"]].groupby(secondary, dropna=False)["median"].mean().reset_index()
        part = part.sort_values("median", ascending=sort_asc, kind="mergesort")
        start = cursor + 1
        for s in part[secondary].tolist():
            cursor += 1
            order_rows.append((p, s, cursor))
        band_ranges.append((start, cursor, p))
    seq = pd.DataFrame(order_rows, columns=[primary, secondary, "xc"])
    seq["xlabel"] = seq[primary].astype(str) + " ▸ " + seq[secondary].astype(str)

    tbl = pd.merge(sub, seq, on=[primary, secondary], how="left").sort_values(["xc"]).copy()

    pal = palette(secondary)
    color_map = pal if isinstance(pal, dict) else None

    fig = px.bar(
        tbl,
        x="xc" if orient == "v" else "median",
        y="median" if orient == "v" else "xc",
        color=secondary,
        orientation="h" if orient == "h" else "v",
        barmode="group",
        **({"color_discrete_map": color_map} if color_map else {"color_discrete_sequence": pal}),
        hover_data={col: False for col in tbl.columns}
    )
    fig.update_traces(
        width=BAR_TRACE_WIDTH,
        marker_line_width=0.8,
        marker_line_color="rgba(0,0,0,.55)",
        cliponaxis=False,
        hovertemplate=(
            "Primary: %{customdata[0]}<br>Secondary: %{customdata[1]}"
            "<br>Median: %{customdata[2]:.2f}<br>n: %{customdata[3]:,.0f}<extra></extra>"
        ),
        customdata=np.stack([
            tbl[primary].astype(str).to_numpy(),
            tbl[secondary].astype(str).to_numpy(),
            tbl["median"].to_numpy(),
            tbl.get("n", pd.Series(index=tbl.index, dtype=float)).to_numpy(),
        ], axis=1),
    )
    fig.update_layout(
        bargap=BAR_GAP,
        bargroupgap=BAR_GROUP_GAP,
        uniformtext_minsize=9,
        uniformtext_mode="hide",
        transition={"duration": 0},
    )
    # axis floor = 0
    max_med = float(tbl["median"].max())
    if orient == "v":
        fig.update_yaxes(range=[0, max_med * 1.1])
    else:
        fig.update_xaxes(range=[0, max_med * 1.1])

    ticks = seq[["xc","xlabel"]]
    if orient == "v":
        fig.update_xaxes(tickmode="array", tickvals=ticks["xc"], ticktext=ticks["xlabel"], tickangle=30)
        fig.update_yaxes(title_text="Median")
    else:
        fig.update_yaxes(tickmode="array", tickvals=ticks["xc"], ticktext=ticks["xlabel"])
        fig.update_xaxes(title_text="Median")

    if sep and len(band_ranges):
        for i, (start, _, _) in enumerate(band_ranges):
            if i > 0:
                (fig.add_vline if orient == "v" else fig.add_hline)(
                    **({"x": start - 0.5} if orient == "v" else {"y": start - 0.5}),
                    line_color="rgba(0,0,0,.32)", line_width=1
                )
        for i, (start, end, _) in enumerate(band_ranges):
            if start > end: continue
            if orient == "v":
                fig.add_vrect(x0=start-0.5, x1=end+0.5,
                              fillcolor="rgba(0,0,0,0.035)" if i%2==0 else "rgba(0,0,0,0.06)",
                              line_width=0, layer="below")
            else:
                fig.add_hrect(y0=start-0.5, y1=end+0.5,
                              fillcolor="rgba(0,0,0,0.035)" if i%2==0 else "rgba(0,0,0,0.06)",
                              line_width=0, layer="below")
    return fig

def _median_with_ci(x: pd.Series, conf: float = 0.95) -> pd.Series:
    
    x = pd.Series(x).dropna()
    n = int(len(x))
    if n == 0:
        return pd.Series(
            {"median": np.nan, "n": 0, "ci_low": np.nan, "ci_high": np.nan}
        )
    vals = np.sort(x.astype(float).to_numpy())
    med = float(np.median(vals))
    if n < 3:
        return pd.Series(
            {"median": med, "n": n, "ci_low": med, "ci_high": med}
        )

    alpha = 1.0 - conf
    z = 1.959963984540054  # ~97.5% quantile for normal
    lower_rank = int(np.floor(0.5 * n - 0.5 * z * np.sqrt(n)))
    upper_rank = int(np.ceil(0.5 * n + 0.5 * z * np.sqrt(n)))
    lower_rank = max(1, min(lower_rank, n))
    upper_rank = max(1, min(upper_rank, n))

    ci_low = float(vals[lower_rank - 1])
    ci_high = float(vals[upper_rank - 1])

    return pd.Series(
        {"median": med, "n": n, "ci_low": ci_low, "ci_high": ci_high}
    )


# =============================================================================
# SECTION 29: BOX PLOT / MEAN CHART
# =============================================================================
# build_mean_chart() creates box plots showing distribution of numeric
# responses. Groups by primary x secondary keys (e.g., city x group).
#
# SAME FOR ANY DATASET — completely generic box plot logic.
# =============================================================================
def build_mean_chart(
    df: pd.DataFrame,
    var: str,
    primary_key: str,
    secondary_key: str,
    orient: str = "h",
    sep: bool = True,
    sort_asc: bool = False,
):
    v_norm = str(var or "").strip().lower()
    # Box plots default to horizontal
    orient = "h" if orient not in {"v", "h"} else orient
    if v_norm not in df.columns:
        return px.box(title=f"No data column found for {var}."), pd.DataFrame()

    work = df.copy()

    # Ensure city_full exists if requested
    if primary_key == "city_full" and "city_full" not in work.columns:
        if "city" in work.columns:
            work["city_full"] = work["city"].map(to_city_full)
        else:
            work["city_full"] = "All cities"

    # Ensure group_disp exists if requested
    if secondary_key == "group_disp" and "group_disp" not in work.columns:
        try:
            work["group_disp"] = _group_disp_series(work)
        except Exception:
            if "group" in work.columns:
                work["group_disp"] = work["group"].astype(str)
            else:
                work["group_disp"] = "All groups"

    raw_s = work[v_norm]
    s_txt = raw_s.astype(str).str.strip()

    # Only treat negative sentinel codes as routing (positive codes like 88, 99 are valid for many variables)
    # Negative codes are handled below via num.mask(num < 0)

    num = pd.to_numeric(s_txt, errors="coerce")
    num = num.mask(num < 0)
    if v_norm in BOXPLOT_NUMERIC_VARS or v_norm.startswith(("q17c", "q17f", "q17i")):
        num = num.where((num >= 1) & (num <= 10))

    keep_cols = [c for c in [primary_key, secondary_key] if c in work.columns]
    sub = work.loc[num.notna(), keep_cols].copy()
    sub["_val"] = num[num.notna()].astype(float).values

    for c in keep_cols:
        sub = sub[sub[c].notna()]

    if sub.empty:
        return px.box(title=f"No valid numeric responses remain for {v_norm.upper()}."), pd.DataFrame()
    primaries = sorted(sub[primary_key].astype(str).unique().tolist(), key=lambda s: s)

    seq_rows = []
    band_ranges = []
    cursor = 0

    for p in primaries:
        part = sub[sub[primary_key].astype(str) == str(p)].copy()
        med_part = (
            part.groupby(secondary_key, dropna=False)["_val"]
            .agg(_med="median", _n="size")
            .reset_index()
        )
        med_part = med_part[med_part["_n"].fillna(0).astype(int) > 0].copy()
        med_part = med_part.sort_values("_med", ascending=sort_asc, kind="mergesort")

        start = cursor + 1
        for s in med_part[secondary_key].astype(str).tolist():
            cursor += 1
            seq_rows.append((str(p), str(s), cursor))
        band_ranges.append((start, cursor, str(p)))

    seq = pd.DataFrame(seq_rows, columns=[primary_key, secondary_key, "xc"])
    if seq.empty:
        return px.box(title="No data are available for the current combination of filters."), pd.DataFrame()

    seq["xlabel"] = seq[primary_key].astype(str) + "<br>" + seq[secondary_key].astype(str)

    tbl = sub.merge(seq[[primary_key, secondary_key, "xc", "xlabel"]], on=[primary_key, secondary_key], how="left")
    tbl = tbl.dropna(subset=["xc"]).copy()
    tbl["xc"] = tbl["xc"].astype(int)
    if tbl.empty:
        return px.box(title="No data are available for the current combination of filters."), pd.DataFrame()
    order = seq[["xc", "xlabel"]].sort_values("xc")["xlabel"].astype(str).tolist()
    # Get unique secondary values (groups or cities) and assign unique colors
    unique_secondary = sorted(tbl[secondary_key].dropna().astype(str).unique().tolist())
    n_colors = len(unique_secondary)

    # Maximally distinct colors - hand-picked for maximum perceptual difference
    # Based on Kelly's colors of maximum contrast + additional distinct colors
    DISTINCT_COLORS = [
        "#e6194B",  # red
        "#3cb44b",  # green
        "#4363d8",  # blue
        "#f58231",  # orange
        "#911eb4",  # purple
        "#42d4f4",  # cyan
        "#f032e6",  # magenta
        "#88aa00",  # lime-green (visible)
        "#e91e63",  # strong pink
        "#469990",  # teal
        "#7b1fa2",  # deep purple
        "#9A6324",  # brown
        "#ffcc00",  # golden yellow (visible)
        "#800000",  # maroon
        "#00897b",  # dark mint
        "#808000",  # olive
        "#ff5722",  # deep orange
        "#000075",  # navy
        "#607d8b",  # blue grey
        "#212121",  # dark grey
        "#8e24aa",  # vivid purple
        "#aa6e28",  # chocolate
        "#ffe119",  # yellow
        "#00c853",  # strong green
        "#2962ff",  # strong blue
        "#d500f9",  # vivid magenta
        "#00bcd4",  # strong cyan
        "#ff1744",  # strong red
        "#008080",  # dark teal
        "#ff6600",  # dark orange
        "#6600ff",  # violet
        "#cc9900",  # gold
        "#009999",  # dark cyan
        "#990099",  # dark magenta
        "#669900",  # yellow-green
        "#ff3399",  # hot pink
        "#0066cc",  # steel blue
        "#795548",  # medium brown
        "#339966",  # sea green
        "#cc3366",  # raspberry
    ]

    # Use pre-defined distinct colors, generate more if needed
    if n_colors <= len(DISTINCT_COLORS):
        box_colors = DISTINCT_COLORS[:n_colors]
    else:
        # If we need more colors, extend with generated ones
        box_colors = list(DISTINCT_COLORS)
        golden_ratio = 0.618033988749895
        hue = 0.33  # Start at different point
        for i in range(n_colors - len(DISTINCT_COLORS)):
            hue = (hue + golden_ratio) % 1.0
            sat = 0.9
            light = 0.35 + (i % 4) * 0.15
            r, g, b = colorsys.hls_to_rgb(hue, light, sat)
            box_colors.append("#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255)))

    box_color_map = {val: box_colors[i] for i, val in enumerate(unique_secondary)}
    color_kwargs = {"color_discrete_map": box_color_map}

    nice_label = dict_labels.get(v_norm, var.upper())

    if orient == "v":
        fig = px.box(
            tbl,
            x="xlabel",
            y="_val",
            color=secondary_key,
            points="outliers",
            category_orders={"xlabel": order},
            **color_kwargs,
        )
        fig.update_yaxes(title_text="Value", rangemode="tozero", automargin=True)
        fig.update_xaxes(
            title_text=None,
            tickangle=0,
            automargin=True,
            tickfont=dict(size=8),
            ticklabeloverflow="hide past domain",
        )
    else:
        fig = px.box(
            tbl,
            x="_val",
            y="xlabel",
            color=secondary_key,
            points="outliers",
            orientation="h",
            category_orders={"xlabel": order},
            **color_kwargs,
        )
        fig.update_xaxes(title_text="Value", rangemode="tozero", automargin=True)
        fig.update_yaxes(title_text=None, automargin=True, tickfont=dict(size=9), ticklabeloverflow="hide past domain")

    fig.update_traces(
    notched=False,
    jitter=0,
    marker={"size": 3},
    line={"width": 1},
    width=0.35, 
)
    n_cols = int(seq["xc"].max()) if not seq.empty else int(tbl["xc"].nunique())
    fig_width = None if orient == "h" else max(1200, min(9000, 100 * max(1, n_cols)))   
    if orient == "h":
        fig_height = max(1200, min(12000, 60 * max(1, n_cols) + 420))
    else:
        fig_height = 740

    # Determine legend title based on secondary_key
    legend_title = "City" if secondary_key in ("city_full", "city_disp") else "Group"

    fig.update_layout(
        boxgap=0.35,
        boxgroupgap=0.10,
        title={"text": nice_label, "x": 0.5, "xanchor": "center"},
        title_font_size=TITLE_FONT_SIZE,
        margin=dict(l=70, r=40, t=120, b=260),
        transition={"duration": 0},
        showlegend=True,
        legend_title_text=legend_title,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.18,
            xanchor="left",
            x=0,
            bgcolor="rgba(255,255,255,0.9)",
            font=dict(size=10),
        ),
        height=fig_height,
        autosize=True,
        **({} if fig_width is None else {"width": fig_width}),
    )
    

    # Separators + subtle alternating bands per primary (like stacked bars)
    def _whiskers(vals: np.ndarray):
        q1 = np.quantile(vals, 0.25)
        q3 = np.quantile(vals, 0.75)
        iqr = q3 - q1
        lo = q1 - 1.5 * iqr
        hi = q3 + 1.5 * iqr
        lo = np.min(vals[vals >= lo]) if np.any(vals >= lo) else float(np.min(vals))
        hi = np.max(vals[vals <= hi]) if np.any(vals <= hi) else float(np.max(vals))
        return float(lo), float(hi)

    rows = []
    for (pk, sk), part in tbl.groupby([primary_key, secondary_key], dropna=False):
        vals = part["_val"].dropna().astype(float).to_numpy()
        if vals.size == 0:
            continue
        q1 = float(np.quantile(vals, 0.25))
        q3 = float(np.quantile(vals, 0.75))
        med = float(np.median(vals))
        iqr = float(q3 - q1)
        wlo, whi = _whiskers(vals)
        rows.append(
            {
                "primary": pk,
                "secondary": sk,
                "n": int(vals.size),
                "median": med,
                "q1": q1,
                "q3": q3,
                "iqr": iqr,
                "whisker_low": wlo,
                "whisker_high": whi,
            }
        )

    table_df = pd.DataFrame(rows)
    if not table_df.empty:
        table_df["primary"] = table_df["primary"].astype(str)
        table_df["secondary"] = table_df["secondary"].astype(str)
        # order rows to match xc order
        order_map = {(p, s): int(xc) for p, s, xc in seq[[primary_key, secondary_key, "xc"]].itertuples(index=False, name=None)}
        table_df["_ord"] = [order_map.get((str(p), str(s)), 10**9) for p, s in zip(table_df["primary"], table_df["secondary"])]
        table_df = table_df.sort_values(["_ord"]).drop(columns=["_ord"]).reset_index(drop=True)

    # Add thermometer scale labels if applicable
    fig = _add_thermometer_axis_labels(fig, var)
    
    return fig, table_df
# =============================================================================
# SECTION 30: SCALE DENSITY CHART
# =============================================================================
# build_scale_density() creates smooth line charts showing distribution
# across a 0-10 scale. Adds spectrum endpoint labels.
#
# SAME FOR ANY DATASET — generic visualization for numeric scale data.
# =============================================================================
def build_scale_density(
    df: pd.DataFrame,
    var: str,
    city_codes=None,
    groups=None,
    genders=("Male", "Female", "Other"),
    smooth: bool = True,
):

    v = str(var or "").strip().lower()
    if v not in df.columns:
        fig = px.line(title=f"No data column found for {var}.")
        return fig, pd.DataFrame(columns=["value", "n", "pct"])
    sub = df[
        (df.city.isin(ALL_CITIES if not city_codes else city_codes))
        & (df.group.isin(ALL_GROUP_IDS if not groups else groups))
        & (df.gender.isin(genders))
    ].copy()

    if sub.empty:
        fig = px.line(title="No data are available for this indicator.")
        return fig, pd.DataFrame(columns=["value", "n", "pct"])
    s = sub[v].map(_canon_code)
    is_special = s.map(_is_negative_code)
    vals = pd.to_numeric(s, errors="coerce")
    vals = vals[~is_special & vals.notna()]

    if vals.empty:
        fig = px.line(title=f"No valid numeric responses remain for {var.upper()}.")
        return fig, pd.DataFrame(columns=["value", "n", "pct"])
    v_min = int(np.floor(vals.min()))
    v_max = int(np.ceil(vals.max()))
    if v_min == v_max:
        v_min = v_min - 1
        v_max = v_max + 1

    grid = np.arange(v_min, v_max + 1, 1, dtype=int)
    counts = vals.value_counts().sort_index()
    total = float(counts.sum())
    pct = (counts / total * 100.0).reindex(grid, fill_value=0.0)

    tbl = pd.DataFrame({
        "value": grid,
        "n": pct.index.map(lambda x: int(counts.get(x, 0))),
        "pct": pct.values,
    })
    label_key = v.strip().lower()
    nice_label = dict_labels.get(label_key, var.upper())

    fig = px.line(
        tbl,
        x="value",
        y="pct",
    )

    mode = "lines+markers"
    line_shape = "spline" if smooth else "linear"
    fig.update_traces(
        mode=mode,
        line={"shape": line_shape, "width": 3},
        marker={"size": 8},
        fill="tozeroy",
        hovertemplate=(
            "Scale point: %{x}<br>"
            "Share of respondents: %{y:.1f}%<br>"
            "n at this point: %{customdata[0]:,}<extra></extra>"
        ),
        customdata=np.stack([
            tbl["n"].to_numpy(),
        ], axis=1),
        showlegend=False,
    )
    # Axes and layout - check for spectrum labels
    bottom_margin = 80
    if v in SPECTRUM_LABELS and 0 in grid and 10 in grid:
        low_label, high_label = SPECTRUM_LABELS[v]
        # Create tick text with endpoint labels
        tick_texts = []
        for x in grid:
            if x == 0:
                tick_texts.append(f"0\n{low_label}")
            elif x == 10:
                tick_texts.append(f"10\n{high_label}")
            else:
                tick_texts.append(str(x))
        fig.update_xaxes(
            title_text=None,
            tickmode="array",
            tickvals=grid,
            ticktext=tick_texts,
            dtick=1,
        )
        bottom_margin = 120
    else:
        fig.update_xaxes(
            title_text="Response category",
            tickmode="array",
            tickvals=grid,
            ticktext=[str(x) for x in grid],
            dtick=1,
        )

    vmax = float(tbl["pct"].max()) if not tbl.empty else 0.0
    pad = 0.1 * vmax if vmax > 0 else 5.0
    fig.update_yaxes(
        title_text="Share of respondents (%)",
        range=[0, vmax + pad],
        rangemode="tozero",
    )

    fig.update_layout(
        title={"text": nice_label, "x": 0.5, "xanchor": "center"},
        transition={"duration": 0},
        title_font_size=TITLE_FONT_SIZE,
        margin=dict(l=60, r=30, t=110, b=bottom_margin),
    )
    out_tbl = tbl[["value", "n", "pct"]].copy().reset_index(drop=True)
    return fig, out_tbl

# =============================================================================
# SECTION 31: YES/NO BAR CHARTS
# =============================================================================
# build_yes() creates bar charts showing "Yes" share for binary variables.
# Auto-detects yes/no codes using YES_ALIASES and NO_ALIASES.
#
# SAME FOR ANY DATASET — generic yes/no detection and chart building.
# =============================================================================
def build_yes(df, var, colour_key, x_key, orient, city_codes, groups, genders, asc, show_auto, sep, color_map_override=None):
    orient = "h" if orient not in {"v", "h"} else orient
    sub = df[
        (df.city.isin(ALL_CITIES if not city_codes else city_codes))
        & (df.group.isin(ALL_GROUP_IDS if not groups else groups))
        & (df.gender.isin(genders))
    ]
    if "group_disp" not in sub.columns:
        sub = sub.copy()
        sub["group_disp"] = _group_disp_series(sub)
    if not show_auto:
        sub = sub[sub["group_disp"] != "Autochthonous"]
    if sub.empty or var not in sub.columns:
        return px.bar(title="No data are available for this indicator.")

    by = [x_key, colour_key] if x_key != colour_key else [x_key]
    tbl = yes_share_for_var(sub, var, by).sort_values("value", ascending=asc)
    if "n" in tbl.columns:
        tbl = tbl[tbl["n"] > 0].copy()
    if tbl.empty:
        return px.bar(title="No data are available for the current combination of filters.")

    cmap = _code_label_map_strict(var)
    lab_yes = cmap.get("1", "Yes")

    custom = np.stack([
        tbl["yes"].to_numpy(),
        tbl["no"].to_numpy(),
        tbl["n"].to_numpy(),
        tbl["value"].to_numpy(),
    ], axis=1)

    if isinstance(color_map_override, dict) and color_map_override:
        color_kwargs = {"color_discrete_map": color_map_override}
    elif str(colour_key) in ("group_disp", "group_name"):
     
        color_kwargs = {"color_discrete_map": _group_color_map_for(tbl[colour_key])}
    else:
        pal = palette(colour_key)
        color_kwargs = {"color_discrete_map": pal} if isinstance(pal, dict) else {"color_discrete_sequence": pal}

    primary = x_key
    secondary = colour_key

    seq_rows = []
    bands = []
    cursor = 0

    primaries = tbl[primary].astype(str).dropna().unique().tolist()
    for p in primaries:
        part = tbl[tbl[primary].astype(str) == str(p)].copy()
        part = part.sort_values("value", ascending=asc, kind="mergesort")

        start = cursor + 1
        for s in part[secondary].astype(str).dropna().unique().tolist():
            cursor += 1
            seq_rows.append((str(p), str(s), cursor))
        bands.append((start, cursor, str(p)))

    if not seq_rows:
        return px.bar(title="No data are available for the current combination of filters.")

    seq = pd.DataFrame(seq_rows, columns=[primary, secondary, "xc"])
    seq["xlabel"] = seq[primary].astype(str)

    tbl2 = tbl.merge(seq[[primary, secondary, "xc", "xlabel"]], on=[primary, secondary], how="left")
    tbl2 = tbl2.dropna(subset=["xc"]).copy()
    tbl2["xc"] = tbl2["xc"].astype(int)
    tbl2 = tbl2.sort_values(["xc"]).copy()

    fig = px.bar(
        tbl2,
        x="xc" if orient == "v" else "value",
        y="value" if orient == "v" else "xc",
        color=secondary,
        orientation="h" if orient == "h" else "v",
        barmode="relative",
        category_orders={
            "xc": tbl2["xc"].tolist(),
            secondary: sorted(tbl2[secondary].dropna().astype(str).unique().tolist()),
        },
        **color_kwargs,
    )

    # Tick labels show ONLY city (not group), and only for first bar of each city band
    ticks = seq[["xc", "xlabel"]].sort_values("xc")
    # Build tick text that shows the city only on the first (xc) of each city band.
    try:
        band_starts = {int(start) for (start, _end, _p) in bands}
    except Exception:
        band_starts = set()

    tick_vals = ticks["xc"].astype(int).tolist()
    tick_text = [
        (str(ticks.loc[ticks["xc"].astype(int) == v, "xlabel"].iloc[0]) if v in band_starts else "")
        for v in tick_vals
    ]
    if orient == "v":
        fig.update_xaxes(
            tickmode="array",
            tickvals=tick_vals,
            ticktext=tick_text,
            tickangle=0,
            ticks="",
        )
        # Prevent tick-label overlap (stacked-bars style)
        fig.update_xaxes(
            tickfont=dict(size=7),
            automargin=True,
            ticklabeloverflow="hide past domain",
        )
        # Ensure enough bottom margin for 1-line labels
        try:
            m = dict(fig.layout.margin) if fig.layout.margin else {}
            m["b"] = max(int(m.get("b", 0) or 0), 140)
            fig.update_layout(margin=m)
        except Exception:
            pass
    else:
        fig.update_yaxes(
            tickmode="array",
            tickvals=tick_vals,
            ticktext=tick_text,
            ticks="",
        )
        # Prevent tick-label overlap for horizontal YES charts
        fig.update_yaxes(
            tickfont=dict(size=7),
            automargin=True,
            ticklabeloverflow="hide past domain",
        )
        try:
            m = dict(fig.layout.margin) if fig.layout.margin else {}
            m["l"] = max(int(m.get("l", 0) or 0), 110)
            fig.update_layout(margin=m)
        except Exception:
            pass
        try:
            n_cat = int(len(ticks))
        except Exception:
            n_cat = 0

        try:
            base_h = int(DEFAULT_BAR_LAYOUT.get("height", 600))
        except Exception:
            base_h = 600

        # Two-line labels need more per-row space; keep it generous but bounded.
        per_row = 26
        min_h = 380
        dyn_h = max(min_h, (per_row * max(1, n_cat)) + 260)

        # Respect any global horizontal scaling you already use, but never go below dyn_h.
        try:
            scaled_h = int(round(base_h * float(globals().get("HORIZONTAL_HEIGHT_SCALE", 1.0))))
        except Exception:
            scaled_h = base_h

        fig.update_layout(height=max(dyn_h, scaled_h))

        # Slightly larger tick font now that we have vertical room
        try:
            fig.update_yaxes(tickfont=dict(size=8))
        except Exception:
            pass

    try:
        if sep and bands:
            # thin separator line between city bands
            for i, (start, _end, _p) in enumerate(bands):
                if i == 0:
                    continue
                (fig.add_vline if orient == "v" else fig.add_hline)(
                    **({"x": start - 0.5} if orient == "v" else {"y": start - 0.5}),
                    line_color="rgba(0,0,0,.25)",
                    line_width=1,
                )
            # alternating band shading per city
            for i, (start, end, _p) in enumerate(bands):
                if start > end:
                    continue
                fill = "rgba(0,0,0,0.035)" if i % 2 == 0 else "rgba(0,0,0,0.06)"
                if orient == "v":
                    fig.add_vrect(
                        x0=start - 0.5,
                        x1=end + 0.5,
                        fillcolor=fill,
                        line_width=0,
                        layer="below",
                    )
                else:
                    fig.add_hrect(
                        y0=start - 0.5,
                        y1=end + 0.5,
                        fillcolor=fill,
                        line_width=0,
                        layer="below",
                    )
    except Exception:
        pass
    try:
        fig.update_traces(width=BAR_TRACE_WIDTH)
    except Exception:
        pass
    try:
        vmax = float(tbl2["value"].max()) if not tbl2.empty else 0.0
    except Exception:
        vmax = 0.0
    pad = 0.05 * vmax if vmax > 0 else 5.0
    if orient == "v":
        fig.update_yaxes(range=[0, vmax + pad])
    else:
        fig.update_xaxes(range=[0, vmax + pad])
    plot_tbl = tbl2
    for tr in fig.data:
        tr_name = getattr(tr, 'name', None)
        if tr_name is None:
            continue
        cats = getattr(tr, 'x', None) if orient == 'v' else getattr(tr, 'y', None)
        if cats is None:
            continue
        rows = []
        for cat in cats:
            m = (plot_tbl["xc"].astype(str) == str(cat)) & (plot_tbl[colour_key].astype(str) == str(tr_name))
            if not m.any():
                rows.append([0, 0, 0, 0.0])
            else:
                r = plot_tbl.loc[m].iloc[0]
                rows.append([int(r['yes']), int(r['no']), int(r['n']), float(r['value'])])
        tr.customdata = np.asarray(rows, dtype=object)

    fig.update_traces(
        marker_line_width=0.7,
        width=BAR_TRACE_WIDTH,
        marker_line_color="rgba(0,0,0,.55)",
        hovertemplate=(
            ("%{x}" if orient == "v" else "%{y}")
            + "<br>Group: %{fullData.name}<br>"
            + "Number of \"Yes\" responses: %{customdata[0]}<br>"
            + "Number of \"No\" responses: %{customdata[1]}<br>"
            + "Valid responses (coded 0/1): %{customdata[2]}<br>"
            + "Share of \"Yes\": %{customdata[3]:.1f}%<extra></extra>"
        ),
    )

    fig.update_layout(
        **DEFAULT_BAR_LAYOUT,
        legend_title_text=colour_key.replace("_", " ").capitalize(),
        yaxis_title=f"{lab_yes} (%)" if orient == "v" else None,
        xaxis_title=None if orient == "v" else f"{lab_yes} (%)",
        title_font_size=TITLE_FONT_SIZE,
    )
    try:
        fig.update_layout(**DEFAULT_BAR_LAYOUT)
    except Exception:
        pass

    
    _apply_stack_accessibility(fig)

    # Add a bit more spacing between categories so bars never collide
    try:
        fig.update_layout(
            bargap=max(BAR_GAP, 0.06),
            bargroupgap=BAR_GROUP_GAP,
        )
    except Exception:
        pass

    return fig

# =============================================================================
# SECTION 32: STACKED BAR CHARTS
# =============================================================================
# build_stack() is the MAIN chart builder — stacked bars showing response
# distribution (totaling 100%). Handles city x group cross-tabulation,
# separators, MIN_NONROUTING_N threshold, and autochthonous inclusion.
# If variable is numeric, redirects to build_mean_chart().
#
# SAME FOR ANY DATASET — generic stacking logic. Auto-reads response
# categories from the data.
# =============================================================================
def build_stack(
    df: pd.DataFrame,
    var: str,
    x_key: str,
    orient: str = "h",
    city_codes=None,
    groups=None,
    genders=("Male", "Female", "Other"),
    include_autochthonous: bool = True,
    sep: bool = True,
    show_auto: bool = True,
    sort_asc: bool = False,
    asc: bool = False,
    **_ignored,
):

    # ------------------------------------------------------------------
    # IMPORTANT: Apply ALL UI filters once, and reuse the same subset for
    # BOTH categorical bars and numeric (box/mean) charts.
    # ------------------------------------------------------------------

    v_norm = str(var or "").strip().lower()
    orient = "h" if orient not in {"v", "h"} else orient

    # Build ONE filtered working subset (same filters for bar + box)
    sub = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    # Ensure city_full exists
    if not sub.empty and "city_full" not in sub.columns:
        if "city" in sub.columns:
            sub["city_full"] = sub["city"].map(to_city_full)
        else:
            sub["city_full"] = "All cities"

    # Apply selectors safely (only if columns exist)
    if not sub.empty and "city" in sub.columns:
        sub = sub[sub["city"].isin(ALL_CITIES if not city_codes else city_codes)].copy()
    if not sub.empty and "group" in sub.columns:
        sub = sub[sub["group"].isin(ALL_GROUP_IDS if not groups else groups)].copy()
    if not sub.empty and "gender" in sub.columns:
        sub = sub[sub["gender"].isin(genders)].copy()

    # Ensure group_disp exists
    if not sub.empty and "group_disp" not in sub.columns:
        try:
            sub["group_disp"] = _group_disp_series(sub, include_autoch=bool(include_autochthonous))
        except Exception:
            if "group" in sub.columns:
                sub["group_disp"] = sub["group"].astype(str)
            else:
                sub["group_disp"] = "All groups"

   # Respect include_autochthonous
    if not sub.empty and (not include_autochthonous) and ("group_disp" in sub.columns):
        sub = sub[sub["group_disp"] != "Autochthonous"].copy()

    if sub is None or sub.empty:
        return px.bar(title="No data are available for this filter combination.")
    
    # Smart category sorting (numeric if possible, fixed order for special variables)
    resp_order = _smart_sort_categories(sub[var].dropna().unique(), var=var)
    
    # ------------------------------------------------------------------
    # Numeric (box/mean) path
    # IMPORTANT: do NOT reference external callback-state variables
    # like `born_here_sel` / `show_autoch` here.
    # All required filter state MUST be passed into build_stack via args.
    # ------------------------------------------------------------------
    if v_norm in BOXPLOT_NUMERIC_VARS:
        fig, _table_df = build_mean_chart(
            sub,
            v_norm,
            primary_key="city_full",
            secondary_key="group_disp",
            orient="h",
            sep=bool(sep),
            sort_asc=bool(sort_asc or asc),
        )
        return fig

    # ------------------------------------------------------------------
    # Non-box paths continue below (categorical stacks / special charts)
    # ------------------------------------------------------------------




    # ------------------------------------------------------------------
    # Non-box paths continue below (categorical stacks / special charts)
    # ------------------------------------------------------------------

    scale_vars = {}
    v_norm = str(var or "").strip().lower()
    if v_norm in scale_vars:
        fig, _tbl = build_scale_density(
            df=df,
            var=v_norm,
            city_codes=city_codes,
            groups=groups,
            genders=genders,
            smooth=True,
        )
        return fig

    primary = "group_disp" if str(x_key).strip().lower() in ("group","group_disp") else "city_full"
    secondary = "city_full" if primary == "group_disp" else "group_disp"
    # Reuse the already-filtered subset built above
    # (so filters apply identically to bar + box charts)
    # sub is already filtered
    if sub.empty or v_norm not in sub.columns:
        return px.bar(title="No data are available for this indicator.")
    g, resp_order = multi_share_generic(sub, var, by=[primary, secondary])
    # multi_share_generic returns columns:
    #   [primary, secondary, 'resp', 'n', 'total', 'pct']
    # but the rest of build_stack expects:
    #   [primary, secondary, 'resp', 'cnt', '_n', 'value']
    # Normalize once here so downstream code never KeyErrors on 'cnt'.

    if g is None:
        g = pd.DataFrame(columns=[primary, secondary, "resp", "cnt", "_n", "value"])

    # Ensure DataFrame
    if isinstance(g, pd.Series):
        g = g.reset_index(name="n")

    # Map possible column names to the expected schema
    cols_lower = {str(c).strip().lower(): c for c in getattr(g, "columns", [])}

    # Count column: prefer 'cnt', else 'n'
    if "cnt" in cols_lower:
        g = g.rename(columns={cols_lower["cnt"]: "cnt"})
    elif "n" in cols_lower:
        g = g.rename(columns={cols_lower["n"]: "cnt"})

    # Total column: prefer '_n', else 'total'
    if "_n" in cols_lower:
        g = g.rename(columns={cols_lower["_n"]: "_n"})
    elif "total" in cols_lower:
        g = g.rename(columns={cols_lower["total"]: "_n"})

    # Share column: prefer 'value', else 'pct'
    if "value" in cols_lower:
        g = g.rename(columns={cols_lower["value"]: "value"})
    elif "pct" in cols_lower:
        g = g.rename(columns={cols_lower["pct"]: "value"})

    # Ensure required columns exist (never crash here)
    for c in [primary, secondary, "resp", "cnt", "_n", "value"]:
        if c not in g.columns:
            g[c] = np.nan

    # --- robust count column (prevents KeyError: 'cnt') ---
    # Normalize whatever count column pandas produced into a guaranteed `cnt`.
    if g is None:
        g = pd.DataFrame()

    # If g is a Series (e.g., from .size()), convert to DataFrame with cnt
    if isinstance(g, pd.Series):
        g = g.reset_index(name="cnt")
    else:
        # Map lowercased names -> original names
        cols_lower = {str(c).strip().lower(): c for c in list(getattr(g, "columns", []))}

        # Common count column names depending on how g was created
        if "cnt" in cols_lower:
            cnt_col = cols_lower["cnt"]
        elif "n" in cols_lower:
            cnt_col = cols_lower["n"]
        elif "count" in cols_lower:
            cnt_col = cols_lower["count"]
        elif "size" in cols_lower:
            cnt_col = cols_lower["size"]
        elif "0" in cols_lower:
            # Sometimes reset_index gives column name 0
            cnt_col = cols_lower["0"]
        else:
            # Last resort: if there is exactly one numeric column, treat it as counts
            numeric_cols = [c for c in g.columns if pd.api.types.is_numeric_dtype(g[c])]
            if len(numeric_cols) == 1:
                cnt_col = numeric_cols[0]
            else:
                # Edge case: no count column found; keep app alive
                g = g.copy()
                g["cnt"] = 0
                cnt_col = "cnt"

        if cnt_col != "cnt":
            g = g.rename(columns={cnt_col: "cnt"})

    # Ensure integer counts
    g["cnt"] = pd.to_numeric(g["cnt"], errors="coerce").fillna(0).astype(int)
    # --- end robust count column ---
    g["_n"] = pd.to_numeric(g["_n"], errors="coerce").fillna(0).astype(int)
    g["value"] = pd.to_numeric(g["value"], errors="coerce").fillna(0.0).astype(float)

    # Drop empty groups (prevents divisions/hover weirdness)
    g = g[g["_n"] > 0].copy()
    r0 = resp_order[0] if resp_order else None
    if r0 is not None:
        base = g[g["resp"] == r0][[primary, secondary, "value"]].rename(columns={"value": "_key"})
    else:
        base = totals.rename(columns={"_n": "_key"})
        base["_key"] = base["_key"].astype(float)
    seq_rows, bands = [], []
    cursor = 0
    for prim in sorted(g[primary].dropna().astype(str).unique().tolist(), key=lambda s: s):
        part = base[base[primary].astype(str) == prim].copy()
        sec_vals = g[g[primary].astype(str) == prim][secondary].dropna().astype(str).unique().tolist()
        part = part[part[secondary].astype(str).isin(sec_vals)]
        part = part.sort_values("_key", ascending=bool(sort_asc), kind="mergesort")

        start = cursor + 1
        for sec in part[secondary].astype(str).tolist():
            cursor += 1
            seq_rows.append((prim, sec, cursor))
        bands.append((start, cursor, prim))

    if not seq_rows:
       return px.bar(title="No data are available for the current combination of filters.")

    seq = pd.DataFrame(seq_rows, columns=[primary, secondary, "xc"])
    seq["xlabel"] = np.where(
        primary == "city_full",
        seq["city_full"].astype(str) + " ▸ " + seq["group_disp"].astype(str),
        seq["group_disp"].astype(str) + " ▸ " + seq["city_full"].astype(str)
    )
    gg = g.merge(seq, on=[primary, secondary], how="left").sort_values(["xc"])
    gg["value"] = gg["value"].astype(float)
    category_orders = {
        "xc": gg["xc"].tolist(),
        "resp": resp_order if resp_order else sorted(gg["resp"].astype(str).unique().tolist())
    }

    fig = px.bar(
        gg,
        x="xc" if orient == "v" else "value",
        y="value" if orient == "v" else "xc",
        color="resp",
        orientation="h" if orient == "h" else "v",
        barmode="relative",
        category_orders=category_orders,
        labels={"resp": "Response", "value": "Share (%)"},
        custom_data=[
            primary,                
            secondary,              
            "cnt",                 
            "_n",                   
            "value",                
        ],
    )
    ticks = seq[["xc", "xlabel"]]
    if orient == "v":
        fig.update_xaxes(
            tickmode="array", tickvals=ticks["xc"], ticktext=ticks["xlabel"], tickangle=-25, ticks=""
        )
        fig.update_yaxes(range=[0, 100], title_text="Share (%)")
    else:
        fig.update_yaxes(tickmode="array", tickvals=ticks["xc"], ticktext=ticks["xlabel"], ticks="")
        fig.update_xaxes(range=[0, 100], title_text="Share (%)")

    try:
        fig.update_xaxes(tickfont=dict(size=7))
        fig.update_yaxes(tickfont=dict(size=7))
    except Exception:
        pass

    if sep and len(bands):
        for i, (start, _, _) in enumerate(bands):
            if i > 0:
                (fig.add_vline if orient == "v" else fig.add_hline)(
                    **({"x": start - 0.5} if orient == "v" else {"y": start - 0.5}),
                    line_color=SEP_LINE_COLOR, line_width=SEP_LINE_WIDTH
                )
        for i, (start, end, _) in enumerate(bands):
            if start > end: 
                continue
            if orient == "v":
                fig.add_vrect(
                    x0=start - 0.5, x1=end + 0.5,
                    fillcolor="rgba(0,0,0,0.035)" if i % 2 == 0 else "rgba(0,0,0,0.06)",
                    line_width=0, layer="below"
                )
            else:
                fig.add_hrect(
                    y0=start - 0.5, y1=end + 0.5,
                    fillcolor="rgba(0,0,0,0.035)" if i % 2 == 0 else "rgba(0,0,0,0.06)",
                    line_width=0, layer="below"
                )

    fig.update_traces(
        hovertemplate=(
            "<b>%{customdata[0]}</b> ▸ <b>%{customdata[1]}</b><br>"
            "Response category: %{fullData.name}<br>"
            "Number of respondents in this segment: %{customdata[2]:,}<br>"
            "Total number of respondents in this column: %{customdata[3]:,}<br>"
            "Percentage within this column: %{customdata[4]:.1f}%<extra></extra>"
        ),
        marker_line_width=0.7,
        marker_line_color="rgba(0,0,0,.55)",
    )

    try:
        fig.update_traces(width=BAR_TRACE_WIDTH)
    except Exception:
        pass

    fig.update_layout(
        **DEFAULT_BAR_LAYOUT,
        legend_title_text="Response",
        yaxis_title="Share (%)" if orient == "v" else None,
        xaxis_title=None if orient == "v" else "Share (%)",
        title_font_size=TITLE_FONT_SIZE,
    )

    try:
        fig.update_layout(**DEFAULT_BAR_LAYOUT)
    except Exception:
        pass
    try:
        if v_norm in HEATMAP_STACK_VARS and len(fig.data):
            if resp_order:
                available = gg["resp"].astype(str).unique().tolist()
                levels = [str(r) for r in resp_order if str(r) in available]
            else:
                levels = gg["resp"].astype(str).dropna().unique().tolist()

            color_map = _build_scale_heatmap_colors(levels)
            if color_map:
                for tr in fig.data:
                    name = getattr(tr, "name", None)
                    if name is None:
                        continue
                    key = str(name)
                    if key in color_map:
                        tr.marker.color = color_map[key]
    except Exception as e:
        _log_exc(e, where="build_stack:heatmap_colours")

    _apply_stack_accessibility(fig)

    return fig

# =============================================================================
# SECTION 33: THEME LOADING AND VARIABLE METADATA
# =============================================================================
# Loads the theme hierarchy (Theme -> Subtheme -> Variable) from
# localmultidem_themes.csv for populating the cascading dropdown menus.
# var_meta is the final metadata used by dropdown callbacks.
# Also includes _is_numeric_var() for detecting numeric/scale variables.
#
# CHANGE FOR NEW DATASET — you need a new localmultidem_themes.csv. The reading
# logic is generic but the content is dataset-specific.
# =============================================================================
var_type_map = dict(zip(labels_src["variable"], labels_src.get("type", pd.Series(dtype=int))))
# DISABLED: eager adapter instantiation (var_meta not available yet)
# LOCALMULTI_ADAPTER = LocalMultiAdapter(
#     raw=raw,
#     var_meta=var_meta,
#     ...
# )

#
# --------------------------
# Survey adapters (initialized after var_meta is created)
# --------------------------
SURVEYS_REGISTRY = {}


def get_adapter(survey: str | None):
    """Return adapter for selected survey; falls back to localmulti."""
    key = _norm_survey(survey)
    ad = SURVEYS_REGISTRY.get(key)
    if ad is None:
        ad = SURVEYS_REGISTRY.get("localmulti")
    return ad

def _load_theme_df() -> pd.DataFrame:
 
    import unicodedata as u
    last_err = None
    for p in THEME_CANDIDATES:
        try:
            if not p.exists():
                continue
            try:
                df = pd.read_csv(p, sep=";", engine="python", dtype=str)
            except Exception:
                df = pd.read_csv(p, engine="python", dtype=str)

            def norm(s):
                s = u.normalize("NFKC", str(s))
                return (s.replace("\ufeff","").replace("\u200b","").replace("\xa0"," ").strip().lower())

            df.columns = [norm(c) for c in df.columns]
            df = df.rename(columns={
                "var":"variable","variables":"variable","var_name":"variable",
                "name":"variable","code":"variable","qid":"variable",
                "theme_name":"theme","topic":"theme","thematic":"theme","dimension":"theme",
                "sub_theme":"subtheme","sub-topic":"subtheme","sub topic":"subtheme",
                "subcategory":"subtheme","sous-theme":"subtheme","sous_thème":"subtheme",
                "labels":"label","label_en":"label","text":"label","question":"label",
                "title":"label","inclusion":"inclusion"
            })

            need = {"theme","variable"}
            if not need.issubset(df.columns):
                raise ValueError(f"Theme CSV missing {sorted(need - set(df.columns))}; got {sorted(df.columns)}")

            if "subtheme" not in df.columns: df["subtheme"] = ""
            if "inclusion" not in df.columns: df["inclusion"] = "yes"

            df["inclusion"] = df["inclusion"].astype(str).str.strip().str.lower()
            df = df[df["inclusion"] != "no"]

            cols = [c for c in ["theme","subtheme","variable","label","inclusion"] if c in df.columns]
            df = df[cols].drop_duplicates()

            for c in ["theme","subtheme","variable","label"]:
                if c in df.columns:
                    df[c] = df[c].astype(str).str.strip()
            df["variable"] = df["variable"].str.lower()
            df["subtheme"] = df["subtheme"].replace({"": None})
            return df
        except Exception as e:
            last_err = e
            continue
    raise SystemExit(f"[ERROR] Could not load themes CSV (localmultidem_themes.csv). Last error: {last_err}")

theme_df_raw = _load_theme_df()

if "variable" in theme_df_raw.columns:
    theme_df_raw = theme_df_raw.copy()
    theme_df_raw["variable"] = theme_df_raw["variable"].astype(str)
    theme_df_raw = theme_df_raw[
        ~theme_df_raw["variable"].map(_norm_varname).isin(EXCLUDE_VARS)
    ]
if "variable" in theme_df_raw.columns:
    theme_df_raw = theme_df_raw.copy()
    theme_df_raw["variable"] = theme_df_raw["variable"].astype(str)
    theme_df_raw = theme_df_raw[
        ~theme_df_raw["variable"].map(_norm_varname).isin(EXCLUDE_VARS)
    ]

visible_vars = [
    v
    for v in theme_df_raw["variable"].unique().tolist()
    if v in raw.columns
    and _norm_varname(v) in ALLOWED_VARS
    and _norm_varname(v) not in EXCLUDE_VARS
]

theme_df = theme_df_raw[theme_df_raw["variable"].isin(visible_vars)].copy()

theme_df = theme_df[~theme_df["variable"].map(_norm_varname).isin(EXCLUDE_VARS)].copy()

theme_df["type"] = theme_df["variable"].map(var_type_map).fillna(-1).astype(int)

theme_df = theme_df[theme_df["type"].isin([1, 2, 3, 4])].copy()
if theme_df.empty:
    warnings.warn("[WARN] No variables after theme/type/visibility gating; using raw-visible fallback.")
    theme_df = theme_df_raw[theme_df_raw["variable"].isin(visible_vars)].copy()
    theme_df["type"] = theme_df["variable"].map(var_type_map).fillna(-1).astype(int)


var_meta = theme_df[["theme", "subtheme", "variable", "type"]].drop_duplicates()

def _is_numeric_var(var: str) -> bool:
    """Флаг «числовая/медианная переменная»."""
    v = str(var or "").strip().lower()
    
    # Force specific variables to be numeric (box plots)
    if v in FORCE_BOX_PLOT_VARS:
        return True
    
    # Force specific variables to NOT be numeric (categorical bars)
    if v in FORCE_CATEGORICAL_BARS:
        return False

    try:
        if _is_numeric_scale_from_labels(v):
            return True
    except Exception:
        pass
    
    t = int(var_type_map.get(v, -1)) if v in var_type_map else -1
    if t == 4:
        return True

    try:
        return (MEDIANS_DF is not None) and (not MEDIANS_DF[MEDIANS_DF.get("variable", "") == v].empty)
    except Exception:
        return False
    

def _load_theme_df() -> pd.DataFrame:
    """
    Загружает один из файлов localmultidem_themes.csv / variables_by_theme_clean.csv.
    Нормализует имена колонок, отбрасывает inclusion == 'no', держит столбцы:
      theme, subtheme, variable, label, inclusion
    Гарантирует lower-case у variable, и None для пустых subtheme.
    """
    import unicodedata as u
    last_err = None
    for p in THEME_CANDIDATES:
        try:
            if not p.exists():
                continue
            try:
                df = pd.read_csv(p, sep=";", engine="python", dtype=str)
            except Exception:
                df = pd.read_csv(p, engine="python", dtype=str)

            def norm(s):
                s = u.normalize("NFKC", str(s))
                return (s.replace("\ufeff","").replace("\u200b","").replace("\xa0"," ").strip().lower())

            df.columns = [norm(c) for c in df.columns]
            df = df.rename(columns={
                "var":"variable","variables":"variable","var_name":"variable",
                "name":"variable","code":"variable","qid":"variable",
                "theme_name":"theme","topic":"theme","thematic":"theme","dimension":"theme",
                "sub_theme":"subtheme","sub-topic":"subtheme","sub topic":"subtheme",
                "subcategory":"subtheme","sous-theme":"subtheme","sous_thème":"subtheme",
                "labels":"label","label_en":"label","text":"label","question":"label",
                "title":"label","inclusion":"inclusion"
            })

            need = {"theme","variable"}
            if not need.issubset(df.columns):
                raise ValueError(f"Theme CSV missing {sorted(need - set(df.columns))}; got {sorted(df.columns)}")

            if "subtheme" not in df.columns: df["subtheme"] = ""
            if "inclusion" not in df.columns: df["inclusion"] = "yes"

            df["inclusion"] = df["inclusion"].astype(str).str.strip().str.lower()
            df = df[df["inclusion"] != "no"]

            cols = [c for c in ["theme","subtheme","variable","label","inclusion"] if c in df.columns]
            df = df[cols].drop_duplicates()

            for c in ["theme","subtheme","variable","label"]:
                if c in df.columns:
                    df[c] = df[c].astype(str).str.strip()
            df["variable"] = df["variable"].str.lower()
            df["subtheme"] = df["subtheme"].replace({"": None})
            return df
        except Exception as e:
            last_err = e
            continue
    raise SystemExit(f"[ERROR] Could not load themes CSV (localmultidem_themes.csv). Last error: {last_err}")

theme_df_raw = _load_theme_df()

# =============================================================================
# SECTION 34: GROUP DISPLAY SERIES
# =============================================================================
# _group_disp_series() creates human-readable group names for charts, with
# autochthonous collapsing. Checks qtype==2 and native city-group pairs to
# replace native group names with "Autochthonous".
#
# CHANGE FOR NEW DATASET — depends on GROUP_NAMES and NATIVE_BY_CITY (both
# LOCALMULTIDEM-specific). The logic is reusable if you define equivalent
# mappings.
# =============================================================================
def _group_disp_series(df: pd.DataFrame, include_autoch: bool = True) -> pd.Series:
    """Return a display-friendly group label.

    If include_autoch is True, optionally collapse native pairs into
    the synthetic group label 'Autochthonous'. When filtering by nativity
    (Born in interview country / Not born), we set include_autoch=False.
    """
    out = df.get("group", pd.Series(index=df.index, dtype=object)).astype(str)

    def _to_name(x):
        try:
            xi = int(float(str(x)))
            return GROUP_NAMES.get(xi, f"Group {xi}")
        except Exception:
            s = str(x).strip()
            return s if s else "All groups"

    disp = out.map(_to_name)

    if include_autoch:
        try:
            if "qtype" in df.columns:
                is_auto = pd.to_numeric(df["qtype"], errors="coerce").eq(2)
            else:
                is_auto = pd.Series(False, index=df.index)

            if "city_full" in df.columns and "group" in df.columns:
                native = [
                    _is_native_pair(cf, _to_name(g))
                    for cf, g in zip(df["city_full"], df["group"])
                ]
                is_auto = is_auto | pd.Series(native, index=df.index)

            disp = disp.mask(is_auto, "Autochthonous")
        except Exception:
            pass

    return disp

    base = df["group"].map(lambda g: GROUP_NAMES.get(int(g) if pd.notna(g) else g, f"Group {g}"))
    
    city_full = df.get("city_full")
    if city_full is None:
        city_full = df["city"].map(to_city_full)

    nat_auto = np.array([
        _is_native_pair(cf, gn) if (cf is not None and gn is not None) else False
        for cf, gn in zip(city_full, base)
    ])
    is_auto_qtype = pd.to_numeric(df["qtype"], errors="coerce").eq(2).to_numpy()
    return np.where(is_auto_qtype | nat_auto, "Autochthonous", base)

# =============================================================================
# SECTION 35: RESPONSE PARSING UTILITIES
# =============================================================================
# Small functions for parsing and classifying survey responses:
# _canon_code() standardizes codes, _is_negative_code() checks routing codes,
# _parse_categories_string() parses pipe-separated labels,
# _code_label_map_strict() maps code->label, _is_binary_var() detects yes/no,
# _infer_yes_no_codes() auto-detects which code is yes/no,
# yes_share_for_var() calculates yes/no percentages.
#
# SAME FOR ANY DATASET — all generic parsers.
# =============================================================================
def _split_list_preserve(s: str) -> list[str]:

    import ast
    if pd.isna(s): return []
    s = str(s).strip()
    if s.startswith("[") and s.endswith("]"):
        try:
            L = ast.literal_eval(s)
            if isinstance(L, (list, tuple)):
                return [str(x).strip() for x in L]
        except Exception:
            pass
    for sep in ["|",";","/","\t",","]:
        if sep in s: return [p.strip() for p in s.split(sep)]
    return [s] if s!="" else []

def _canon_code(x) -> str:

    if pd.isna(x): return ""
    s = str(x).strip()
    m = re.fullmatch(r"\s*([-+]?\d+)(?:\.0+)?\s*", s)
    if m: return m.group(1)
    return s

def _parse_int(s: str):
    try: return int(str(s).strip())
    except Exception: return None

def _is_negative_numeric_code(s: str) -> bool:
    if s is None:
        return False
    c = _canon_code(s)
    i = _parse_int(c)
    return i is not None and i < 0

def _is_negative_code(s: str) -> bool:
    """Only negative numeric codes (< 0) are universally routing codes."""
    return _is_negative_numeric_code(s)

def _parse_categories_string(cat: str) -> tuple[list[str], list[str]]:
    """
    Parse codebook 'categories' strings like:
      '1. Yes | 2. No | -8. Not applicable (item not asked)'
    into (codes, labels).
    """
    if cat is None:
        return [], []
    s = str(cat).strip()
    if not s or s.lower() in {"nan", "none"}:
        return [], []

    # Split on pipes (the codebook uses " | ")
    parts = [p.strip() for p in s.split("|") if str(p).strip()]
    codes, labs = [], []
    for p in parts:
        # Match: CODE + '.' + LABEL
        # examples: '01. French', '-8. Not applicable ...', '0. No'
        m = re.match(r"^\s*([+-]?\d+)\s*\.\s*(.+?)\s*$", p)
        if m:
            code = m.group(1).strip()
            lab = m.group(2).strip()
            if code and lab:
                codes.append(_canon_code(code))
                labs.append(lab)
            continue

        # If it doesn't match 'x. label', keep as label-only
        # (rare, but better than dropping)
        labs.append(p)
        codes.append(_canon_code(p))

    return codes, labs


def _codes_labels_for_strict(var: str) -> tuple[list[str], list[str]]:
    v = str(var).strip().lower()

    # 1) PRIMARY: localmultidem_codebook.csv Categories column (ALWAYS prefer this)
    try:
        if "codebook_df" in globals() and codebook_df is not None and not codebook_df.empty:
            cb = codebook_df
            if "variable" in cb.columns:
                hit = cb[cb["variable"].astype(str).str.strip().str.lower() == v]
                if not hit.empty and "categories" in hit.columns:
                    cat = hit.iloc[0].get("categories", "")
                    cds2, labs2 = _parse_categories_string(cat)
                    if cds2 and labs2 and len(cds2) == len(labs2):
                        return cds2, labs2
    except Exception:
        pass

    # 2) SECONDARY: labels file (localmultidem_category_labels.csv)
    try:
        row = labels_src[labels_src["variable"] == v]
        if not row.empty:
            labs = _split_list_preserve(row.iloc[0].get("labels", ""))
            cds  = _split_list_preserve(row.iloc[0].get("codes",  "")) if "codes" in labels_src.columns else []
            cds  = [_canon_code(c) for c in cds]

            if cds and len(cds) == len(labs):
                return cds, labs
            if labs:
                return [str(i) for i in range(len(labs))], labs
    except Exception:
        pass

    return [], []

def _code_label_map_strict(var: str) -> dict[str,str]:
 
    cds, labs = _codes_labels_for_strict(var)
    return dict(zip(cds, labs))

def _positive_codes_and_labels(var: str) -> tuple[list[str], list[str]]:
 
    codes, labs = _codes_labels_for_strict(var)
    pos_codes, pos_labs = [], []
    for c, l in zip(codes, labs):
        if not _is_negative_code(c):
            pos_codes.append(c); pos_labs.append(l)
    return pos_codes, pos_labs
def _resp_sentence_case(x) -> str:
    """Sentence-case for response labels: capitalize first character only.

    Avoid .title() because it mangles contractions (e.g., Don't -> Don'T).
    """
    if x is None:
        return ""
    s = str(x).strip()
    if not s or s.lower() in {"nan", "none"}:
        return ""
    return s[:1].upper() + s[1:]

def _norm_token(s: str) -> str:
    import unicodedata as u
    s = str(s or "").strip().lower()
    s = u.normalize("NFKD", s)
    s = "".join(ch for ch in s if not u.combining(ch))
    s = re.sub(r"\s+", " ", s)
    return s

def _is_binary_var(var: str) -> bool:

    try:
        yes_code, no_code, _, _ = _infer_yes_no_codes(var)
        return yes_code is not None and no_code is not None and yes_code != no_code
    except Exception:
        pass
    # Fallback: look at response labels we consider "positive domain"
    try:
        pos_codes, pos_labels = _positive_codes_and_labels(var)
        return len(set(pos_labels)) == 2
    except Exception:
        return False

def _infer_yes_no_codes(var: str) -> tuple[str,str,str,str]:
  
    pos_codes, pos_labs = _positive_codes_and_labels(var)
    if len(pos_codes) != 2:
       
        return "1", [c for c in pos_codes if c != "1"][0] if pos_codes else "0", "Yes", "No"
    c1, c2 = pos_codes
    lmap = _code_label_map_strict(var)
    l1, l2 = _norm_token(lmap.get(c1, "")), _norm_token(lmap.get(c2, ""))
    if any(tok in l1 for tok in YES_ALIASES) or re.match(r"^\s*yes\b", l1):
        return c1, c2, lmap.get(c1, "Yes"), lmap.get(c2, "No")
    if any(tok in l2 for tok in YES_ALIASES) or re.match(r"^\s*yes\b", l2):
        return c2, c1, lmap.get(c2, "Yes"), lmap.get(c1, "No")
    if any(tok in l1 for tok in NO_ALIASES) or re.match(r"^\s*no\b", l1):
        return c2, c1, lmap.get(c2, "Yes"), lmap.get(c1, "No")
    if any(tok in l2 for tok in NO_ALIASES) or re.match(r"^\s*no\b", l2):
        return c1, c2, lmap.get(c1, "Yes"), lmap.get(c2, "No")
 
    if c1 == "1" and c2 == "0": return c1, c2, lmap.get(c1, "Yes"), lmap.get(c2, "No")
    if c2 == "1" and c1 == "0": return c2, c1, lmap.get(c2, "Yes"), lmap.get(c1, "No")
    if c1 == "1" and c2 == "2": return c1, c2, lmap.get(c1, "Yes"), lmap.get(c2, "No")
    if c2 == "1" and c1 == "2": return c2, c1, lmap.get(c2, "Yes"), lmap.get(c1, "No")
    
    if lmap.get(c1,"") <= lmap.get(c2,""):
        return c1, c2, lmap.get(c1, "Yes"), lmap.get(c2, "No")
    return c2, c1, lmap.get(c2, "Yes"), lmap.get(c1, "No")

def yes_share_for_var(df: pd.DataFrame, var: str, by: list[str]) -> pd.DataFrame:

    if var not in df.columns:
        return pd.DataFrame(columns=by + ["yes","no","n","value"])
    yes_code, no_code, _, _ = _infer_yes_no_codes(var)
    sub = df[df[var].notna()].copy()
    code_s = sub[var].map(_canon_code)
    valid = code_s.isin({yes_code, no_code})
    sub = sub.assign(_yes=(code_s == yes_code), _valid=valid)
    agg = (
        sub.groupby(by, dropna=False)
           .apply(lambda d: pd.Series({"yes": int(d["_yes"].sum()),
                                       "n":   int(d["_valid"].sum())}))
    )
    # Drop columns that duplicate index levels to avoid "cannot insert, already exists"
    for col in by:
        if col in agg.columns:
            agg = agg.drop(columns=[col])
    g = agg.reset_index()
    g["no"] = g["n"] - g["yes"]
    g["value"] = np.where(g["n"] > 0, (100.0 * g["yes"] / g["n"]).clip(0, 100), 0.0)
    return g

def _complete_zero_categories(g: pd.DataFrame, keys: list[str], resp_col: str, resp_order: list[str]) -> pd.DataFrame:
    all_keys = g[keys].drop_duplicates()
    rows = []
    for _, kv in all_keys.iterrows():
        mask = (g[keys] == kv.values).all(axis=1)
        present = set(g.loc[mask, resp_col].tolist())
        missing = [r for r in resp_order if r not in present]
        if missing:
            add = pd.DataFrame({**{k: [kv[k]]*len(missing) for k in keys},
                                resp_col: missing,
                                "cnt": [0]*len(missing),
                                "value": [0.0]*len(missing)})
            rows.append(add)
    if rows:
        g = pd.concat([g] + rows, ignore_index=True, sort=False)
    return g

# =============================================================================
# SECTION 36: GENERIC MULTI-SHARE CALCULATION
# =============================================================================
# multi_share_generic() calculates the % distribution of all response
# categories for a variable. This is the data behind stacked bar charts.
#
# SAME FOR ANY DATASET — completely generic.
# =============================================================================
def multi_share_generic(df: pd.DataFrame, var: str, by: list[str]):
    """
    Compute response shares of `var` grouped by columns in `by`.

    Robustness rule:
    If any grouping column is missing (e.g., some survey slices), create a
    constant bucket for it instead of crashing.
    """
    v_norm = str(var or "").strip().lower()
    by = [str(c).strip() for c in (by or []) if str(c).strip()]

    if df is None or getattr(df, "empty", False):
        return pd.DataFrame(columns=[*by, "resp", "n", "total", "pct"]), []

    work = df.copy()

    # Guarantee group-by columns exist
    for c in by:
        if c not in work.columns:
            work[c] = "All"

    # If the variable itself is missing, return empty
    if v_norm not in work.columns:
        return pd.DataFrame(columns=[*by, "resp", "n", "total", "pct"]), []

    sub = work[[*by, v_norm]].copy()

    # --- map numeric codes -> human response labels using Categories (localmultidem_codebook.csv)
    try:
        lmap = _code_label_map_strict(v_norm) or {}
    except Exception:
        lmap = {}

    code_s = sub[v_norm].map(_canon_code)

    # If we have labels, use them; otherwise fall back to canonical code
    sub["resp"] = code_s.map(lambda c: _strip_number_prefix(lmap.get(c, c)))
# Remove negative (routing) codes from plotting universe; they go to routing block instead
    sub = sub[~code_s.map(_is_negative_code)].copy()
    # Drop empty/null tokens and negative numeric routing codes only
    # Positive codes (88, 99, etc.) are valid responses for many variables
    routing_tokens = {"", "nan", "none"}
    code_txt = code_s.astype(str).str.strip().str.lower()
    sub = sub[~code_txt.isin(routing_tokens)].copy()

    # Drop negative numeric routing codes (< 0)
    code_num = pd.to_numeric(code_txt, errors="coerce")
    sub = sub[~(code_num < 0)].copy()

    if sub.empty:
        return pd.DataFrame(columns=[*by, "resp", "n", "total", "pct"]), []

    # Use CSV order from Column C for response ordering (PRIORITY 1)
    # _smart_sort_categories uses CATEGORY_ORDERS_FROM_CSV which preserves the exact order from the CSV
    unique_responses = sub["resp"].dropna().unique().tolist()
    resp_order = _smart_sort_categories(unique_responses, var=v_norm)

    g = (
        sub.groupby([*by, "resp"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    g["total"] = g.groupby(by, dropna=False)["n"].transform("sum")
    g["pct"] = g["n"] / g["total"].where(g["total"] > 0, np.nan) * 100.0
    g = g.replace([np.inf, -np.inf], np.nan).dropna(subset=["pct"])

    return g, resp_order


# =============================================================================
# SECTION 37: NONRESPONSE ANALYSIS
# =============================================================================
# Counts routing/missing codes (-995 to -999) per variable and labels them
# ("Question not asked", "Refused", "Don't know", "Missing").
#
# SAME FOR ANY DATASET — routing codes are standard in many surveys. Add
# new codes here only if your data uses different missing value codes.
# =============================================================================
def nonresponse_counts_labeled(df: pd.DataFrame, var: str) -> dict[str, int]:

    s = df[var]
    codes, labs = _codes_labels_for_strict(var)
    code_counts = s.map(_canon_code).value_counts(dropna=False)
    out = {}
    for c, l in zip(codes, labs):
        if _is_negative_numeric_code(c):
            out[l] = int(code_counts.get(_canon_code(c), 0))
    miss = int(s.isna().sum()) + int((s.astype(str).str.strip() == "").sum())
    out["Missing/blank"] = miss
    return out

def _count_special_codes(df: pd.DataFrame, var: str) -> dict[str, int]:
 
    if var not in df.columns:
        return {
            "8 Don’t know": 0,
            "88 Don’t know": 0,
            "9 Refusal": 0,
            "99 Refusal": 0,
            "9999 Refusal": 0,
        }
    s = df[var].map(_canon_code)
    return {
        "8 Don’t know":   int((s == "8").sum()),
        "88 Don’t know":  int((s == "88").sum()),
        "9 Refusal":      int((s == "9").sum()),
        "99 Refusal":     int((s == "99").sum()),
        "9999 Refusal":   int((s == "9999").sum()),
    }

var_type_map = dict(zip(labels_src["variable"], labels_src.get("type", pd.Series(dtype=int))))
visible_vars = [
    v
    for v in theme_df_raw["variable"].unique().tolist()
    if v in raw.columns
    and _norm_varname(v) in ALLOWED_VARS
    and _norm_varname(v) not in EXCLUDE_VARS
]

theme_df = theme_df_raw[theme_df_raw["variable"].isin(visible_vars)].copy()
theme_df = theme_df[~theme_df["variable"].map(_norm_varname).isin(EXCLUDE_VARS)].copy()
theme_df["type"] = theme_df["variable"].map(var_type_map).fillna(-1).astype(int)
theme_df = theme_df[theme_df["type"].isin([1, 2, 3, 4])].copy()
if theme_df.empty:
    warnings.warn("[WARN] No variables after theme/type/visibility gating; using raw-visible fallback.")
    theme_df = theme_df_raw[theme_df_raw["variable"].isin(visible_vars)].copy()
    theme_df["type"] = theme_df["variable"].map(var_type_map).fillna(-1).astype(int)

var_meta = theme_df[["theme", "subtheme", "variable", "type"]].drop_duplicates()

for c in ("group","qtype","q1","q35"):
    raw[c] = pd.to_numeric(raw[c], errors="coerce")
# Global rule: drop synthetic/invalid group -9 everywhere
raw = raw[pd.to_numeric(raw["group"], errors="coerce") != -9].copy()

raw = raw.dropna(subset=["city", "group", "qtype"]).copy()

raw = raw.assign(
    migrant_status = raw.qtype.map({1:"Immigrant origin", 2:"Autochthonous"}),
    gender         = raw.q1.map({1:"Male", 2:"Female"}).fillna("Other"),
    education      = raw.q35.map({1:"Primary", 2:"Secondary", 3:"Tertiary"}).fillna("Other"),
    group_name     = raw.group.map(lambda g: GROUP_NAMES.get(int(g) if pd.notna(g) else g, f"Group {g}")),
    city_full      = raw.city.map(to_city_full)
)
raw["group_disp"] = _group_disp_series(raw)

ALL_GROUP_IDS   = sorted(GROUP_NAMES)
ALL_GENDERS     = ["Male","Female","Other"]
ALL_CITIES      = sorted(raw.city.dropna().unique())
ALL_GROUP_NAMES = sorted(raw["group_name"].dropna().unique().tolist())
GROUP_COL_ACTIVE = GROUP_COL.copy()
GROUP_COL_ACTIVE["Autochthonous"] = AUTOCH_COLOR
STATUS_COL = {"Immigrant origin":"#5a9bd4","Autochthonous":AUTOCH_COLOR}
PAL_CITY   = px.colors.qualitative.Alphabet

def palette(key: str):
    mapping = {
        "group_disp": GROUP_COL_ACTIVE,  # <-- region shades now
        "group_name": GROUP_COL_ACTIVE,  # <-- same
        "migrant_status": STATUS_COL,
        "gender": px.colors.qualitative.Plotly,
        "education": px.colors.qualitative.Set2,
        "city_full": PAL_CITY,
    }
    return mapping.get(key, px.colors.qualitative.Plotly)

def _qs_dict(href: str) -> dict[str, list[str]]:
    """
    Парсинг query-параметров из href. Нужен для deep-linking из URL в состояние UI.
    """
    if not href: return {}
    return parse_qs(urlparse(href).query)
EXACT = {
    "birth_year": "q2",
    "arrival_year": "q4",
    "reason_arr": "q5",
    "came_alone": "opt1",
    "years_city": "q6",
    "legal": "q9",
    "born_in_country": "q3",
}
CANDS = {
    "birth_year":   ["q2","q02","year_of_birth","birth_year","yob","q2_year"],
    "arrival_year": ["q4","q04","year_of_arrival","arrival_year","yoa"],
    "reason_arr":   ["q5","reason_of_arrival","arrival_reason","q_5"],
    "came_alone":   ["opt1","came_alone","came_alone_yn","arrived_alone"],
    "years_city":   ["q6","years_in_city","years_city","yrs_city"],
    "legal":        ["q9","legal_situation","legal_status","legal"],
    "born_in_country": ["q3","q03","born_here","born_in_interview_country","country_of_birth_here"],
}

def _resolve(colkey: str) -> str|None:
    """
    Возвращает имя столбца для логического ключа colkey.
    Сначала проверяет EXACT, затем перебирает CANDS. Нет совпадений → None.
    """
    exact = EXACT[colkey]
    if exact in raw.columns: return exact
    for c in CANDS[colkey]:
        if c in raw.columns: return c
    return None

FVAR = {k:_resolve(k) for k in EXACT.keys()}

def _num_range(col: str|None, lo=None, hi=None, fallback=(0,100)):
    if not col or col not in raw.columns: return fallback
    s = pd.to_numeric(raw[col], errors="coerce").dropna()
    if s.empty: return fallback
    vmin, vmax = int(np.floor(s.min())), int(np.ceil(s.max()))
    if lo is not None: vmin = max(vmin, lo)
    if hi is not None: vmax = min(vmax, hi)
    if vmin > vmax: vmin, vmax = vmax, vmin
    return (vmin, vmax)

BY_MIN, BY_MAX = _num_range(FVAR["birth_year"], lo=1906, hi=1999, fallback=(1906,2025))
YA_MIN, YA_MAX = _num_range(FVAR["arrival_year"], lo=1905, hi=2020, fallback=(1905,2020))
YC_MIN, YC_MAX = _num_range(FVAR["years_city"],  lo=0, hi=Q6_MAX_HARD,  fallback=(0,99))

def _cat_opts(varname: str|None):
    if not varname: return [], []
    codes_lab, labels_lab = _positive_codes_and_labels(varname)
    if codes_lab and labels_lab:
        return ([{"label":lab, "value":str(code)} for code, lab in zip(codes_lab, labels_lab)],
                list(map(str, codes_lab)))
    s = raw[varname].map(_canon_code)
    vals = [v for v in sorted(s.dropna().unique().tolist()) if v != "" and not _is_negative_code(v)]
    return ([{"label":v, "value":v} for v in vals], vals)

REASON_OPTS, _REASON_ALL = _cat_opts(FVAR["reason_arr"])
LEGAL_OPTS,  _LEGAL_ALL  = _cat_opts(FVAR["legal"])

def _born_here_series(df: pd.DataFrame) -> pd.Series:
    """Determine if respondent was born in interview country based on Q3 or qtype.

    Handles multiple data formats:
      - Q3 as 1/2 coding (1 = born here, 2 = born abroad)
      - Q3 as country codes (ES, FR, IT...) compared to cntry (host country)
      - qtype as numeric (2 = autochthonous, 1 = immigrant)
      - qtype as string ("autochthonous", "immigrant origin")
    """
    out_arr = np.full(len(df), None, dtype=object)

    # 1) Try the configured born-in-country column (often q3)
    col = FVAR.get("born_in_country")
    if col and col in df.columns:
        s = df[col].astype(str).str.strip()
        s_low = s.str.lower()

        # Case A: classic 1/2 coding
        here   = s_low.isin({"1", "01", "1.0", "here", "yes"})
        abroad = s_low.isin({"2", "02", "2.0", "abroad", "no"})
        out_arr[here.to_numpy()]   = "HERE"
        out_arr[abroad.to_numpy()] = "ABROAD"

        # Case B: country-of-birth codes (e.g., ES/MA/EC) -> compare to host country
        still_none = pd.isna(pd.array(out_arr, dtype=object))
        if still_none.any() and "cntry" in df.columns:
            host = df["cntry"].astype(str).str.strip().str.upper().to_numpy()
            q3_upper = s.str.upper().to_numpy()
            # Only apply to rows that look like country codes (2-3 letter strings)
            looks_like_code = s.str.match(r'^[A-Za-z]{2,3}$', na=False).to_numpy()
            match_mask = still_none & looks_like_code
            out_arr[match_mask & (q3_upper == host)] = "HERE"
            out_arr[match_mask & (q3_upper != host)] = "ABROAD"

    # 2) Fallback to qtype for any remaining None values
    if "qtype" in df.columns:
        mask_none = np.array([x is None for x in out_arr])

        # Numeric qtype: 2 = autochthonous (born here), 1 = immigrant (born abroad)
        qn = pd.to_numeric(df["qtype"], errors="coerce").to_numpy()
        out_arr[(qn == 2) & mask_none] = "HERE"
        out_arr[(qn == 1) & mask_none] = "ABROAD"

        # String qtype fallback
        mask_none = np.array([x is None for x in out_arr])
        if mask_none.any():
            qt = df["qtype"].astype(str).str.strip().str.lower().to_numpy()
            out_arr[mask_none & np.isin(qt, ["autochthonous", "native"])] = "HERE"
            out_arr[mask_none & np.isin(qt, ["immigrant origin", "immigrant", "foreign-born"])] = "ABROAD"

    return pd.Series(out_arr, index=df.index, dtype=object)

def _load_questionnaire_map() -> dict[str, str]:
    path = QUESTION_CSV_PRIMARY if QUESTION_CSV_PRIMARY.exists() else QUESTION_CSV_FALLBACK
    if not path or not path.exists():
        return {}
    df = _read_questionnaire_table(path)
    cols = {str(c).strip().lower(): c for c in df.columns}
    id_col  = next((cols[k] for k in ("id","code","qid","var","variable") if k in cols), None)
    txt_col = next((cols[k] for k in ("question","text","label") if k in cols), None)
    if not id_col or not txt_col:
        raise SystemExit(f"[ERROR] questionnaire file needs ID and Question columns; got {list(df.columns)}")

    def norm_id(s: str) -> str:
        s = str(s or "").strip().upper()
        s = s.replace("-", "_").replace(".", "_")
        s = re.sub(r"\s+", "", s)
        return s

    m: dict[str,str] = {}
    for _, r in df.iterrows():
        _id = norm_id(r[id_col])
        if not _id: continue
        qtxt = str(r[txt_col]).strip()
        if _id not in m and qtxt:
            m[_id] = qtxt
    return m  
QMAP = _load_questionnaire_map()

def _find_questions_for_var(var: str) -> list[tuple[str,str]]:
    if not var: return []
    key = str(var).upper().replace(".", "_").replace("-", "_")
    key = re.sub(r"\s+", "", key)

    out = []
    for k, v in QMAP.items():
        if k == key:
            out.append((k, v))
    if out:
        seen = set(); uniq = []
        for k,v in out:
            if k not in seen:
                seen.add(k); uniq.append((k,v))
        return uniq[:8]
    for k, v in QMAP.items():
        if k.startswith(key):
            out.append((k, v))
    if not out:
        base = re.sub(r"[_A-Z]+$", "", key).rstrip("_")
        for k, v in QMAP.items():
            if k.startswith(base):
                out.append((k, v))
    seen = set(); uniq = []
    for k,v in out:
        if k not in seen:
            seen.add(k); uniq.append((k,v))
    return uniq[:8]

def _load_routing_map() -> dict[str, str]:
    path = QUESTION_CSV_PRIMARY if QUESTION_CSV_PRIMARY.exists() else QUESTION_CSV_FALLBACK
    if not path or not path.exists():
        return {}
    df = _norm_cols(_read_csv_salvage(path))
    if df.empty:
        return {}
    id_col = next((c for c in ["id","code","qid","var","variable"] if c in df.columns), None)
    if not id_col:
        return {}
    route_cols = [c for c in df.columns if any(k in c for k in ["route","routing","universe","filter","base","skip","instruction"])]
    if not route_cols:
        return {}
    def norm_id(s: str) -> str:
        s = str(s or "").strip().upper().replace("-", "_").replace(".", "_")
        return re.sub(r"\s+", "", s)
    m: dict[str, str] = {}
    for _, r in df.iterrows():
        rid = norm_id(r.get(id_col, ""))
        if not rid:
            continue
        chunks = []
        for c in route_cols:
            val = str(r.get(c, "")).strip()
            if val and val.lower() not in {"na", "n/a", "none"}:
                chunks.append(val)
        if chunks:
            seen = set(); ordered = []
            for t in chunks:
                if t not in seen:
                    seen.add(t); ordered.append(t)
            m[rid] = " | ".join(ordered)
    return m

ROUTING_MAP = _load_routing_map()

def routing_line_for_var(var: str) -> str:
    """Return routing/universe text for var if present; else empty string."""
    key = str(var or "").upper().replace("-", "_").replace(".", "_")
    key = re.sub(r"\s+", "", key)
    if key in ROUTING_MAP:
        return ROUTING_MAP[key]
    for k, v in ROUTING_MAP.items():
        if k.startswith(key):
            return v
    base = re.sub(r"[_A-Z]+$", "", key).rstrip("_")
    for k, v in ROUTING_MAP.items():
        if k.startswith(base):
            return v
    return ""
def _is_numeric_var(var: str) -> bool:
    """Flag for numeric/median variable.

    Sources:
      - manual/labels flag via _is_numeric_scale_from_labels (includes q17f, q17i, q17c etc.)
      - labels_src.type == 4 (type=4 in labels file)
      - fallback: presence of entries in MEDIANS_DF by variable
    Used to route such variables to median charts.
    """
    v = str(var or "").strip().lower()

    # Check the labels-based numeric scale flag first (includes manual overrides)
    try:
        if _is_numeric_scale_from_labels(v):
            return True
    except Exception:
        pass

    # Explicit typing from labels (type=4)
    t = int(var_type_map.get(v, -1)) if v in var_type_map else -1
    if t == 4:
        return True

    # Median CSV presence implies numeric/median chart
    try:
        if MEDIANS_DF is not None:
            m = MEDIANS_DF
            if "variable" in m.columns and (m["variable"].astype(str).str.strip().str.lower() == v).any():
                return True
    except Exception:
        pass

    return False

#  APP 

external_stylesheets = [
    dbc.themes.BOOTSTRAP,
    "https://fonts.googleapis.com/css2?family=Lato:wght@400;600;700&family=Merriweather:wght@400;700&display=swap",
]

app = Dash(__name__, external_stylesheets=external_stylesheets)

app.config.suppress_callback_exceptions = True

AUTOCH_LABEL = "Autochthonous"
AUTOCH_KEY   = "__AUTOCH__" 



def _filter_by_group_and_auto(df: pd.DataFrame, groups, show_auto: bool) -> pd.DataFrame:

    sub = df
    # Ensure group_disp exists
    if "group_disp" not in sub.columns:
        sub = sub.copy()
        sub["group_disp"] = _group_disp_series(sub)

    if groups:
        want_auto = AUTOCH_KEY in set(groups)
        numeric_groups = [g for g in groups if g != AUTOCH_KEY]
        mask_groups = sub["group"].isin(numeric_groups) if numeric_groups else False
        is_auto = pd.to_numeric(sub["qtype"], errors="coerce").eq(2) | (sub["group_disp"] == "Autochthonous")
        mask_auto = is_auto if want_auto else False
        sub = sub[mask_groups | mask_auto]

    if not show_auto:
        is_auto = pd.to_numeric(sub["qtype"], errors="coerce").eq(2) | (sub["group_disp"] == "Autochthonous")
        sub = sub[~is_auto]
    return sub

def radio(id_, opts, default, help_text=None):

    body = [dcc.RadioItems(
    id=id_, value=default, inline=True,
    options=[{"label": l, "value": v} for l, v in opts],
    style={"fontSize": "14px"},
    labelStyle={
        "display": "inline-block",
        "marginRight": "20px",
        "marginBottom": "6px",
        "paddingLeft": "4px",  # Space between radio circle and label text
    },
    inputStyle={
        "marginRight": "6px",  # Space between radio circle and label text
    },
)]

    if help_text:
        body.append(dbc.FormText(help_text, color="secondary", style={"fontSize": "12px"}))
    return html.Div(body, style={"marginTop": "6px", "marginBottom": "12px"})

def _marks(lo, hi, step):

    lo, hi, step = int(lo), int(hi), int(max(1, step))
    return {v: str(v) for v in range(lo, hi+1, step)}


CONTENT_STYLE = {
    "marginLeft": "0", "marginRight": "0", "padding": "1rem",
}

navbar = dbc.Navbar(
    dbc.Container([
        dbc.Button("Menu", id="open_menu", n_clicks=0, className="me-2", color="secondary"),
        html.Span("EMM Playground", className="navbar-brand mb-0 h1"),
    ], fluid=True),
    color="light", className="mb-3", sticky="top"
)

offcanvas_menu = dbc.Offcanvas(
    [
        html.H4("EMM Playground", className="mb-3"),
        html.Hr(),
        html.P("Navigate", className="lead"),
        dbc.Nav(
            [
                dbc.NavLink("Home", href="/", active="exact"),
                dbc.NavLink("GO TO THE PLAYGROUND", href="/playground", active="exact"),
                dbc.NavLink("READY MADE GRAPHS", href="/readymade", active="exact"),
            ],
            vertical=True, pills=True,
        ),
    ],
    id="sidebar", title="Menu", is_open=False, placement="start", scrollable=True
)

content = html.Div(id="page-content", style=CONTENT_STYLE)

app.layout = html.Div([
    html.Link(rel="stylesheet", href=f"/assets/brand.css?v={BRAND_ASSET_VER}"),
    dcc.Location(id="url"),
    dcc.Store(id="filters_state", data={}),
    navbar,
    offcanvas_menu,
    content
])

@app.callback(
    Output("sidebar", "is_open"),
    Input("open_menu", "n_clicks"),
    State("sidebar", "is_open"),
    prevent_initial_call=True
)
def _toggle_offcanvas(n, is_open):
    if n:
        return not is_open
    return is_open

#  EXAMPLES OF PRECOOKED GRAPHS (Playground-parity)
def _pc_label(var: str) -> str:
    v = str(var or "").strip().lower()
    # Explicit override for Q53 header wording
    if v == "q53":
        return "How well do you speak (Host country Language)?"
    lbl = dict_labels.get(v, "").strip()
    return lbl if lbl else v.upper()

# ------- Filtering helper used by the demo cards -------

def _pc_filter_base(
    df: pd.DataFrame,
    born: str | None = None,            # "HERE" or "ABROAD" (born in interview country)
    cities: list[str] | None = None,    # pretty city names, e.g. ["Madrid","Barcelona"]
    legal_codes: list[str] | None = None,
    reason_codes: list[str] | None = None,
    birth_year_gt: int | None = None,   # strictly greater than this year
) -> pd.DataFrame:
    sub = df.copy()

    # born in interview country via helper
    if born in {"HERE", "ABROAD"}:
        try:
            born_s = _born_here_series(sub)
            sub = sub[born_s == born]
        except Exception:
            pass

    # city filter (pretty names)
    if cities:
        want = {to_city_full(c) for c in cities}
        sub = sub[sub["city"].map(to_city_full).isin(want)]

    # legal situation (by resolved column name)
    if legal_codes and FVAR.get("legal") and FVAR["legal"] in sub.columns:
        sub = sub[sub[FVAR["legal"]].map(_canon_code).isin([str(x) for x in legal_codes])]

    # reason of arrival (by resolved column name)
    if reason_codes and FVAR.get("reason_arr") and FVAR["reason_arr"] in sub.columns:
        sub = sub[sub[FVAR["reason_arr"]].map(_canon_code).isin([str(x) for x in reason_codes])]

    # birth year strictly greater than
    if birth_year_gt is not None and FVAR.get("birth_year") and FVAR["birth_year"] in sub.columns:
        sub = sub[pd.to_numeric(sub[FVAR["birth_year"]], errors="coerce") > int(birth_year_gt)]

    return sub

def _pc_card(title: str, figure, note: str, survey_label: str = "LOCALMULTIDEM") -> dbc.Card:
    # Determine if the figure is a median chart (trace name includes 'Median')
    is_median = hasattr(figure, 'data') and any('Median' in str(tr.name) for tr in figure.data)
    display_config = {"displayModeBar": not is_median}
    header_children = [
        html.H2(title, className="h5 mb-0 d-inline"),
        dbc.Badge(survey_label, color="primary", className="ms-2"),
    ]
    return dbc.Card(
        [
            dbc.CardHeader(html.Div(header_children)),
            dbc.CardBody(
                [
                    html.P(note, className="text-muted small mb-2"),
                    dcc.Graph(figure=figure, config=display_config),
                ]
            ),
        ],
        className="shadow-sm mb-3",
    )

def _pc_yes(df: pd.DataFrame, var: str, note: str, sort_asc=False, sep=True, include_auto: bool=False) -> dbc.Card:
    """Playground yes-bar: primary=City, color=Group; include_auto=False by default."""
    fig = build_yes(
        df=df,
        var=var,
        colour_key="group_disp",
        x_key="city_full",
        orient="h",
        city_codes=None,
        groups=None,
        genders=("Male", "Female", "Other"),
        asc=sort_asc,
        show_auto=bool(include_auto),
        sep=sep,
        color_map_override=PRECOOKED_GROUP_COL,
    )
    title = f"{_pc_label(var)} — {str(var).upper()}"
    return _pc_card(title, fig, note)


def _pc_stack(df: pd.DataFrame, var: str, note: str, sort_asc=False, sep=True, primary: str = "group", include_auto: bool=False) -> dbc.Card:
    """Playground stacked: primary defaults to group; exclude autochthonous by default."""
    xk = "group_disp" if str(primary).lower() == "group" else "city_full"
    fig = build_stack(
        df=df,
        var=var,
        x_key=xk,
        orient="h",
        city_codes=None,
        groups=None,
        genders=("Male", "Female", "Other"),
        include_autochthonous=bool(include_auto),
        sep=sep,
        sort_asc=sort_asc,
    )
    title = f"{_pc_label(var)} — {str(var).upper()}"
    return _pc_card(title, fig, note)

READYMADE_VARS = ["q1604", "q24c07", "q24a11", "q3704", "q2302", "q33"]

def readymade_layout() -> dbc.Container:
    return dbc.Container(
        [
            html.H2("READY MADE GRAPHS", className="mt-3 mb-2"),
            dcc.Store(id="readymade_seed", data=int(time.time())),
            html.Div(id="readymade_cards"),
        ],
        fluid=True,
    )

# ADD THIS CALLBACK HERE:

def _pc_yesno_full(df: pd.DataFrame, var: str, description: str, primary: str = "city", include_auto: bool = True) -> dbc.Card:
    """
    Create a stacked bar chart showing BOTH Yes and No responses.
    This givesa complete view of the binary variable distribution.
    """
    xk = "group_disp" if str(primary).lower() == "group" else "city_full"
    
    fig = build_stack(
        df=df,
        var=var,
        x_key=xk,
        orient="h",
        city_codes=None,
        groups=None,
        genders=("Male", "Female", "Other"),
        include_autochthonous=bool(include_auto),
        sep=True,
        sort_asc=False,
    )
    
    title = f"{description} — {str(var).upper()}"
    note = f"All groups and cities included. Shows distribution of Yes and No responses."
    
    return _pc_card(title, fig, note)
@app.callback(
    Output("readymade_cards", "children"),
    Input("readymade_seed", "data"),
    prevent_initial_call=False
)
def populate_readymade(_seed):
    """
    Populate ready-made graphs page with selected variables.
    NO FILTERS APPLIED - shows all data.
    YES/NO variables display BOTH Yes and No bars.
    """
    cards: list[dbc.Card] = []
    
    # Selected variables for ready-made graphs
    readymade_variables = [
        ("q1604", "Interest in election under study", "city"),
        ("q24c07", "Contacted politician - People concerned", "group"),
        ("q24a11", "Member of ethnic organisation", "city"),
        ("q3704", "Registered to vote in host country", "city"),
        ("q2302", "Feel discriminated in employment", "group"),
        ("q33", "Feel close to party in country", "city"),
    ]
    
    try:
        df = raw.copy()  # NO FILTERS - use all data
        
        for var, description, primary_axis in readymade_variables:
            if var not in df.columns:
                print(f"Variable {var} not found in dataset, skipping...")
                continue
            
            try:
                # Determine if it's a yes/no variable (binary) or categorical (stacked)
                is_binary = _is_binary_var(var)
                
                if is_binary:
                    # For yes/no variables, show BOTH Yes and No using stacked bar
                    cards.append(
                        _pc_yesno_full(
                            df,
                            var,
                            description=description,
                            primary=primary_axis,
                            include_auto=True  # Include all data
                        )
                    )
                else:
                    # For categorical variables, use stacked bar chart
                    cards.append(
                        _pc_stack(
                            df,
                            var,
                            note=f"{description} - All groups and cities included",
                            primary=primary_axis,
                            include_auto=True  # Include all data
                        )
                    )
            except Exception as e:
                print(f"Error creating graph for {var}: {e}")
                continue
        
        if not cards:
            return dbc.Alert(
                [
                    html.H4("No Ready-Made Graphs Available", className="alert-heading"),
                    html.P("Unable to generate example graphs. Please try the Data Playground instead."),
                ],
                color="info"
            )
        
        return dbc.Container(cards, fluid=True, className="mt-3")
    
    except Exception as e:
        print(f"Error in populate_readymade: {e}")
        import traceback
        traceback.print_exc()
        return dbc.Alert(f"Error loading ready-made graphs: {e}", color="danger")
def examples_layout() -> dbc.Container:
    cards: list[dbc.Card] = []

    df1 = raw.copy()
    cards.append(
        _pc_yes(
            df1,
            "q24a06",
            note="Filters: All groups and all cities. Autochthonous excluded. Primary = City; color = Group.",
            include_auto=False,
        )
    )

    df2 = _pc_filter_base(raw, cities=["Madrid", "Barcelona"])
    cards.append(
        _pc_yes(
            df2,
            "q24b07",
            note="Filters: Cities = Madrid, Barcelona. Autochthonous excluded. Primary = City; color = Group.",
            include_auto=False,
        )
    )
    df3 = _pc_filter_base(raw, born="ABROAD", reason_codes=["3"])  # Study
    cards.append(
        _pc_stack(
            df3,
            "q3609",
            note="Filters: Not born in interview country (ABROAD) AND Reason of arrival = 3 (Study). Autochthonous excluded. Primary = Group; color = Response.",
            primary="group",
            include_auto=False,
        )
    )
    df4 = _pc_filter_base(raw, born="ABROAD", legal_codes=["1"])
    cards.append(
        _pc_stack(
            df4,
            "q53",
            note="Filters: Not born in interview country (ABROAD) AND Legal situation = 1 (Short-term permit ≤ 5). Autochthonous excluded. Primary = Group; color = Response.",
            primary="group",
            include_auto=False,
        )
    )

    df5 = _pc_filter_base(raw, born="ABROAD")
    cards.append(
        _pc_yes(
            df5,
            "q24a11",
            note="Filters: Not born in interview country (ABROAD). Autochthonous excluded. Primary = City; color = Group.",
            include_auto=False,
        )
    )

    if "q24a01" in raw.columns:
        df6 = _pc_filter_base(raw, born="ABROAD")
        cards.append(_pc_yes(df6, "q24a01", note="Filters: Not born in interview country (ABROAD). Autochthonous excluded. Primary = City; color = Group.", include_auto=False))

    if "q24a12" in raw.columns:
        df7 = _pc_filter_base(raw, born="ABROAD")
        cards.append(_pc_yes(df7, "q24a12", note="Filters: Not born in interview country (ABROAD). Autochthonous excluded. Primary = City; color = Group.", include_auto=False))

    if "q25" in raw.columns:
        df8 = _pc_filter_base(raw, born="ABROAD")
        cards.append(_pc_yes(df8, "q25", note="Filters: Not born in interview country (ABROAD). Autochthonous excluded. Primary = City; color = Group.", include_auto=False))

    return dbc.Container(
        [html.H2("EXAMPLES OF PRECOOKED GRAPHS", className="mt-3 mb-3"), *cards],
        fluid=True,
    )



# PLAYGROUND


def playground_layout() -> dbc.Container:
    box_gap = {"marginTop": "10px", "marginBottom": "18px"}
    section_gap = {"marginTop": "18px", "marginBottom": "26px"}
    return dbc.Container([
        dcc.Store(id="req_subtheme"),
        dcc.Store(id="vtype_store"),
        dcc.Store(id="vmode_store", data="stack"),
        dcc.Store(id="last_click_ctx"),  # for click → breakdown logic

        dbc.Row(
            [
                dbc.Col(ethmig_logo(), width="auto", align="center"),
                dbc.Col(html.H2(APP_TITLE, className="my-2"), align="center"),
            ],
            align="center",
            className="mb-2",
        ),
        
# Survey
dbc.Col(html.Div([
    dbc.Label("Survey"),
    dcc.Dropdown(
        id="survey",
        options=[
            {"label": "LOCALMULTIDEM", "value": "localmulti"},
            {"label": "Civic & Political Integration", "value": "civicpol"},
        ],
        value="localmulti",
        clearable=False,
        style={"fontSize": "14px"},
    ),
    dbc.FormText(
        "Choose which survey to explore. Themes and variables update accordingly.",
        color="secondary"
    )
], style=box_gap), xs=12, md=4),
        #  data
        dbc.Card(dbc.CardBody([
            html.Div("Select data", className="fw-bold mb-2"),
            dbc.Row(className="g-4", children=[
                # Theme
                dbc.Col(html.Div([
                    dbc.Label("Theme"),
                    dcc.Dropdown(
                        id="theme",
                        options=[],
                        value=None,
                        clearable=False,
                        style={
                            "fontSize": "14px",
                            "lineHeight": "1.6",
                        },
                        optionHeight=50,
                    ),
                    dbc.FormText("Choose a broad domain. Variables are grouped by theme.", color="secondary")
                ], style=box_gap), xs=12, md=4),

                # Subtheme
                dbc.Col(html.Div([
                    dbc.Label("Subtheme"),
                    dcc.Dropdown(
                        id="subtheme",
                        options=[],
                        value=None,
                        clearable=True,
                        placeholder="All subthemes",
                        style={
                            "fontSize": "14px",
                            "lineHeight": "1.6",
                        },
                        optionHeight=50,
                    ),
                    dbc.FormText("Refine within a theme. Empty means all variables in the theme.", color="secondary")
                ], style=box_gap), xs=12, md=4),

                # Variable
                dbc.Col(html.Div([
                    dbc.Label("Variable"),
                    dcc.Dropdown(
                        id="var",
                        options=[],
                        value=None,
                        clearable=False,
                        style={
                            "fontSize": "14px",
                            "lineHeight": "1.6",
                        },
                        optionHeight=60,
                    ),
                    dbc.FormText("Pick one variable. If wording is missing, code is shown.", color="secondary")
                ], style=box_gap), xs=12, md=4),
            ]),
        ]), className="mb-3"),

dbc.Card(
    id="display_mode_card",               # we can hide/show the whole card
    className="mb-3",
    children=dbc.CardBody([
        html.Div("Display mode", className="fw-bold mb-2"),
        # Create display_mode directly in the layout so it always exists
        dcc.RadioItems(
            id="display_mode",
            options=[
                {"label": "Stacked distribution", "value": "stack"},
                {"label": "Yes bar", "value": "yes"},
            ],
            value="stack",
            inline=True,
            style={"fontSize": "14px"},
            labelStyle={
                "display": "inline-block",
                "marginRight": "28px",  # Space between options
                "paddingLeft": "4px",   # Space after radio circle
            },
            inputStyle={
                "marginRight": "6px",   # Space between radio circle and label text
            },
        ),
        dbc.FormText(
            "Stacked = full response distribution. Yes bar = share of 'Yes' only. "
            'Tip: click the "Yes" segment in a stacked chart to jump to Yes bar.',
            color="secondary"
        ),
    ])
),

        dbc.Card(dbc.CardBody([
          
           
            dbc.Button("More filters", id="more_filters_btn", color="secondary", outline=True, className="mb-3 me-2"),
            dbc.Button("Less filters", id="less_filters_btn", color="secondary", outline=True, className="mb-3 me-2", style={"display": "none"}),
            dbc.Button("Reset All Filters", id="reset_filters_btn", color="danger", outline=True, className="mb-3"),
            dbc.Collapse(id="more_filters_collapse", is_open=False, children=[

                # Chart options
                html.Div("Chart options", className="fw-bold", style=section_gap),
                dbc.Row(className="g-4", children=[
               
                    dbc.Col(dbc.Checkbox(
                        id="autoch", label="Include autochthonous sub-sample",
                        value=True, className="py-1", style={"marginTop": "6px"}
                    ), xs=12, sm="auto"),

                    dbc.Col(radio(
                        "axis",
                        [("Group × City", "group"), ("City × Group", "city")], "city",
                        help_text="Switch which dimension is primary."
                    ), xs=12, md="auto", style={"marginRight": "20px"}),

                    dbc.Col(radio(
                        "orient", [("Vertical", "v"), ("Horizontal", "h")], "h",
                        help_text="Rotate the chart."
                    ), xs=12, md="auto", style={"marginRight": "20px"}),

                    dbc.Col(radio(
                        "sort", [("High→Low", "desc"), ("Low→High", "asc")], "desc",
                        help_text="Sort secondaries within each primary by the share of the first response."
                    ), xs=12, md="auto", style={"marginRight": "20px"}),

                    dbc.Col(dcc.Checklist(
                        id="comp_aids",
                        options=[{"label": "Primary separators", "value": "sep"}],
                        value=["sep"], inline=True, className="py-1", style={"fontSize": "14px"}
                    ), xs=12),
                ]),

                html.Hr(className="my-3"),

                # IMMIGRATION FILTERS - Hidden for CivicPol survey
                html.Div(id="immigration-filters-section", children=[
                    html.Div("Filter: Country of birth", className="fw-bold", style=section_gap),
                    dbc.Row(className="g-4", children=[
                        dbc.Col(html.Div([
                            dcc.RadioItems(
                                id="born_here",
                                options=[
                                    {"label": "No filter", "value": "ANY"},
                                    {"label": "Born in interview country", "value": "HERE"},
                                    {"label": "Not born in interview country", "value": "ABROAD"},
                                ],
                                value="ANY",
                                inline=True,
                                className="py-1",
                                style={"fontSize": "14px", "lineHeight": "1.8"},
                                labelStyle={
                                    "display": "inline-block",
                                    "marginRight": "20px",
                                    "marginBottom": "8px",
                                    "paddingLeft": "4px",
                                },
                                inputStyle={"marginRight": "6px"},
                            ),
                            dbc.FormText(
                                "Selecting 'Not born in interview country' enables migration-specific filters below.",
                                color="secondary"
                            ),
                        ], style=box_gap), md=12, xs=12),
                    ]),

                    html.Hr(className="my-3"),
                    html.Div("Filters: Migration biography", className="fw-bold", style=section_gap),
                    html.Div("Active only if you filter to 'Not born in interview country'.", className="text-muted mb-2"),
                    html.Div(id="box3", children=[
                
                    dbc.Row(className="g-4", children=[
                        dbc.Col(html.Div([
                            dbc.Label("Year of Arrival (Q4)"),
                            dcc.RangeSlider(
                                id="yoa_rng", min=int(YA_MIN), max=int(YA_MAX), step=1,
                                value=[int(YA_MIN), int(YA_MAX)], allowCross=False,
                                marks=_marks(int(YA_MIN), int(YA_MAX),
                                             max(1, (int(YA_MAX) - int(YA_MIN)) // 5 or 1)),
                                tooltip={"placement": "bottom", "always_visible": False}
                            ),
                            dbc.FormText("Drag to select the arrival window.", color="secondary"),
                        ], style=box_gap), md=12, xs=12),
                    ]),
            
                    dbc.Row(className="g-4", children=[
                        dbc.Col(html.Div([
                            dbc.Label("Years in the City (Q6)"),
                            dcc.Checklist(
                                id="yc_life",
                                options=[{"label": "Include “All or almost all of my life”", "value": "LIFE"}],
                                value=[], inline=True, className="py-1", style={"fontSize": "14px"}
                            ),
                            dcc.RangeSlider(
                                id="yc_rng", min=int(YC_MIN), max=int(min(YC_MAX, Q6_MAX_HARD)), step=1,
                                value=[int(YC_MIN), int(min(YC_MAX, Q6_MAX_HARD))], allowCross=False,
                                marks=_marks(int(YC_MIN), int(min(YC_MAX, Q6_MAX_HARD)),
                                             max(1, (int(min(YC_MAX, Q6_MAX_HARD)) - int(YC_MIN)) // 6 or 1)),
                                tooltip={"placement": "bottom", "always_visible": False}
                            ),
                            dbc.FormText("Combine LIFE code with a numeric range if needed.", color="secondary"),
                        ], style=box_gap), md=12, xs=12),
                    ]),
             
                    dbc.Row(className="g-4", children=[
                        dbc.Col(html.Div([
                            dbc.Label("Reason of Arrival (Q5)"),
                            dcc.Dropdown(
                                id="reason_fil", options=REASON_OPTS, value=[],
                                multi=True, placeholder="All reasons", style={"fontSize": "14px"}
                            ),
                            dbc.FormText("Multi-select. Empty = all.", color="secondary"),
                        ], style=box_gap), md=4, xs=12),

                        dbc.Col(html.Div([
                            dbc.Label("Came Alone (OPT1)"),
                            dcc.RadioItems(
                                id="alone_radio",
                                options=[{"label": "Any", "value": "ANY"},
                                         {"label": "Yes", "value": "YES"},
                                         {"label": "No", "value": "NO"}],
                                value="ANY", inline=True, className="py-1", style={"fontSize": "14px"},
                                labelStyle={"marginRight": "20px", "paddingLeft": "4px"},
                                inputStyle={"marginRight": "6px"},
                            )
                        ], style=box_gap), md=4, xs=12),

                        dbc.Col(html.Div([
                            dbc.Label("Legal Situation (Q9)"),
                            dcc.Dropdown(
                                id="legal_fil", options=LEGAL_OPTS, value=[],
                                multi=True, placeholder="All legal situations", style={"fontSize": "14px"}
                            ),
                            dbc.FormText("Multi-select. Empty = all.", color="secondary"),
                        ], style=box_gap), md=4, xs=12),
                    ]),
                ]),
                ]),  # END of immigration-filters-section

                html.Hr(className="my-3"),

                html.Div("Filters: Demography", className="fw-bold", style=section_gap),

                dbc.Row(className="g-4", children=[
                dbc.Col(html.Div([
                    dbc.Label("City"),
                    dcc.Dropdown(
                        id="city_fil",
                        options=[], value=[],
                        multi=True, placeholder="All cities", style={"fontSize": "14px"},
                        persistence=True,
                        persistence_type="session",
                    ),
                    dbc.FormText("Multi-select. Empty = all.", color="secondary"),
                ], style=box_gap), md=6, xs=12),

                dbc.Col(html.Div([
                    dbc.Label("Group"),
                    dcc.Dropdown(
                        id="group_fil",
                        options=[], value=[],
                        multi=True, placeholder="All groups", style={"fontSize": "14px"},
                        persistence=True,
                        persistence_type="session",
                    ),
                    dbc.FormText("Multi-select. Empty = all.", color="secondary"),
                ], style=box_gap), md=6, xs=12),
                ]),

                dbc.Row(className="g-4", children=[
                dbc.Col(html.Div([
                    dbc.Label("Gender"),
                    dcc.Dropdown(
                        id="gender_fil",
                        options=[{"label": g, "value": g} for g in ALL_GENDERS],
                        value=ALL_GENDERS, multi=True, style={"fontSize": "14px"},
                        persistence=True,
                        persistence_type="session",
                    ),
                    dbc.FormText("Filter respondents by gender.", color="secondary"),
                ], style=box_gap), md=6, xs=12),

                    dbc.Col(html.Div([
                        dbc.Label("Year of Birth (Q2)"),
                        dcc.RangeSlider(
                            id="yob_rng", min=1906, max=1999, step=1,
                            value=[BY_MIN, BY_MAX], allowCross=False,
                            marks=_marks(1906, 1999, 10),
                            tooltip={"placement": "bottom", "always_visible": False}
                        ),
                        dbc.FormText("Drag to select birth years.", color="secondary"),
                    ], style=box_gap), md=6, xs=12),
                ]),
            ]),
        ]), className="mb-3"),

        html.Div(id="var_label", className="text-muted small mb-2"),
        hscroll(
            dcc.Graph(
                id="graph",  # IMPORTANT: callbacks write to Output("graph", "figure")
                figure=go.Figure(
                    layout=go.Layout(
                        title="Select a variable to see the chart",
                        transition={"duration": 0},
                        **{k: v for k, v in DEFAULT_BAR_LAYOUT.items() if k != "transition"}
                    )
                ),
                config={
                    "responsive": False, 
                    "displayModeBar": True,
                    "toImageButtonOptions": {
                        "format": "jpeg",
                        "filename": "graph",
                        "height": 1200,
                        "width": 1800,
                        "scale": 3  # High quality (3x resolution)
                    }
                },
                style={"height": "auto", "minHeight": "740px", "width": "100%"}
            )
        ),
      
        # data-preview area (first rows) + CSV download for the CURRENT figure's data
        playground_data_area(),

        html.Div(id="click_stats", className="small mt-2", style={"lineHeight": "1.4"}),


        html.Div(id="question_table", className="small mt-2", style={"lineHeight": "1.35"}),
        html.Div(id="routing_info", className="text-muted small mt-2"),
        html.Div(id="footnote", className="small mt-2", style={"lineHeight": "1.35"})
    ], fluid=True, style={"maxWidth": "1400px"})
def _df_preview(df: pd.DataFrame, max_rows: int = 0) -> pd.DataFrame:
    try:
        df = df.copy()
        return df if max_rows <= 0 else df.head(max_rows)
    except Exception:
        return pd.DataFrame()


def playground_data_area():
 
    return html.Div(
        id="pg-data-area",
        style={"marginTop": "16px"},  # Reduced from 100px to 16px (about 6x smaller)
        children=[ 
            html.Div(
                "Preview of the data used in the graph (first rows)",
                className="text-muted small mb-1"
            ),
            dash_table.DataTable(
                id="pg-data-table",
                columns=[],
                data=[],
                page_action="none",
                style_table={"overflowX": "auto", "maxHeight": "600px", "overflowY": "auto"},
                style_cell={"fontSize": 12, "padding": "6px", "whiteSpace": "normal", "height": "auto"},
            ),
            html.Div(
                [
                    dbc.Button("Download CSV", id="pg-btn-dl", size="sm", color="secondary", className="mt-2"),
                    dcc.Download(id="pg-dl"),
                ]
            ),
        ],
    )

def _standardize_table(df: pd.DataFrame, var: str = "") -> pd.DataFrame:
    """Normalize any table_df to: City | Group | Response | N | Total | Percentage."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["City", "Group", "Response", "N", "Total", "Percentage"])
    out = df.copy()
    # Rename known column variants to standard names
    rename = {}
    for col in out.columns:
        cl = str(col).lower().strip()
        if cl in ("city_full", "city", "cityname", "city_name", "primary"):
            if "City" not in rename.values():
                rename[col] = "City"
        elif cl in ("group_disp", "group_name", "group", "secondary"):
            if "Group" not in rename.values():
                rename[col] = "Group"
        elif cl in ("resp", "response", "answer", "label"):
            rename[col] = "Response"
        elif cl == "n" and "N" not in rename.values():
            rename[col] = "N"
        elif cl in ("total", "_n"):
            rename[col] = "Total"
        elif cl in ("pct", "percentage", "share"):
            rename[col] = "Percentage"
        elif cl == "yes" and "N" not in rename.values():
            rename[col] = "N"
    out = out.rename(columns=rename)
    # For binary yes/no tables: Response = "Yes", N = yes count, Total = n
    if "yes" in df.columns and "no" in df.columns:
        if "Response" not in out.columns:
            out["Response"] = "Yes"
        if "Total" not in out.columns and "n" in df.columns:
            out["Total"] = df["n"]
    # For box plot tables (median, q1, q3): Response = var name, use median as info
    if "median" in df.columns:
        if "Response" not in out.columns:
            out["Response"] = str(var) if var else "Value"
    # Ensure all required columns exist
    for c in ("City", "Group", "Response", "N", "Total", "Percentage"):
        if c not in out.columns:
            if c == "Response" and var:
                out[c] = str(var)
            elif c == "Percentage" and "N" in out.columns and "Total" in out.columns:
                n_col = pd.to_numeric(out["N"], errors="coerce")
                t_col = pd.to_numeric(out["Total"], errors="coerce")
                out[c] = np.where(t_col > 0, (100.0 * n_col / t_col).round(1), 0.0)
            else:
                out[c] = ""
    # Round percentage
    if "Percentage" in out.columns:
        out["Percentage"] = pd.to_numeric(out["Percentage"], errors="coerce").round(1)
    # Select and order columns
    return out[["City", "Group", "Response", "N", "Total", "Percentage"]].reset_index(drop=True)


def _pg_table_payload(df: pd.DataFrame, var: str = ""):
    """
    Returns (columns, data) for dash_table.
    Standardizes to: City | Group | Response | N | Total | Percentage.
    """
    std = _standardize_table(df, var=var)
    cols = [{"name": c, "id": c} for c in std.columns]
    data = std.to_dict("records")
    return cols, data

def _pg_download_callback_register(data_supplier):
    """
    Wire up the download button to stream the full table (not just the preview) as CSV.
    data_supplier must be a zero-arg callable returning dict with 'df' and 'var' keys.
    Call this once when you build the Playground layout/callbacks.
    """
    @app.callback(Output("pg-dl", "data"), Input("pg-btn-dl", "n_clicks"), prevent_initial_call=True)
    def _do_pg_download(n):
        try:
            data = data_supplier()
            df = data.get("df", pd.DataFrame())
            var_name = str(data.get("var", "data")).strip().lower()
            # Sanitize variable name for filename
            safe_var = re.sub(r'[^\w\-]', '_', var_name) if var_name else "data"
            filename = f"playground_{safe_var}.csv"
            if df is None or df.empty:
                return dcc.send_string("", filename=filename)
            return dcc.send_data_frame(df.to_csv, filename, index=False)
        except Exception:
            return dcc.send_string("", filename="playground_data.csv")

def home_layout() -> dbc.Container:
    """
    Final home page with:
    1. Title and logo
    2. How the Data Playground Works section (with ETHMIGSURVEYDATA network info)
    3. LOCALMULTIDEM survey section with full details
    4. Civic & Political Integration survey section with full details
    5. Ready-Made Graphs button (Examples button removed)
    """
    
    content = [
        # === HEADER WITH LOGO AND TITLE ===
        dbc.Row(
            [
                dbc.Col(ethmig_logo(style={"height": "80px"}), width="auto", align="center"),
                dbc.Col(
                    html.H1("EMM Survey Data Playground", className="mt-3", style={"marginBottom": "0"}), 
                    align="center"
                ),
            ],
            align="center",
            className="mt-3",
            style={"marginBottom": "48px"},  # More space after title
        ),
        
        # === HOW THE DATA PLAYGROUND WORKS ===
        html.Div([
            html.H3("The Ethnic and Migrant Minorities (EMM) Survey Data Playground", style={"marginBottom": "20px", "color": "#2c3e50"}),
            
            html.P([
                "The EMM Survey Data Playground is part of ",
                html.Strong("ETHMIGSURVEYDATA – The International Ethnic and Immigrant Minorities' Survey Data Network"),
                ". It is an interactive platform designed to help you explore and visualize survey data about migration, integration, and civic participation across Europe. "
                "Whether you're a researcher, student, or policy analyst, this tool makes complex survey data accessible and actionable."
            ], style={"marginBottom": "16px", "lineHeight": "1.6"}),
            
            html.H5("Getting Started:", style={"marginBottom": "12px", "fontWeight": "600"}),
            html.Ul([
                html.Li([
                    html.Strong("Select a Survey: "),
                    "Choose from LOCALMULTIDEM or Civic & Political Integration post-harmonised local-level surveys using the buttons below."
                ], style={"marginBottom": "8px"}),
                html.Li([
                    html.Strong("Browse Variables: "),
                    "Navigate through thematic categories (e.g., Political Participation, Discrimination, Migration Biography) to find specific survey questions."
                ], style={"marginBottom": "8px"}),
                html.Li([
                    html.Strong("Apply Filters: "),
                    "Refine your analysis by city, migrant group, gender, age, year of arrival, and many other demographic characteristics."
                ], style={"marginBottom": "8px"}),
                html.Li([
                    html.Strong("Visualize Data: "),
                    "View results as interactive charts such as stacked bar charts for categorical responses, box plots for numeric scales, and specialized visualizations for specific question types."
                ], style={"marginBottom": "8px"}),
                html.Li([
                    html.Strong("Download & Share: "),
                    "Export charts as images or download the underlying data CSV tables for further analysis."
                ], style={"marginBottom": "8px"}),
                html.Li([
                    html.Strong("Explore Ready-Made Graphs: "),
                    "Access a curated collection of pre-generated visualizations highlighting key findings and trends across the datasets."
                ], style={"marginBottom": "8px"}),
            ], style={"marginBottom": "24px", "lineHeight": "1.6"}),
            
            html.P(
                "The platform handles missing values and special codes automatically, displaying only valid responses for clear interpretation.",
                style={"marginBottom": "16px", "lineHeight": "1.6", "fontStyle": "italic", "color": "#555"}
            ),
        ], style={"marginBottom": "48px", "padding": "24px", "backgroundColor": "#f8f9fa", "borderRadius": "8px"}),
        
        # === SURVEY 1: LOCALMULTIDEM ===
        html.Div([
            html.H3("LOCALMULTIDEM Survey", style={"marginBottom": "20px", "color": "#2c3e50"}),
            
            html.P(
                'LOCALMULTIDEM ("Multicultural Democracy and Immigrants\' Social Capital in Europe") is a cross-national, individual-level survey conducted between 2004 and 2008 across 11 major European cities in 8 countries. '
                "Additionally, a team based at Université Libre de Bruxelles replicated a large part of the questionnaire in Brussels (Belgium), and Zakaria Sajir replicated parts of the questionnaire in Turin (Italy). "
                "The combined pooled dataset comprises over 11,000 interviews and covers more than 20 ethnic/migrant minority groups, with structured sampling strategies adapted to each city's legal-institutional and demographic context.",
                style={"marginBottom": "16px", "lineHeight": "1.6"}
            ),
            
            html.P(
                "The survey explores six major dimensions of immigrant integration: civic and political participation, organizational affiliations, experiences of discrimination and institutional trust, migration trajectories and transnational ties, social capital and identity formation, and socioeconomic profiles. "
                "Data was collected using probability sampling, snowball methods, and aggregation center techniques, with multilingual questionnaires administered via CATI or face-to-face interviews.",
                style={"marginBottom": "20px", "lineHeight": "1.6"}
            ),
            
            html.H5("Cities Covered in Alpha Version of the Playground:", style={"marginBottom": "12px", "fontWeight": "600"}),
            html.Ul([
                html.Li("Barcelona and Madrid (Spain)"),
                html.Li("Budapest (Hungary)"),
                html.Li("Geneva and Zurich (Switzerland)"),
                html.Li("London (United Kingdom)"),
                html.Li("Lyon (France)"),
                html.Li("Milan and Turin (Italy)"),
                html.Li("Oslo (Norway)"),
                html.Li("Stockholm (Sweden)"),
            ], style={"marginBottom": "20px", "columnCount": "2", "columnGap": "24px"}),
            
            html.H5("Data Sources:", style={"marginBottom": "12px", "fontWeight": "600"}),
            html.Ul([
                html.Li([
                    'Morales, Laura; Anduiza, Eva; Bengtsson, Bo; Cinalli, Manlio; Diani, Mario; Giugni, Marco; Orkeny, Antal; Rogstad, Jon; Statham, Paul, 2014, "LOCALMULTIDEM and MDE Individual Survey (WP4) Dataset, 2004-2008", ',
                    html.A("https://doi.org/10.7910/DVN/24987", href="https://doi.org/10.7910/DVN/24987", target="_blank", style={"textDecoration": "none"}),
                    ", Harvard Dataverse, V5."
                ], style={"marginBottom": "8px"}),
                html.Li([
                    'Sajir, Zakaria, 2017, "Individual-level Survey - Moroccan-origin Community of Turin", ',
                    html.A("https://doi.org/10.7910/DVN/3MRMUR", href="https://doi.org/10.7910/DVN/3MRMUR", target="_blank", style={"textDecoration": "none"}),
                    ", Harvard Dataverse, V2."
                ], style={"marginBottom": "8px"}),
            ], style={"marginBottom": "20px"}),
            
            html.H5("Questionnaire & Documentation:", style={"marginBottom": "12px", "fontWeight": "600"}),
            html.Ul([
                html.Li([
                    "Questionnaire (PDF, English): ",
                    html.A("Harvard Dataverse – Questionnaire file", href="https://doi.org/10.7910/DVN/24987", target="_blank", style={"textDecoration": "none"})
                ], style={"marginBottom": "8px"}),
                html.Li([
                    "Full dataset and documentation: ",
                    html.A("Harvard Dataverse entry", href="https://doi.org/10.7910/DVN/24987", target="_blank", style={"textDecoration": "none"})
                ], style={"marginBottom": "8px"}),
            ], style={"marginBottom": "24px"}),
            
            dbc.Button(
                "Access LOCALMULTIDEM Data", 
                href="/playground?survey=localmulti", 
                color="primary", 
                size="lg",
                style={"marginBottom": "16px"}
            ),
        ], style={"marginBottom": "48px", "padding": "24px", "backgroundColor": "#ffffff", "border": "1px solid #dee2e6", "borderRadius": "8px"}),
        
        # === SURVEY 2: CIVIC & POLITICAL INTEGRATION ===
        html.Div([
            html.H3("Civic & Political Integration Post-Harmonised Local-Level Survey", style={"marginBottom": "20px", "color": "#2c3e50"}),
            
            html.P(
                "The Civic & Political Integration survey is a post-harmonized dataset developed within WP3 of COST Action CA16111 (ETHMIGSURVEYDATA). "
                "This comprehensive dataset focuses on understanding migrants' civic and political participation at both local and national levels across multiple European countries. "
                "The post-harmonization work was undertaken jointly by the ANR-funded FAIRETHMIGQUANT project and the Swiss National Science Foundation–funded project on Muslim migrant integration, "
                "and was completed in 2025 as part of the CHIST-ERA–funded OPENMIN project.",
                style={"marginBottom": "16px", "lineHeight": "1.6"}
            ),
            
            html.P(
                "The dataset examines key dimensions of political and civic integration including electoral behaviors (turnout, party preference, voting intentions), "
                "non-electoral political behaviors, associational membership and civic engagement, political interest and knowledge, civic and political attitudes and orientations, "
                "media consumption patterns, and various sociopolitical attitudes. The survey complements LOCALMULTIDEM by providing deeper insights into the political dimensions "
                "of immigrant integration, including participation in political organizations, trust in democratic institutions, and attitudes toward citizenship and political representation.",
                style={"marginBottom": "20px", "lineHeight": "1.6"}
            ),
            
            html.H5("Thematic Coverage:", style={"marginBottom": "12px", "fontWeight": "600"}),
            html.Ul([
                html.Li("Electoral behaviors (voting turnout, party preferences, voting intentions)"),
                html.Li("Non-electoral political participation"),
                html.Li("Associational membership and civic engagement"),
                html.Li("Political interest, knowledge, and media consumption"),
                html.Li("Civic and political attitudes and orientations"),
                html.Li("Identity, belonging, and social attitudes"),
                html.Li("Sociodemographic characteristics and migration trajectories"),
                html.Li("Religious affiliation and practices"),
            ], style={"marginBottom": "20px"}),
            
          
            html.H5("Project Team & Acknowledgments:", style={"marginBottom": "12px", "fontWeight": "600"}),
            html.P([
                "This work was overseen by ",
                html.Strong("Laura Morales (CSIC & Sciences Po, CEE)"),
                " in collaboration with ",
                html.Strong("Katia Pilati"),
                ". Key contributors include ",
                html.Strong("Natalia Malancu (University of Geneva)"),
                ", ",
                html.Strong("Meredith Winn (Sciences Po, CEE)"),
                ", and ",
                html.Strong("Dimitrios-Rafail Tservenis"),
                ", along with support from several Short-Term Scientific Mission (STSM) participants funded by COST Action CA16111."
            ], style={"marginBottom": "24px", "lineHeight": "1.6"}),
            
             html.P([
    html.Strong("Note: "),
    "The Data Playground for this survey is currently a work in progress. "
    "The post-harmonization documentation workflow was completed in December 2025. "
    "Additional features and full integration are being developed."
], style={"marginBottom": "24px", "fontStyle": "italic", "color": "#856404", "backgroundColor": "#fff3cd", "padding": "12px", "borderRadius": "4px", "border": "1px solid #ffeeba"}),


            dbc.Button(
                "Access Civic & Political Integration Post-Harmonised Local-Level Data",
                href="/playground?survey=civicpol", 
                color="success", 
                size="lg",
                style={"marginBottom": "16px"}
            ),
        ], style={"marginBottom": "32px", "padding": "24px", "backgroundColor": "#ffffff", "border": "1px solid #dee2e6", "borderRadius": "8px"}),
        
        # === BOTTOM BUTTONS (EXAMPLES REMOVED, READY-MADE GRAPHS GOES TO /readymade) ===
        html.Hr(style={"marginTop": "32px", "marginBottom": "32px"}),
        html.Div([
            dbc.Button(
                "Open the Data Playground", 
                href="/playground", 
                color="primary", 
                size="lg",
                className="me-3"
            ),
            dbc.Button(
                "View Ready-Made Graphs", 
                href="/readymade", 
                color="info", 
                size="lg"
            ),
        ], style={"textAlign": "center"}),
    ]
    
    return dbc.Container(
        dbc.Row([dbc.Col(content, md=10, lg=9, xl=8)]), 
        fluid=True,
        style={"paddingTop": "20px", "paddingBottom": "40px"}
    )

def examples_layout_deprecated() -> dbc.Container:
    """Deprecated stub kept only for reference. Not used — real implementation is defined above."""
    return dbc.Container()

# ▶ Theme options callback moved to theme_from_survey below (avoid duplicate outputs)

@app.callback(Output("var_label", "children"), Input("survey","value"), Input("var", "value"))
def _upd_var_label(survey, var):
    if not var:
        return ""
    labels = _labels_for_survey(survey)
    lbl = labels.get(str(var).strip().lower(), "").strip()
    if not lbl:
        lbl = str(var).upper()
    return f"Variable: {lbl}"

@app.callback(
    Output("subtheme-pill-box","children"),
    [Input({"role":"theme","name":ALL},"n_clicks")],
    [State({"role":"theme","name":ALL},"id")]
)
def show_subthemes(clicks, ids):
    if not clicks or not ids: return []
    last = None
    for c, i in zip(clicks, ids):
        if c and (last is None or c > last[0]):
            last = (c, i["name"])
    if not last: return []
    theme = last[1]
    subs = (var_meta.query("theme == @theme")["subtheme"]
            .dropna().astype(str).str.strip().replace({"": None}).dropna().unique().tolist())
    subs = sorted(subs)
    if not subs:
        return html.Div([
            dbc.Alert("No subthemes for this theme. Open the dashboard with this theme.", color="info"),
            dbc.Button(f"Open {theme}", color="primary", href=f"/playground?theme={theme}")
        ])
    return [
        dbc.Button(
            s, outline=False, color="primary", className="me-2 mb-2",
            href=f"/playground?theme={theme}&subtheme={s}"
        ) for s in subs
    ]


@app.callback(
    Output("theme","value"),
    Output("req_subtheme","data"),
    Input("url","href"),
    State("theme","options"),
    prevent_initial_call=True
)
def sync_theme_from_url(href, theme_opts):
    if not href: return no_update, no_update
    qs = _qs_dict(href)
    t = qs.get("theme", [None])[0]
    s = qs.get("subtheme", [None])[0]
    valid_themes = {o["value"] for o in (theme_opts or [])}
    if t not in valid_themes:
        t = (sorted(valid_themes)[0] if valid_themes else None)
    return t, s


# ==========================
# Canonical subtheme dropdown owner (prevents duplicate callback outputs)
# ==========================
# Theme dropdown - populate options based on selected survey
# ==========================
# ==========================
# Theme dropdown - populate options based on selected survey
# ==========================
@app.callback(
    Output("theme", "options"),
    Output("theme", "value", allow_duplicate=True),
    Output("subtheme", "value", allow_duplicate=True),  # RESET subtheme
    Output("var", "value", allow_duplicate=True),       # RESET variable
    Input("survey", "value"),
    prevent_initial_call='initial_duplicate',
)
def theme_from_survey(survey):
    """Populate theme dropdown based on selected survey."""
    print(f"[CALLBACK] theme_from_survey called with survey={survey}")  # ADD THIS
    try:
        ad = get_adapter(survey)
        print(f"[CALLBACK] got adapter: {ad}")  # ADD THIS
    except Exception as e:
        print(f"[CALLBACK] get_adapter failed: {e}")  # ADD THIS
        ad = None

    if ad is not None:
        opts = ad.theme_options()
        print(f"[CALLBACK] theme_options returned {len(opts)} options: {opts[:3]}")  # ADD THIS
    else:
        # Fallback: LOCALMULTIDEM var_meta
        themes = sorted([t for t in var_meta["theme"].dropna().unique().tolist() if str(t).strip()])
        opts = [{"label": sentence_case(t), "value": t} for t in themes]
        print(f"[CALLBACK] fallback themes: {len(opts)}")  # ADD THIS

    print(f"[CALLBACK] returning: {len(opts)} options, first value: {opts[0]['value'] if opts else None}")  # ADD THIS
    return opts, (opts[0]["value"] if opts else None), None, None  # Reset subtheme and var
# ==========================
# ==========================
# Subtheme dropdown - populate options based on survey and theme
# ==========================
@app.callback(
    Output("subtheme", "options"),
    Output("subtheme", "value"),
    Input("survey", "value"),
    Input("theme", "value"),
    State("req_subtheme", "data"),
    prevent_initial_call=False,
)
def subtheme_from_theme(survey, theme, req_sub):
    """Single source of truth for subtheme dropdown (options + value)."""
    # Adapter path (preferred)
    try:
        ad = get_adapter(survey)
    except Exception:
        ad = None

    if ad is not None:
        opts = ad.subtheme_options(theme)
    else:
        # Fallback: LOCALMULTIDEM var_meta
        subdf = var_meta[(var_meta["theme"] == theme)]
        subs = sorted([s for s in subdf["subtheme"].dropna().unique().tolist() if str(s).strip()])
        opts = [{"label": sentence_case(s), "value": s} for s in subs]

    # Respect a requested subtheme from URL if it exists and is valid
    valid = {o["value"] for o in (opts or [])}
    if req_sub and req_sub in valid:
        return opts, req_sub

    return opts, (opts[0]["value"] if opts else None)


# ==========================
# Variable dropdown - populate options based on theme and subtheme
# ==========================
@app.callback(
    Output("var", "options"),
    Output("var", "value"),
    Input("survey", "value"),
    Input("theme", "value"),
    Input("subtheme", "value"),
    prevent_initial_call=False,
)
def variable_from_theme_subtheme(survey, theme, subtheme):
    """Populate variable dropdown based on selected survey, theme, and subtheme."""
    print(f"[CALLBACK] variable_from_theme_subtheme: survey={survey}, theme={theme}, subtheme={subtheme}")  # ADD THIS
    try:
        ad = get_adapter(survey)
    except Exception:
        ad = None

    if ad is not None:
        opts = ad.variable_options(theme, subtheme)
        print(f"[CALLBACK] variable_options returned {len(opts)} options")  # ADD THIS
    else:
        # ... rest of code
        # Fallback: LOCALMULTIDEM var_meta
        df = var_meta.copy()
        t = str(theme or "").strip()
        st = str(subtheme or "").strip()
        if t:
            df = df[df["theme"].astype(str).str.strip() == t]
        if st:
            df = df[df["subtheme"].astype(str).str.strip() == st]
        
        vars_list = df["variable"].astype(str).str.strip().str.lower().drop_duplicates().tolist()
        opts = []
        for v in vars_list:
            if not v:
                continue
            lab = dict_labels.get(v, "").strip()
            txt = f"{v} — {lab}" if lab else v
            opts.append({"label": txt, "value": v})

    return opts, (opts[0]["value"] if opts else None)
@app.callback(
    Output("city_fil", "options"),
    Output("group_fil", "options"),
    Input("survey", "value"),
    Input("var", "value"),
    State("city_fil", "options"),
    State("group_fil", "options"),
)
def upd_filter_opts(survey, var, city_opts_current, group_opts_current):
    """Populate City and Group dropdowns based on the selected survey + variable.

    Keeps existing options during transient UI states (e.g., when var resets to None).
    """
    # Keep existing options if the variable is temporarily None during dropdown repopulation
    if not var:
        if city_opts_current or group_opts_current:
            return no_update
        return [], []

    # Prefer adapter-specific data if available
    ad = None
    try:
        ad = get_adapter(survey)
    except Exception:
        ad = None

    df = None
    if ad is not None and hasattr(ad, "raw"):
        df = ad.raw
    else:
        df = raw

    v = str(var).strip().lower()
    if df is None or getattr(df, "empty", False) or (v not in df.columns):
        if city_opts_current or group_opts_current:
            return no_update
        return [], []

    sub = df[df[v].notna()].copy()
    if sub.empty:
        if city_opts_current or group_opts_current:
            return no_update
        return [], []

    # Survey-specific dimension names
    if _norm_survey(survey) == "civicpol":
        city_col = "city_full" if "city_full" in sub.columns else None
        group_col = "group_disp" if "group_disp" in sub.columns else ("rgroup" if "rgroup" in sub.columns else None)

        cities = sorted(sub[city_col].dropna().astype(str).unique()) if city_col else []
        groups_vals = sorted(sub[group_col].dropna().astype(str).unique()) if group_col else []

        city_opts = [{"label": c, "value": c} for c in cities]
        # Hide native/autochthonous group names from dropdown; show single "Autochthonous" entry
        has_auto = "Autochthonous" in groups_vals
        non_auto_groups = [g for g in groups_vals
                           if g != "Autochthonous" and g not in CIVIC_NATIVE_GROUP_NAMES]
        if not has_auto:
            has_auto = any(g in CIVIC_NATIVE_GROUP_NAMES for g in groups_vals)
        group_opts = [{"label": g, "value": g} for g in non_auto_groups]
        if has_auto:
            group_opts.append({"label": AUTOCH_LABEL, "value": AUTOCH_KEY})
        return city_opts, group_opts

    # LOCALMULTIDEM (existing behaviour)
    if "city_full" not in sub.columns and "city" in sub.columns:
        sub["city_full"] = sub["city"].map(to_city_full)
    cities = sorted(sub["city_full"].dropna().astype(str).unique())

    gnum = pd.to_numeric(sub.get("group"), errors="coerce")
    gnum = gnum[gnum.notna()]
    groups_codes = sorted([g for g in gnum.astype(int).unique().tolist() if g != -9])

    # Collect all native group names that should be hidden from dropdown
    _native_group_names = set()
    for _city_natives in NATIVE_BY_CITY.values():
        _native_group_names.update(n.strip() for n in _city_natives)

    # Build group options, excluding native group names (they become "Autochthonous")
    group_opts = []
    has_auto = False
    for g in groups_codes:
        gname = GROUP_NAMES.get(int(g), f"Group {g}")
        if gname.strip() in _native_group_names:
            has_auto = True  # At least one native group exists → show Autochthonous
        else:
            group_opts.append({"label": gname, "value": int(g)})

    # Also check if qtype=2 respondents exist
    try:
        if not has_auto:
            has_auto = pd.to_numeric(sub.get("qtype"), errors="coerce").eq(2).any()
    except Exception:
        pass

    if has_auto:
        group_opts.append({"label": AUTOCH_LABEL, "value": AUTOCH_KEY})

    return ([{"label": c, "value": c} for c in cities], group_opts)
@app.callback(Output("box3","style"), Input("born_here","value"))
def _toggle_box3(born):
    return ({ "display":"block" } if born == "ABROAD" else { "display":"none" })

# Hide immigration filters section for CivicPol survey
@app.callback(Output("immigration-filters-section", "style"), Input("survey", "value"))
def _toggle_immigration_filters(survey):
    if _norm_survey(survey) == "civicpol":
        return {"display": "none"}
    return {"display": "block"}

@app.callback(
    Output("more_filters_collapse","is_open"),
    Output("more_filters_btn", "style"),
    Output("less_filters_btn", "style"),
    Input("more_filters_btn","n_clicks"),
    Input("less_filters_btn","n_clicks"),
    State("more_filters_collapse","is_open"),
    prevent_initial_call=True
)
def toggle_filters(more_clicks, less_clicks, is_open):
    triggered = ctx.triggered_id
    if triggered in ("more_filters_btn", "less_filters_btn"):
        new_open = not is_open
        if new_open:
            # Filters are now open: hide "More", show "Less"
            return new_open, {"display": "none"}, {"display": "inline-block"}
        else:
            # Filters are now closed: show "More", hide "Less"
            return new_open, {"display": "inline-block"}, {"display": "none"}
    return is_open, {"display": "inline-block" if not is_open else "none"}, {"display": "none" if not is_open else "inline-block"}
@app.callback(
    Output("city_fil", "value"),
    Output("group_fil", "value"),
    Output("gender_fil", "value"),
    Output("born_here", "value"),
    Output("yob_rng", "value"),
    Output("yoa_rng", "value"),
    Output("yc_rng", "value"),
    Output("yc_life", "value"),
    Output("reason_fil", "value"),
    Output("alone_radio", "value"),
    Output("legal_fil", "value"),
    Output("autoch", "value"),
    Output("axis", "value"),
    Output("orient", "value"),
    Output("sort", "value"),
    Output("comp_aids", "value"),
    Input("reset_filters_btn", "n_clicks"),
    prevent_initial_call=True
)
def reset_all_filters(n_clicks):
    """Reset all filters to their default values."""
    if n_clicks:
        return (
            [],                                          # city_fil - empty (all cities)
            [],                                          # group_fil - empty (all groups)
            list(ALL_GENDERS),                           # gender_fil - all genders
            "ANY",                                       # born_here - no filter
            [BY_MIN, BY_MAX],                            # yob_rng - full range
            [int(YA_MIN), int(YA_MAX)],                  # yoa_rng - full range
            [int(YC_MIN), int(min(YC_MAX, Q6_MAX_HARD))], # yc_rng - full range
            [],                                          # yc_life - unchecked
            [],                                          # reason_fil - no filter
            "ANY",                                       # alone_radio - no filter
            [],                                          # legal_fil - no filter
            True,                                        # autoch - include autochthonous
            "city",                                      # axis - city x group
            "h",                                         # orient - horizontal
            "desc",                                      # sort - high to low
            ["sep"],                                     # comp_aids - separators on
        )
    return no_update


# DISABLED: duplicate outputs for subtheme (owned by subtheme_from_theme)
#@app.callback(
#    Output("subtheme","value"),
#    Input("url","href"),
#    State("subtheme","options"),
#    prevent_initial_call=True
#)
#def sync_subtheme_from_url(href, subtheme_opts):
#    if not href: return no_update
#    qs = _qs_dict(href)
#    s = qs.get("subtheme", [None])[0]
#    valid_subthemes = {o["value"] for o in (subtheme_opts or [])}
#    if s not in valid_subthemes:
#        s = (sorted(valid_subthemes)[0] if valid_subthemes else None)
#    return s


@app.callback(
    Output("display_mode_card", "style"),        # hide/show the whole card
    Output("vtype_store", "data"),               # store the resolved type
    Output("vmode_store", "data"),               # store the current mode ('yes' or 'stack')
    Input("var", "value"),
)
def update_display_mode_ui(var):
    """
    Show the 'Display mode' card ONLY for binary variables (types 1/2).
    Default to 'yes' for these; for others, hide card and set mode to 'stack'.
    """
    v = (str(var).strip().lower() if var else "")
    vtype = int(var_type_map.get(v, -1)) if v in var_type_map else -1
    is_binary = vtype in (1, 2)

    if not is_binary:
        # Hide the whole card for non-binary variables
        return {"display": "none"}, vtype, "stack"

    # Binary variables: show the card
    return {}, vtype, "stack"
@app.callback(
    Output("vmode_store", "data", allow_duplicate=True),
    Input("display_mode", "value"),
    prevent_initial_call=True
)
def _sync_vmode_from_radio(mode_value):
    return mode_value

def _pg_question_and_footnote(var: str, df_slice: pd.DataFrame) -> tuple:
    qrows = _find_questions_for_var(var)
    if qrows:
        qtbl = dbc.Table(
            [
                html.Thead(html.Tr([html.Th("ID (A)"), html.Th("Question (B)")])),
                html.Tbody([html.Tr([html.Td(k), html.Td(v)]) for k, v in qrows]),
            ],
            bordered=True, hover=False, responsive=True, striped=False, size="sm",
            className="mt-2",
        )
    else:
        label = dict_labels.get(str(var).strip().lower(), str(var).upper())
        qtbl = html.Div([
            html.Strong("Question wording"),
            html.Div(label, className="text-muted")
        ])

    try:
        specials = _count_special_codes(df_slice, var)
        miss_lbl = nonresponse_counts_labeled(df_slice, var)
        miss = miss_lbl.get("Missing/blank", 0)
        parts = [f"{k}: {v}" for k, v in specials.items() if v > 0]
        if miss > 0:
            parts.append(f"Missing/blank: {miss}")
        ftxt = " · ".join(parts) if parts else "No special codes / missing values in the current slice."
    except Exception:
        ftxt = "Nonresponse summary unavailable for this variable."

    fnode = html.Div([html.Strong("Notes"), html.Span(" — "), html.Span(ftxt)], className="text-muted")
    return qtbl, fnode


#  SINGLE callback


_PG_LAST_TABLE = {"df": pd.DataFrame(), "var": ""}  # Store both data and variable name

@app.callback(
    Output("graph", "figure"),
    Output("question_table", "children"),
    Output("footnote", "children"),
    Output("pg-data-table", "columns"),
    Output("pg-data-table", "data"),
    Input("survey", "value"),  # ADDED: survey selector
    Input("var", "value"),
    Input("axis", "value"),
    Input("city_fil", "value"),
    Input("group_fil", "value"),
    Input("gender_fil", "value"),
    Input("sort", "value"),
    Input("display_mode", "value"),
    Input("orient", "value"),
    Input("comp_aids", "value"),
    Input("autoch", "value"),
    Input("born_here", "value"),
    Input("yob_rng", "value"),
    Input("yoa_rng", "value"),
    Input("yc_rng", "value"),
    Input("yc_life", "value"),
    Input("reason_fil", "value"),
    Input("alone_radio", "value"),
    Input("legal_fil", "value"),
    prevent_initial_call=False
)
def _pg_update_all(survey, var, axis, cities, groups, genders, sort_ord, display_mode, orient, comp_aids, show_autoch,
                   born_here, yob_rng, yoa_rng, yc_rng, yc_life, reason_vals, alone_sel, legal_vals):

    orient = orient if orient in {"v", "h"} else "h"  # default horizontal
    sep = ("sep" in set(comp_aids or []))
    include_autoch = bool(show_autoch)
    sort_asc = (str(sort_ord).lower() == "asc")

    # =========================================================================
    # ROUTE TO CIVICPOL ADAPTER
    # =========================================================================
    if _norm_survey(survey) == "civicpol":
        ad = SURVEYS_REGISTRY.get("civicpol")
        if ad is None:
            empty_fig = px.bar(title="Civic survey adapter not available")
            cols, data = _pg_table_payload(pd.DataFrame())
            return empty_fig, [], "", cols, data

        # Call CivicPolAdapter.draw()
        # Note: axis parameter controls city/group switching
        # No exclusion when no filters are active; exclusion only with filters
        _civic_any_filter = (
            _range_is_active(yob_rng, BY_MIN, BY_MAX)
            or (genders and genders not in ([], [None]) and set(genders) != set(ALL_GENDERS))
            or (born_here and born_here not in ("ANY", None, ""))
        )
        result = ad.draw(
            var=var,
            axis=axis or "city",  # "city" or "group" for switching
            orient=orient,
            sort_order="asc" if sort_asc else "desc",
            sep=sep,
            cities_full=cities,
            groups=groups,
            gender_vals=genders,  # Gender filter using rgender
            birth_year_rng=yob_rng,  # Birth year filter using ryrbrn
            title_font_size=TITLE_FONT_SIZE,
            include_autoch=include_autoch,
            skip_exclusion=not _civic_any_filter,
        )

        fig = result.get("fig")
        if fig is None:
            fig = px.bar(title="No data for this variable")

        footer_text = result.get("footer_text", "")
        description_text = result.get("description_text", "")
        table_df = result.get("table_df", pd.DataFrame())

        # Build question table and footnote
        qtbl = []
        if description_text:
            qtbl = [html.P(description_text, style={"fontStyle": "italic", "color": "#555"})]

        # Footer: gray text for response labels / routing, then red exclusion line
        fnode = ""
        if footer_text:
            fnode = html.Pre(footer_text, style={"fontSize": "0.85rem", "color": "#666", "whiteSpace": "pre-wrap", "margin": "10px 0 0 0"})
        # Append red exclusion message from adapter (uses shared helper)
        _civic_excluded = result.get("excluded_units_info", [])
        fnode = _append_excl_to_footnote(fnode, _civic_excluded)

        # Store for download
        _PG_LAST_TABLE["df"] = table_df
        _PG_LAST_TABLE["var"] = str(var or "data").strip()

        cols, data = _pg_table_payload(table_df, var=str(var or ""))
        return fig, qtbl, fnode, cols, data

    # =========================================================================
    # LOCALMULTIDEM (original logic)
    # =========================================================================
    sub = raw.copy()
    
    # Ensure city_full column exists
    if "city_full" not in sub.columns and "city" in sub.columns:
        sub["city_full"] = sub["city"].map(to_city_full)

    # Apply city filter
    if cities:
        want_c = {to_city_full(c) for c in cities}
        sub = sub[sub["city_full"].isin(want_c)]

    # Apply group filter
    if groups:
        want_auto = AUTOCH_KEY in set(groups)
        num_groups = [g for g in groups if g != AUTOCH_KEY]

        # Build mask: rows matching selected numeric groups OR autochthonous rows
        mask = pd.Series(False, index=sub.index)
        if num_groups:
            mask = mask | sub["group"].isin(num_groups)
        if want_auto:
            # qtype == 2 → autochthonous respondent
            if "qtype" in sub.columns:
                mask = mask | pd.to_numeric(sub["qtype"], errors="coerce").eq(2)
            # native city-group pair → autochthonous
            if "city_full" in sub.columns and "group" in sub.columns:
                _cf = sub["city_full"].astype(str)
                _gn = sub["group"].map(lambda g: GROUP_NAMES.get(int(g) if pd.notna(g) else g, f"Group {g}"))
                _native_mask = pd.Series(
                    [_is_native_pair(c, g) for c, g in zip(_cf, _gn)],
                    index=sub.index,
                )
                mask = mask | _native_mask
        sub = sub[mask]

    # Apply all demographic/migration filters using the apply_filters function
    sub = apply_filters(
        df=sub,
        yob_rng=yob_rng,
        yoa_rng=yoa_rng,
        yc_rng=yc_rng,
        yc_life=yc_life or [],
        reason_vals=reason_vals or [],
        alone_sel=alone_sel or "ANY",
        legal_vals=legal_vals or [],
        genders=genders or list(ALL_GENDERS),
        born_here_sel=born_here or "ANY",
    )

    # Ensure group_disp column exists
    if "group_disp" not in sub.columns:
        sub = sub.assign(group_disp=_group_disp_series(sub))
    
    # Apply autochthonous filter
    if not include_autoch:
        sub = sub[sub["group_disp"] != "Autochthonous"]

    if not var or var not in sub.columns or sub.empty:
        empty_fig = px.bar(title="No data")
        cols, data = _pg_table_payload(pd.DataFrame())
        qtbl, fnode = _pg_question_and_footnote(var or "", sub)
        return empty_fig, qtbl, fnode, cols, data

    # --- Min-25 threshold ---
    # --- Min-25 threshold ---
    # No filters → NO exclusion (show all data as-is).
    # Filters active → recompute exclusion on filtered data.
    _primary_k = "city_full" if str(axis or "city").lower() != "group" else "group_disp"
    _secondary_k = "group_disp" if _primary_k == "city_full" else "city_full"
    _excluded_units_info = []
    _any_filter = (
        _range_is_active(yob_rng, BY_MIN, BY_MAX)
        or _range_is_active(yoa_rng, YA_MIN, YA_MAX)
        or _range_is_active(yc_rng, YC_MIN, min(YC_MAX, Q6_MAX_HARD))
        or (yc_life and yc_life not in ([], [None]))
        or (reason_vals and reason_vals not in ([], [None]))
        or (alone_sel and alone_sel not in ("ANY", None, ""))
        or (legal_vals and legal_vals not in ([], [None]))
        or (born_here and born_here not in ("ANY", None, ""))
    )
    if _any_filter:
        sub, _excluded_units_info = _compute_exclusion_info(sub, var, _primary_k, _secondary_k)

    if sub.empty:
        empty_fig = px.bar(title=f"All combinations have fewer than {MIN_NONROUTING_N} responses")
        cols, data = _pg_table_payload(pd.DataFrame())
        qtbl, fnode = _pg_question_and_footnote(var or "", sub)
        return empty_fig, qtbl, fnode, cols, data

    sort_asc = (str(sort_ord).lower() == "asc")

    scale_vars = {"q1901", "q1902", "q1903", "q33", "q1308", "q1311", "q3709"}
    v_norm = str(var or "").strip().lower()
    if v_norm in scale_vars:
        fig, tbl = build_scale_density(
            df=sub,
            var=v_norm,
            city_codes=None,
            groups=None,
            genders=genders or ("Male", "Female", "Other"),
            smooth=True,
        )

        cols, data = _pg_table_payload(tbl, var=str(var or v_norm))
        qtbl, fnode = _pg_question_and_footnote(var or v_norm, sub)

        fnode = _append_excl_to_footnote(fnode, _excluded_units_info)

        try:
            _PG_LAST_TABLE["df"] = tbl.copy()
            _PG_LAST_TABLE["var"] = str(var or "data").strip()
        except Exception:
            _PG_LAST_TABLE["df"] = tbl
            _PG_LAST_TABLE["var"] = str(var or "data").strip()
# Return early for scale variables
        return fig, qtbl, fnode, cols, data
    
    if _is_numeric_var(var) or _is_numeric_scale_from_labels(var):
        # IMPORTANT: numeric charts must respect the SAME active filters as bar charts
        primary_key = "city_full" if (axis or "city") == "city" else "group_disp"
        secondary_key = "group_disp" if (axis or "city") == "city" else "city_full"

        # Use the already-filtered respondent slice `sub` (NOT the precomputed MEDIANS_DF)
        fig, tbl = build_mean_chart(
            df=sub,
            var=var,
            primary_key=primary_key,
            secondary_key=secondary_key,
            orient=orient,
            sep=sep,
            sort_asc=sort_asc,
        )

        fig.update_layout(
            modebar=dict(
                remove=[
                    "toImage","autoScale2d","zoom2d","pan2d","select2d",
                    "lasso2d","zoomIn2d","zoomOut2d","resetScale2d"
                ]
            )
        )

    elif _is_binary_var(var) and (display_mode or "stack") == "yes":
        x_key = "city_full"
        by = [x_key, "group_disp"]
        tbl = yes_share_for_var(sub, var, by).sort_values(by + ["value"], ascending=sort_asc).reset_index(drop=True)

        if "n" in tbl.columns:
            keep_cities = tbl.groupby(x_key)["n"].sum()
            keep_cities = keep_cities[keep_cities > 0].index.tolist()
            tbl = tbl[tbl[x_key].isin(keep_cities)].copy()

        fig = build_yes(
            df=sub, var=var, colour_key="group_disp",
            x_key=x_key, orient=orient,
            city_codes=None, groups=None, genders=("Male","Female","Other"),
            asc=sort_asc, show_auto=include_autoch, sep=sep
        )

    else:
        x_key = "group_disp" if str(axis).lower() == "group" else "city_full"
        g, resp_order = multi_share_generic(sub, var, by=["city_full", "group_disp"])
        # Robust sort: older code expected a 'value' column, but our grouped tables use
        # 'pct' (and sometimes 'n'). Choose the best available sort column.
        sort_col = None
        if isinstance(g, pd.DataFrame):
            if "value" in g.columns:
                sort_col = "value"
            elif "pct" in g.columns:
                sort_col = "pct"
            elif "n" in g.columns:
                sort_col = "n"

        if sort_col and x_key in g.columns:
            g = g.sort_values([x_key, sort_col], ascending=[True, sort_asc], kind="mergesort").reset_index(drop=True)
        tbl = g.copy()

        fig = build_stack(
            df=sub,
            var=var,
            x_key=x_key,
            orient=orient,
            city_codes=None,
            groups=None,
            genders=("Male", "Female", "Other"),
            show_auto=include_autoch,
            sep=sep,
            asc=sort_asc,
        )

    lbl = dict_labels.get(str(var).strip().lower(), "") or str(var).upper()
    fig.update_layout(title={"text": lbl, "x": 0.5, "xanchor": "center"},
                      title_font_size=TITLE_FONT_SIZE)

    qtbl, fnode = _pg_question_and_footnote(var, sub)

    fnode = _append_excl_to_footnote(fnode, _excluded_units_info)

    # 4) Data preview under the graph
    _PG_LAST_TABLE["df"] = tbl
    _PG_LAST_TABLE["var"] = str(var or "data").strip()
    cols, data = _pg_table_payload(tbl, var=str(var or ""))
    return fig, qtbl, fnode, cols, data
_pg_download_callback_register(lambda: _PG_LAST_TABLE)


def _filter_medians(var: str, city_codes, groups, genders, show_auto: bool) -> pd.DataFrame:
 
    if MEDIANS_DF is None or MEDIANS_DF.empty:
        return pd.DataFrame(columns=["variable","city_full","group_disp","gender","median","n"])

    v = str(var or "").strip().lower()
    sub = MEDIANS_DF[MEDIANS_DF["variable"] == v].copy()
    if sub.empty:
        return sub
    if city_codes:
        sub = sub[sub["city_full"].isin(city_codes)]
    want_auto = (groups is not None) and (AUTOCH_KEY in set(groups))
    numeric_groups = [g for g in (groups or []) if g != AUTOCH_KEY]
    selected_names = [GROUP_NAMES.get(int(g), f"Group {g}") for g in numeric_groups]
    mask_groups = sub["group_disp"].isin(selected_names) if numeric_groups else False
    mask_auto   = (sub["group_disp"] == AUTOCH_LABEL) if want_auto else False
    if groups:
        sub = sub[mask_groups | mask_auto]
    if not show_auto:
        sub = sub[sub["group_disp"] != AUTOCH_LABEL]
    has_all = (sub["gender"] == "ALL").any()
    if has_all:
        sub = sub[sub["gender"] == "ALL"]
    else:
        if genders:
            sub = sub[sub["gender"].isin(genders)]

    return sub


def build_median_chart(var: str, primary_key: str, secondary_key: str, orient: str,
                       city_codes, groups, genders, show_auto: bool, sep: bool, sort_asc: bool):
    sub = _filter_medians(var, city_codes, groups, genders, show_auto)
    if sub.empty:
        return px.bar(title="No median data in the precomputed CSV")

    sub = sub.copy()
    sub["group_disp"] = sub["group_disp"].replace({"autochthonous": AUTOCH_LABEL})
    primary   = "group_disp" if primary_key   == "group_name" else primary_key
    secondary = "group_disp" if secondary_key == "group_name" else secondary_key
    for k in (primary, secondary):
        if k not in sub.columns:
            if k == "gender":
                sub["gender"] = "ALL"
            else:
                pass
    keys = [k for k in [primary, secondary] if k]
    if primary == secondary:
        keys = [primary]
    g = sub[keys + ["median","n"]].copy()

    if len(keys) == 2:
        base = (g.groupby([primary, secondary], dropna=False)["median"]
                  .mean().reset_index().rename(columns={"median": "_sortval"}))
        g = g.merge(base, on=[primary, secondary], how="left")
    else:
        base = (g.groupby([primary], dropna=False)["median"]
                  .mean().reset_index().rename(columns={"median": "_sortval"}))
        g = g.merge(base, on=[primary], how="left")
    primaries = sorted(g[primary].dropna().unique().tolist(), key=lambda x: str(x))
    order_pairs, band_ranges = [], []
    cursor = 0
    for p in primaries:
        if len(keys) == 2:
            part = g[g[primary] == p][[secondary, "_sortval"]].drop_duplicates()
        else:
            part = g[g[primary] == p][[primary, "_sortval"]].drop_duplicates().rename(columns={primary: secondary})
        part = part.sort_values("_sortval", ascending=sort_asc, kind="mergesort")
        secs = part[secondary].tolist()
        start = cursor + 1
        for s in secs:
            cursor += 1
            order_pairs.append((p, s, cursor))
        band_ranges.append((start, cursor, p))

    seq = pd.DataFrame(order_pairs, columns=[primary, secondary, "xc"])
    seq["xlabel"] = seq[primary].astype(str) + ("" if len(keys)==1 else " ▸ " + seq[secondary].astype(str))

    tbl = sub.merge(seq, on=[c for c in [primary, secondary] if c in seq.columns], how="left")
    tbl = tbl.sort_values(["xc"]).copy()
    colour_key = secondary if len(keys) == 2 else primary
    pal = palette(colour_key)
    color_map = pal if isinstance(pal, dict) else None
    fig = px.bar(
        tbl,
        x="xc" if orient == "v" else "median",
        y="median" if orient == "v" else "xc",
        color=colour_key if colour_key in tbl.columns else None,
        orientation="h" if orient == "h" else "v",
        barmode="group",
        **({"color_discrete_map": color_map} if color_map else ({"color_discrete_sequence": pal} if pal else {})),
        hover_data={col: False for col in tbl.columns}
    )
    fig.update_traces(
        marker_line_width=0.8,
        marker_line_color="rgba(0,0,0,.55)",
        customdata=np.stack([
            tbl.get("n", pd.Series([np.nan]*len(tbl))).to_numpy(),
            (tbl[primary].astype(str) if primary in tbl.columns else pd.Series([""]*len(tbl))).to_numpy(),
            (tbl[secondary].astype(str) if secondary in tbl.columns else pd.Series([""]*len(tbl))).to_numpy()
        ], axis=1),
        text=(
            (tbl[secondary].astype(str) if secondary in tbl.columns 
             else pd.Series([""] * len(tbl)))
        ).to_list(),
        texttemplate="%{text}",
        textposition="outside",
        hovertemplate=(
            ("Primary: %{customdata[1]}" if primary in tbl.columns else "")
            + ( "<br>Secondary: %{customdata[2]}" if (secondary in tbl.columns and primary!=secondary) else "" )
            + "<br>Median: %{y:.2f}" if orient=="v" else "<br>Median: %{x:.2f}"
            + "<br>N: %{customdata[0]:.0f}<extra></extra>"
        )
    )
    if orient == "v":
        ticks = seq[["xc","xlabel"]]
        fig.update_xaxes(tickmode="array", tickvals=ticks["xc"], ticktext=ticks["xlabel"], tickangle=-30)
        fig.update_yaxes(title_text="Median")
    else:
        ticks = seq[["xc","xlabel"]]
        fig.update_yaxes(tickmode="array", tickvals=ticks["xc"], ticktext=ticks["xlabel"])
        fig.update_xaxes(title_text="Median")
    if sep and len(band_ranges):
        for i, (start, _, _) in enumerate(band_ranges):
            if i > 0:
                pos = start - 0.5
                (fig.add_vline if orient == "v" else fig.add_hline)(
                    **({"x": pos} if orient == "v" else {"y": pos}),
                    line_color="rgba(0,0,0,.32)", line_width=1
                )
        for i, (start, end, _) in enumerate(band_ranges):
            if start > end:
                continue
            if orient == "v":
                fig.add_vrect(x0=start-0.5, x1=end+0.5,
                              fillcolor="rgba(0,0,0,0.035)" if i%2==0 else "rgba(0,0,0,0.06)",
                              line_width=0, layer="below")
            else:
                fig.add_hrect(y0=start-0.5, y1=end+0.5,
                              fillcolor="rgba(0,0,0,0.035)" if i%2==0 else "rgba(0,0,0,0.06)",
                              line_width=0, layer="below")

    # ---- Add spectrum endpoint labels for 0-10 scale variables on median axis ----
    v_norm = str(var or "").strip().lower()
    left_margin = 50
    bottom_margin = 60
    if v_norm in SPECTRUM_LABELS:
        low_label, high_label = SPECTRUM_LABELS[v_norm]
        if orient == "v":
            # For vertical bars, median is on y-axis
            fig.update_yaxes(
                tickmode="array",
                tickvals=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                ticktext=[f"0 - {low_label}", "1", "2", "3", "4", "5", "6", "7", "8", "9", f"10 - {high_label}"],
                title_text=None,
            )
            left_margin = 180
        else:
            # For horizontal bars, median is on x-axis
            fig.update_xaxes(
                tickmode="array",
                tickvals=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                ticktext=[f"0 - {low_label}", "1", "2", "3", "4", "5", "6", "7", "8", "9", f"10 - {high_label}"],
                title_text=None,
            )
            bottom_margin = 120

    fig.update_layout(
        bargap=0.12,
        bargroupgap=0.08,
        legend_title_text=(colour_key.replace("_"," ").capitalize() if colour_key in tbl.columns else ""),
        transition_duration=250,
        title_font_size=TITLE_FONT_SIZE,
        margin=dict(l=left_margin, r=10, t=70, b=bottom_margin),
    )
    return fig

def build_chart(var: str, vtype: int, mode: str,
                axis: str, orient: str, sort_dir: str, sep: bool,
                city_codes, groups, genders, show_auto: bool):
    primary_key   = "group_name" if axis == "group" else "city_full"
    secondary_key = "city_full"  if axis == "group" else "group_name"
    sort_asc = (sort_dir == "asc")

    if vtype == 4 or _is_numeric_var(var):
        return build_median_chart(
            var=var,
            primary_key=primary_key,
            secondary_key=secondary_key,
            orient=orient,
            city_codes=city_codes,
            groups=groups,
            genders=genders,
            show_auto=show_auto,
            sep=("sep" in (sep or [])) if isinstance(sep, list) else bool(sep),
            sort_asc=sort_asc
        )
    if mode == "yes" and vtype in (1,2) and _is_binary_var(var):
        return build_yes(
            raw, var,
            colour_key=secondary_key,
            x_key=primary_key,
            orient=orient,
            city_codes=city_codes,
            groups=groups,
            genders=genders,
            asc=sort_asc,
            show_auto=show_auto,
            sep=("sep" in (sep or [])) if isinstance(sep, list) else bool(sep),
        )
    # stacked
    return build_stack(
    raw,
    var,
    x_key=("group_disp" if axis == "group" else "city_full"),
    orient=orient,
    city_codes=city_codes,
    groups=groups,
    genders=genders,
    include_autochthonous=show_auto,
    sep=(("sep" in (sep or [])) if isinstance(sep, list) else bool(sep)),
    sort_asc=sort_asc,
)
def apply_filters(
    df: pd.DataFrame,
    yob_rng,
    yoa_rng,
    yc_rng,
    yc_life,
    reason_vals,
    alone_sel,
    legal_vals,
    genders,
    born_here_sel,
):
    """
    Apply all selected filters in a consistent, sequential way.

    Behavior intentionally matches the hover logic in app_main.py:
      - no special-casing for born-here
      - no auto-keeping NA rows for migration-related filters
    """
    sub = df.copy()

    # born here / abroad
    born = _born_here_series(sub)
    if born_here_sel == "HERE":
        sub = sub[born == "HERE"]
    elif born_here_sel == "ABROAD":
        sub = sub[born == "ABROAD"]

    # year of birth — keep routing codes (negative, >=9990) and NaN
    if FVAR["birth_year"] and yob_rng:
        s = pd.to_numeric(sub[FVAR["birth_year"]], errors="coerce")
        is_routing = (s < 0) | (s >= 9990) | s.isna()
        sub = sub[((s >= yob_rng[0]) & (s <= yob_rng[1])) | is_routing]

    # years in city (Q6) — keep routing codes (negative, >=9990) and LIFE codes
    if FVAR["years_city"]:
        s_raw = sub[FVAR["years_city"]].map(_canon_code)
        s_num = pd.to_numeric(sub[FVAR["years_city"]], errors="coerce")
        lo, hi = (yc_rng or (YC_MIN, min(YC_MAX, Q6_MAX_HARD)))
        hi = min(int(hi), int(Q6_MAX_HARD))
        in_range = (s_num >= lo) & (s_num <= hi)
        is_life = s_raw.isin(YC_LIFE_CODES)
        is_routing = (s_num < 0) | (s_num >= 9990) | s_num.isna()
        mask_q6 = in_range | (("LIFE" in (yc_life or [])) & is_life) | is_routing
        sub = sub[mask_q6]

    # year of arrival — keep routing codes (-1 = not applicable, 9999, etc.)
    if FVAR["arrival_year"] and yoa_rng:
        s = pd.to_numeric(sub[FVAR["arrival_year"]], errors="coerce")
        is_routing = (s < 0) | (s >= 9990) | s.isna()
        sub = sub[((s >= yoa_rng[0]) & (s <= yoa_rng[1])) | is_routing]

    # reason for arrival
    if FVAR["reason_arr"] and reason_vals:
        codes = sub[FVAR["reason_arr"]].map(_canon_code)
        sub = sub[codes.isin(set(map(str, reason_vals)))]

    # came alone
    if FVAR["came_alone"] and alone_sel and alone_sel.upper() in {"YES", "NO"}:
        codes = sub[FVAR["came_alone"]].map(_canon_code)
        yes_code, no_code = "1", "0"
        sub = sub[codes == (yes_code if alone_sel.upper() == "YES" else no_code)]

    # legal status
    if FVAR["legal"] and legal_vals:
        codes = sub[FVAR["legal"]].map(_canon_code)
        sub = sub[codes.isin(set(map(str, legal_vals)))]

    # gender
    if genders:
        sub = sub[sub["gender"].isin(genders)]

    return sub 

def _norm_survey(survey: str | None) -> str:
    """Normalize survey name to registry key."""
    s = str(survey or "").strip().lower()
    if not s:
        return "localmulti"
    if s in {"civicpol", "civic", "civic & political integration", "civic and political integration"}:
        return "civicpol"
    return "localmulti"

def get_adapter(survey: str | None):
    """Get the appropriate survey adapter."""
    key = _norm_survey(survey)
    return SURVEYS_REGISTRY.get(key)

def init_adapters():
    """Initialize both survey adapters: LOCALMULTIDEM and Civic & Political Integration."""
    global SURVEYS_REGISTRY

    # Always start clean
    SURVEYS_REGISTRY = {}

# === CIVIC PRE-CHECK ===
    print("\n" + "="*80)
    print("CIVIC SURVEY PRE-FLIGHT CHECK")
    print("="*80)
    
    from pathlib import Path
    
    print(f"1. Checking CIVIC_CODEBOOK_PATH...")
    print(f"   Path: {CIVIC_CODEBOOK_PATH}")
    print(f"   Exists: {Path(CIVIC_CODEBOOK_PATH).exists()}")
    
    print(f"2. Checking CIVIC_CSV_PATH...")
    print(f"   Path: {CIVIC_CSV_PATH}")
    print(f"   Exists: {Path(CIVIC_CSV_PATH).exists()}")
    
    print(f"3. Checking CivicPolAdapter class...")
    try:
        print(f"   CivicPolAdapter: {CivicPolAdapter}")
        print(f"   ✓ Class available")
    except NameError as e:
        print(f"   ✗ Class NOT available: {e}")
    
    print(f"4. Checking mappings...")
    print(f"   CIVIC_CITY_MAPPING: {len(CIVIC_CITY_MAPPING)} entries")
    print(f"   CIVIC_COUNTRY_MAPPING: {len(CIVIC_COUNTRY_MAPPING)} entries")
    
    print("="*80 + "\n")
    # -----------------------
    # LOCALMULTIDEM (existing)
    # -----------------------
    local_ad = LocalMultiAdapter(
        raw=raw,
        var_meta=var_meta,
        dict_labels=dict_labels,
        var_type_map=var_type_map,
        allowed_vars=ALLOWED_VARS,
        norm_varname=_norm_varname,
        sentence_case=sentence_case,
        apply_filters=apply_filters,
        find_questions_for_var=_find_questions_for_var,
        routing_line_for_var=routing_line_for_var,
        country_line_for_var=country_line_for_var,
        nonresponse_counts_labeled=nonresponse_counts_labeled,
        count_special_codes=_count_special_codes,
        build_stack=build_stack,
        build_yes=build_yes,
        build_mean_chart=build_mean_chart,
        multi_share_generic=multi_share_generic,
        yes_share_for_var=yes_share_for_var,
        is_numeric_var=_is_numeric_var,
        is_binary_var=_is_binary_var,
        is_numeric_scale_from_labels=_is_numeric_scale_from_labels,
        TITLE_FONT_SIZE=TITLE_FONT_SIZE,
    )

    # -------------------------------------------------
    # CIVIC & POLITICAL INTEGRATION (NEW / SEPARATE DATA)
    # -------------------------------------------------
    civic_ad = None
    try:
        if raw_civic is None or raw_civic.empty:
            raise RuntimeError("raw_civic is empty (Civic .dta did not load)")

        if civic_codebook_df is None or civic_codebook_df.empty:
            raise RuntimeError("civic_codebook_df is empty (missing civic_codebook.csv)")

        civic_df = _prepare_civic_dimensions(raw_civic)

        # Provide LOCALMULTIDEM-like columns used by your plot/filter logic
        # rgender -> gender (Male/Female/Other)
        if "gender" not in civic_df.columns and "rgender" in civic_df.columns:
            g = civic_df["rgender"]
            g_num = pd.to_numeric(g, errors="coerce")
            civic_df["gender"] = np.where(
                g_num == 1, "Male",
                np.where(g_num == 2, "Female", "Other")
            )

        # ryborn -> born_here (True/False/NaN)
        if "born_here" not in civic_df.columns and "ryborn" in civic_df.columns:
            b = pd.to_numeric(civic_df["ryborn"], errors="coerce")
            civic_df["born_here"] = np.where(b == 1, True, np.where(b == 0, False, np.nan))

        civic_ad = CivicPolAdapter(
            raw=civic_df,
            codebook=civic_codebook_df,
            dict_labels={},  # Will be populated from codebook
            dict_descriptions={},  # Will be populated from codebook
            var_type_map={},  # Will be populated from codebook
            allowed_vars=set(civic_codebook_df["variable"].tolist() if "variable" in civic_codebook_df.columns else []),
            city_mapping=CIVIC_CITY_MAPPING,
            country_mapping=CIVIC_COUNTRY_MAPPING,
            norm_varname=_norm_varname,
            sentence_case=sentence_case,
            build_stack=build_stack,
            build_yes=build_yes,
            build_mean_chart=build_mean_chart,
            group_labels=CIVIC_GROUP_LABELS,
        )
        print("[init_adapters] ✓ Civic adapter initialized")

    except Exception as e:
        _log_exc(e, where="init_adapters:civic")
        print(f"[init_adapters] ✗ Civic adapter not available: {e}")
        civic_ad = None

    SURVEYS_REGISTRY.update({
        "localmulti": local_ad,
        "civicpol": civic_ad,
    })

    print(f"[init_adapters] Registry contains: {list(SURVEYS_REGISTRY.keys())}")

 
  
    # Register both adapters
    SURVEYS_REGISTRY.update({
        "localmulti": local_ad,
        "civicpol": civic_ad,
    })

# Initialize adapters at module load so callbacks have data
# Diagnostic wrapper to catch errors
try:
    print("="*80)
    print("CALLING init_adapters()...")
    init_adapters()
    print(f"SUCCESS - SURVEYS_REGISTRY: {list(SURVEYS_REGISTRY.keys())}")
    print("="*80)
except Exception as e:
    print("="*80)
    print(f"FATAL ERROR in init_adapters(): {e}")
    import traceback
    traceback.print_exc()
    print("="*80)
    # Emergency: Register just LOCALMULTIDEM
    local_ad = LocalMultiAdapter(
        raw=raw, var_meta=var_meta, dict_labels=dict_labels,
        var_type_map=var_type_map, allowed_vars=ALLOWED_VARS,
        norm_varname=_norm_varname, sentence_case=sentence_case,
        apply_filters=apply_filters,
        find_questions_for_var=_find_questions_for_var,
        routing_line_for_var=routing_line_for_var,
        country_line_for_var=country_line_for_var,
        nonresponse_counts_labeled=nonresponse_counts_labeled,
        count_special_codes=_count_special_codes,
        build_stack=build_stack, build_yes=build_yes,
        build_mean_chart=build_mean_chart,
        multi_share_generic=multi_share_generic,
        yes_share_for_var=yes_share_for_var,
        is_numeric_var=_is_numeric_var,
        is_binary_var=_is_binary_var,
        is_numeric_scale_from_labels=_is_numeric_scale_from_labels,
        TITLE_FONT_SIZE=TITLE_FONT_SIZE,
    )
    SURVEYS_REGISTRY["localmulti"] = local_ad
    SURVEYS_REGISTRY["civicpol"] = None
    print("✓ Emergency: LOCALMULTIDEM registered")

def _empty_table_payload():
    return ([{"name": "—", "id": "__"}], [])

def _pg_table_payload(df: pd.DataFrame, var: str = ""):
    if df is None or df.empty:
        return _empty_table_payload()
    std = _standardize_table(df, var=var)
    cols = [{"name": c, "id": c} for c in std.columns]
    data = std.to_dict("records")
    return cols, data

@app.callback(
    Output("graph", "figure", allow_duplicate=True),
    Output("question_table", "children", allow_duplicate=True),
    Output("routing_info", "children", allow_duplicate=True),
    Output("footnote", "children", allow_duplicate=True),
    Output("pg-data-table", "columns", allow_duplicate=True),
    Output("pg-data-table", "data", allow_duplicate=True),
    Input("survey", "value"),
    Input("var", "value"),
    Input("city_fil", "value"),
    Input("group_fil", "value"),
    Input("gender_fil", "value"),
    Input("autoch", "value"),       
    Input("axis", "value"),
    Input("orient", "value"),
    Input("sort", "value"),
    Input("comp_aids", "value"),
    Input("theme", "value"),
    Input("subtheme", "value"),
    Input("born_here", "value"),
    Input("yob_rng", "value"),
    Input("yoa_rng", "value"),
    Input("yc_rng", "value"),
    Input("yc_life", "value"),
    Input("reason_fil", "value"),
    Input("alone_radio", "value"),
    Input("legal_fil", "value"),
    Input("vtype_store", "data"),   
    Input("vmode_store", "data"),      
    prevent_initial_call=True
)
def draw(
    survey,
    var,
    cities_full,
    groups,
    genders,
    show_auto,  # Whether to include autochthonous respondents
    axis,
    orient,
    sort_order,
    comp_aids,
    _theme_unused,
    _subtheme_unused,
    born_here,
    yob_rng,
    yoa_rng,
    yc_rng,
    yc_life,
    reason_vals,
    alone_sel,
    legal_vals,
    vtype,
    vmode,
):
    try:
        # helpers
        asc = (str(sort_order).lower() == "asc")
        sep = ("sep" in set(comp_aids or []))

        # Always-available return helper (prevents UnboundLocalError)
        def _ret(fig, qtable, routing_block, foot, df_tbl=None):
            cols, data = _pg_table_payload(df_tbl if isinstance(df_tbl, pd.DataFrame) else pd.DataFrame(), var=str(var or ""))
            return fig, qtable, routing_block, foot, cols, data

        # --- Survey routing via adapters (Civic is handled here; LOCALMULTIDEM continues below) ---
        ss = (str(survey or "localmulti").strip().lower())
        if "get_adapter" in globals():
            try:
                ss = _norm_survey(survey) if "_norm_survey" in globals() else ss
            except Exception:
                pass

        if ss in {"civicpol", "civic", "civic & political integration", "civic and political integration"}:
            if "get_adapter" not in globals():
                # civic not wired yet
                fig = px.bar(title="Civic survey selected, but adapters are not initialized yet")
                empty_route = html.Div([html.Span("Routing / Universe: ", className="fw-bold"), html.Span("—")])
                return _ret(fig, dbc.Alert("Civic adapter not initialized yet.", color="warning"), empty_route, "", pd.DataFrame())

            ad = get_adapter(survey)
            if ad is None:
               raise RuntimeError("Adapters not initialized: SURVEYS_REGISTRY is empty.")
            # Convert show_auto to boolean (checkbox may return list or None)
            show_autochthonous = True
            if isinstance(show_auto, list):
                show_autochthonous = "auto" in show_auto or "show" in show_auto or len(show_auto) > 0
            elif show_auto is None or show_auto == "" or show_auto == []:
                show_autochthonous = False
            else:
                show_autochthonous = bool(show_auto)

            # No exclusion when no filters are active; exclusion only with filters
            _civic_any_filter = (
                yob_rng not in (None, [])
                or (genders and genders not in ([], [None]))
                or (born_here and born_here not in ("ANY", None, ""))
            )
            res = ad.draw(
                var=var,
                axis=axis,
                orient=orient,
                sort_order=sort_order,
                sep=sep,
                cities_full=cities_full,
                groups=groups,
                # Civic-specific filters
                gender_vals=genders,
                birth_year_rng=yob_rng,
                born_in_country=born_here,
                include_autoch=show_autochthonous,
                title_font_size=TITLE_FONT_SIZE,
                skip_exclusion=not _civic_any_filter,
            )

            fig = res.get("fig")
            if fig is None:
                fig = go.Figure()
                fig.add_annotation(text="No data available", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(size=20))

            # For Civic: show variable name + label + description under chart
            desc = res.get("description_text", "")
            var_label = ad.label(var) if hasattr(ad, 'label') else var

            # Build variable info block: variable (column A) + label (column B) + description (column C)
            qtable_children = [
                html.Strong(f"{var}"),  # Variable name from column A
                html.Span(f" — {var_label}", className="text-muted ms-2"),  # Label from column B
            ]
            if desc and desc != "nan":
                qtable_children.append(html.Div(desc, className="text-muted mt-1"))  # Description from column C

            # Values legend (answer codes from column G)
            values_legend = res.get("values_legend", "")
            substantive_vals = res.get("substantive_values", [])
            routing_codes = res.get("routing_codes", [])

            # Build answer codes legend
            if substantive_vals:
                legend_items = [html.Li(f"{v['code']}: {v['meaning']}") for v in substantive_vals]
                qtable_children.append(html.Div([
                    html.Strong("Answer codes:", className="mt-2"),
                    html.Ul(legend_items, className="mb-1 small")
                ], className="mt-2"))

            qtable = html.Div(qtable_children)

            # Routing codes table (negative/special values from data AND codebook)
            r_df = res.get("routing_df")
            routing_children = []

            # Add routing codes from codebook (column G)
            if routing_codes:
                # Handle both dict format (LocalMulti) and string format (CivicPol)
                routing_items = []
                for v in routing_codes:
                    if isinstance(v, dict):
                        routing_items.append(html.Li(f"{v['code']}: {v['meaning']}"))
                    else:
                        # String format from CivicPolAdapter
                        routing_items.append(html.Li(str(v)))
                routing_children.append(html.Div([
                    html.Strong("Routing / Excluded values:"),
                    html.Ul(routing_items, className="mb-1 small text-muted")
                ]))

            # Add actual data routing summary if available
            if isinstance(r_df, pd.DataFrame) and not r_df.empty:
                routing_children.append(
                    dbc.Table.from_dataframe(r_df, striped=False, bordered=True, hover=False, size="sm", className="mt-2")
                )

            if routing_children:
                routing_block = html.Div(routing_children)
            else:
                routing_block = html.Div([html.Span("Routing variables: ", className="fw-bold"), html.Span("—")])

            footer_text = res.get("footer_text", "")
            foot_node = ""
            if footer_text:
                foot_node = html.Pre(footer_text, style={"fontSize": "0.85rem", "color": "#666", "whiteSpace": "pre-wrap", "margin": "10px 0 0 0"})
            _civic_excl = res.get("excluded_units_info", [])
            foot_node = _append_excl_to_footnote(foot_node, _civic_excl)
            table_df = res.get("table_df") if isinstance(res.get("table_df"), pd.DataFrame) else pd.DataFrame()
            return _ret(fig, qtable, routing_block, foot_node, table_df)

        if (
            not var
            or var not in raw.columns
            or _norm_varname(var) not in ALLOWED_VARS
        ):
            empty_route = html.Div([
                html.Span("Routing / Universe: ", className="fw-bold"),
                html.Span("—")
            ])
            fig = px.bar(title="No data for this variable (not in allowed set)")
            return _ret(fig, html.Div(), empty_route, "", pd.DataFrame())
        df_use = apply_filters(
            raw,
            yob_rng=yob_rng,
            yoa_rng=yoa_rng,
            yc_rng=yc_rng,
            yc_life=yc_life or [],
            reason_vals=reason_vals,
            alone_sel=alone_sel,
            legal_vals=legal_vals,
            genders=genders,
            born_here_sel=born_here,
        )
        # Use the exact same filtered slice for ALL chart types (bar + box)
        df_filtered = df_use.copy()
        
        # Ensure required columns exist after filtering
        if "city_full" not in df_use.columns:
            df_use = df_use.copy()
            if "city" in df_use.columns:
                df_use["city_full"] = df_use["city"].map(to_city_full)
            else:
                df_use["city_full"] = "All cities"

        if "group_disp" not in df_use.columns:
            df_use = df_use.copy()
            df_use["group_disp"] = _group_disp_series(df_use)

        # CHANGE 2: Keep df_filtered separate and create df_display
        foot_warn = ""
        df_display = df_filtered.copy()  # Use filtered data for display
        
        # Ensure required columns exist in df_display
        if "city_full" not in df_display.columns:
            df_display = df_display.copy()
            if "city" in df_display.columns:
                df_display["city_full"] = df_display["city"].map(to_city_full)
            else:
                df_display["city_full"] = "All cities"

        if "group_disp" not in df_display.columns:
            df_display = df_display.copy()
            df_display["group_disp"] = _group_disp_series(df_display)
        
        # Fallback to unfiltered data only if filtered data is empty
        if df_display.empty:
            df_display = raw.copy()
            foot_warn = " | No rows after filters — showing unfiltered data."
            
            if "city_full" not in df_display.columns:
                df_display = df_display.copy()
                if "city" in df_display.columns:
                    df_display["city_full"] = df_display["city"].map(to_city_full)
                else:
                    df_display["city_full"] = "All cities"
            
            if "group_disp" not in df_display.columns:
                df_display = df_display.copy()
                df_display["group_disp"] = _group_disp_series(df_display)

        # CHANGE 3: Autochthonous handling with df_display
        # Convert show_auto to boolean
        include_autoch = bool(show_auto)
        if isinstance(show_auto, list):
            include_autoch = len(show_auto) > 0
        elif show_auto is None or show_auto == "" or show_auto == []:
            include_autoch = False

        if not include_autoch:
            df_display = df_display[df_display["group_disp"] != "Autochthonous"].copy()

        # ── Group filter (handle AUTOCH_KEY properly) ──
        # build_stack / build_yes filter by numeric group codes internally,
        # but AUTOCH_KEY is a string sentinel.  Do the filtering here and
        # pass groups=None downstream so the functions skip their own filter.
        if groups:
            want_auto = AUTOCH_KEY in set(groups)
            num_groups = [g for g in groups if g != AUTOCH_KEY]

            mask = pd.Series(False, index=df_display.index)
            if num_groups and "group" in df_display.columns:
                mask = mask | df_display["group"].isin(num_groups)
            if want_auto and "group_disp" in df_display.columns:
                mask = mask | (df_display["group_disp"] == AUTOCH_LABEL)
            df_display = df_display[mask].copy()
            groups = None          # already filtered — tell downstream to keep all

        # CHANGE 4: City selection with df_display
        sel_codes = []
        if cities_full:
            present = set(df_display["city_full"].dropna().astype(str))
            sel_wanted = [c for c in cities_full if c in present]
            if sel_wanted:
                sel_codes = (df_display.loc[df_display["city_full"].isin(sel_wanted), "city"]
                                   .dropna().astype(str).unique().tolist())

        
        if str(axis).lower() == "group":
            primary_key, secondary_key = "group_disp", "city_full"
        else:
            primary_key, secondary_key = "city_full", "group_disp"
        x_key = primary_key

        # --- Min-25 exclusion ---
        # No filters → no exclusion. Filters active → recompute on filtered data.
        _draw_excluded_info = []
        _any_filter = (
            _range_is_active(yob_rng, BY_MIN, BY_MAX)
            or _range_is_active(yoa_rng, YA_MIN, YA_MAX)
            or _range_is_active(yc_rng, YC_MIN, min(YC_MAX, Q6_MAX_HARD))
            or (yc_life and yc_life not in ([], [None]))
            or (reason_vals and reason_vals not in ([], [None]))
            or (alone_sel and alone_sel not in ("ANY", None, ""))
            or (legal_vals and legal_vals not in ([], [None]))
            or (born_here and born_here not in ("ANY", None, ""))
        )
        if _any_filter:
            df_display, _draw_excluded_info = _compute_exclusion_info(
                df_display, var, primary_key, secondary_key
            )

        vtype_int = int(vtype) if isinstance(vtype, (int, float, str)) and str(vtype).isdigit() else -1
        mode = (vmode or ("yes" if vtype_int in (1, 2) else "stack"))

        table_df = pd.DataFrame()
        v_norm = str(var or "").strip().lower()

       
        # CHANGE 5: All chart functions now use df_display
        if v_norm in TIME_LINE_VARS:
            
            fig, table_df = build_time_line_area(df_display, v_norm)

        
        elif v_norm in REGION_HEATMAP_VARS:
            axis_norm = (str(axis).strip().lower() if axis is not None else "city")
            fig, table_df = build_region_heatmap(
                df=df_display,
                var=v_norm,
                axis=axis_norm,
            )

        
        elif _is_numeric_scale_from_labels(var):
            fig, table_df = build_mean_chart(
                df=df_display,
                var=var,
                primary_key=primary_key,
                secondary_key=secondary_key,
                orient=orient,
                sep=sep,
                sort_asc=asc,
            )

            
            fig.update_layout(
                modebar=dict(
                    remove=[
                        "toImage", "autoScale2d", "zoom2d", "pan2d", "select2d", "lasso2d",
                        "zoomIn2d", "zoomOut2d", "resetScale2d",
                    ]
                )
            )

        elif _is_numeric_var(var) or vtype_int == 4:
            fig, table_df = build_mean_chart(
                df=df_display,
                var=var,
                primary_key=primary_key,
                secondary_key=secondary_key,
                orient=orient,
                sep=sep,
                sort_asc=asc,
            )
            fig.update_layout(
                modebar=dict(
                    remove=[
                        "toImage","autoScale2d","zoom2d","pan2d","select2d",
                        "lasso2d","zoomIn2d","zoomOut2d","resetScale2d"
                    ]
                )
            )
        elif (vtype_int in (1, 2)) and _is_binary_var(var) and (mode == "yes"):
            by = [x_key, "group_disp"] if x_key != "group_disp" else [x_key]
            table_df = yes_share_for_var(df_display, var, by).reset_index(drop=True)

            if "n" in table_df.columns:
                keep = table_df.groupby(x_key)["n"].sum()
                keep = keep[keep > 0].index.tolist()
                table_df = table_df[table_df[x_key].isin(keep)].copy()

            fig = build_yes(
                df=df_display, var=var,
                colour_key="group_disp", x_key=x_key, orient=orient,
                city_codes=(sel_codes or None), groups=groups, genders=genders,
                asc=asc, show_auto=include_autoch, sep=sep,
            )

        else:
            g, resp_order = multi_share_generic(df_display, var, by=[primary_key, secondary_key])
            if "cnt" in g.columns:
                g["cnt"] = pd.to_numeric(g["cnt"], errors="coerce").fillna(0).astype(int)
                totals = (
                    g.groupby([primary_key, secondary_key], dropna=False)["cnt"]
                    .sum()
                    .reset_index(name="_n")
                )
                g = g.merge(totals, on=[primary_key, secondary_key], how="left")
                g = g[g["_n"] > 0].copy()
            table_df = g.copy()
            fig = build_stack(
                df=df_display,
                var=var,
                x_key=("group_disp" if str(axis).lower() == "group" else "city_full"),
                orient=orient,
                city_codes=(sel_codes or None),
                groups=groups,
                genders=genders,
                include_autochthonous=include_autoch,
                sep=sep,
                sort_asc=asc,
            )
        lbl = dict_labels.get(str(var).strip().lower(), "") or str(var).upper()
        fig.update_layout(title={"text": lbl, "x": 0.5, "xanchor": "center"},
                          title_font_size=TITLE_FONT_SIZE)

        qrows = _find_questions_for_var(var)
        if qrows:
            qtable = dbc.Table(
                [
                    html.Thead(html.Tr([html.Th("ID (A)"), html.Th("Question (B)")])),
                    html.Tbody([html.Tr([html.Td(k), html.Td(v)]) for k, v in qrows]),
                ],
                bordered=True, hover=False, responsive=True, striped=False, size="sm",
                className="mt-2",
            )
        else:
            qtable = html.Div("", style={"display": "none"})

        # CHANGE 6: Non-response counts with df_display
        try:
            nn = nonresponse_counts_labeled(df_display, var)
            specials = _count_special_codes(df_display, var)
        except Exception:
            nn, specials = {}, {}

        question_text = dict_labels.get(str(var).strip().lower(), "")
        question_text = (question_text.strip().lower().capitalize() if isinstance(question_text, str) and question_text.strip() else "")
        try:
            country_line = country_line_for_var(var) or ""
        except Exception:
            country_line = ""

        meta_parts = []
        if question_text: meta_parts.append(f"Question (codebook): {question_text}")
        if country_line:  meta_parts.append(country_line)
        meta_block = "  \n".join(meta_parts)

        footer = (
            (meta_block + ("  \n" if meta_block else ""))
            + "Negative/Non-response — "
            + " | ".join(f"{k}: {v}" for k, v in (nn.items() if nn else []))
            + (" | " if specials else "")
            + " · ".join([f"{k}: {v}" for k, v in (specials.items() if specials else [])])
            + (foot_warn if foot_warn else "")
        ).strip()
        route_txt = routing_line_for_var(var)
        routing_block = html.Div([
            html.Span("Routing variables: ", className="fw-bold"),
            html.Span(route_txt if route_txt else "—")
        ])

        # Build HTML footnote with gray text + red exclusion line
        foot_node = ""
        if footer:
            foot_node = html.Pre(footer, style={"fontSize": "0.85rem", "color": "#666", "whiteSpace": "pre-wrap", "margin": "10px 0 0 0"})
        foot_node = _append_excl_to_footnote(foot_node, _draw_excluded_info)

        return _ret(fig, qtable, routing_block, foot_node, table_df)
    except Exception as e:
        _log_exc(e, where="draw")
        err_fig = px.bar(title="Error while drawing figure")
        err_table = dbc.Alert("Question table unavailable due to an error. See log.", color="danger")
        err_footer = f"Rendering error: {e}"
        cols, data = _empty_table_payload()
        empty_route = html.Div([html.Span("Routing / Universe: ", className="fw-bold"), html.Span("—")])
        return err_fig, err_table, empty_route, err_footer, cols, data
    
@app.callback(Output("page-content", "children"), Input("url", "pathname"))
def render_page(pathname):
    if pathname == "/" or pathname is None:
        return home_layout()
    elif pathname == "/playground":
        return playground_layout()
    elif pathname == "/readymade":
        return readymade_layout()
    elif pathname == "/examples":
        return examples_layout()
    else:
        return home_layout()


server = app.server

if __name__ == "__main__":
    init_adapters()
    print("Adapters:", SURVEYS_REGISTRY.keys())
    app.run(host="127.0.0.1", port=8009, debug=True)