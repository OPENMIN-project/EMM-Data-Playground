# survey_civic.py
"""
Adapter for Civic & Political Integration Survey.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go


# =============================================================================
# LAU_1 DECODER
# =============================================================================
LAU_1_DECODER: dict[str, str] = {
    'GM0363': 'Amsterdam', 'GM0599': 'Rotterdam',
    '11002': 'Antwerp', '21004': 'Brussels', '62063': 'Liege',
    '08019': 'Barcelona', '080508': 'Faro', '28079': 'Madrid',
    'CH2701': 'Basel', 'CH6621': 'Geneva', 'CH0261': 'Zurich',
    '11000000': 'Berlin', '5112000': 'Duisburg', '06412000': 'Frankfurt (Main)', '8111000': 'Stuttgart',
    '13578': 'Budapest',
    'E09000007': 'Camden (London)', 'E09000012': 'Hackney (London)',
    'E09000014': 'Haringey (London)', 'E09000019': 'Islington (London)',
    '151205': 'Setubal',
    '69123': 'Lyon', '75056': 'Paris', '67482': 'Strasbourg',
    '015146': 'Milan', '63049': 'Naples', '001272': 'Turin',
    '0301': 'Oslo', '0180': 'Stockholm',
    'E09000007; E09000012; E09000014; E09000019': 'London',
    '40101': 'Vienna', '90001': 'Vienna',
    'PT001C': 'Lisbon',
    '05112000': 'Duisburg', '08111000': 'Stuttgart', '063049': 'Naples',
}
for code in range(110501, 110732):
    LAU_1_DECODER[f'{code:06d}'] = 'Lisbon'
    LAU_1_DECODER[str(code)] = 'Lisbon'


# =============================================================================
# ROUTING CODES
# =============================================================================
ROUTING_CODES = {-996, -997, -998, -999, -995}
MIN_NONROUTING_N = 25  # Hide bars/boxes with fewer than this many non-routing responses
AUTOCH_KEY = "__AUTOCH__"
AUTOCH_LABEL = "Autochthonous"
ROUTING_LABELS = {
    -995: "Not applicable",
    -996: "Question not asked",
    -997: "Refused",
    -998: "Don't know",
    -999: "Missing",
}

# =============================================================================
# EXCLUDED THEMES (not shown in Data Playground)
# =============================================================================
EXCLUDED_THEMES = {
    "Variables Identifying Studies and Respondents",
    "variables identifying studies and respondents",
}

# Variables that should NOT appear in the Data Playground visualisation
EXCLUDED_VARIABLES = {
    "rlegit1",
    "rop_demostr",
    "rop_auth",
    "rop_ineq",
    "ratti_homosexual",
    "rauth",
    "rlwordr",
    "rpstmat",
    "rgrow_environm",
    "rtrust_diffethnic",
    "rencour_participationact",
    "rturnreco_preshost",
    "rturnreco_reghost",
    "rturnreco_preshome",
    "rturnreco_parlhome",
    "rturnreco_reghome",
    "rturnreco_lochome",
    "rturnint_preshost",
    "rturnint_parlhost",
    "rturnint_reghost",
    "rturnint_lochost",
    "rturnint_preshome",
    "rturnint_parlhome",
    "rturnint_reghome",
    "rturnint_lochome",
    "ryearmgrt_cntry",
    "ryearmgrt_cty",
    "rdiscus1",
    "rpolelect",
    "rknows",
}


# =============================================================================
# VARIABLE CONFIGURATIONS
# =============================================================================
VAR_CONFIG: dict[str, dict] = {
    # Binary Yes/No variables
    "rencour_participationact": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},
    "rasscmbr1": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},
    "runion": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},
    "rmember": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},
    "rhostlang_native": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes, native speaker"}, "order": [0, 1]},
    "rhostcitz_interest_b": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},
    "rcontpol": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},
    "rcontlcloff": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},
    "rwrkplpty": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},
    "rsignpet": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},
    "rpubdem": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},
    "rpldon": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},
    "rcontmed": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},
    "rstrike": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},
    "rjob_selfempl": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No, employee", 1: "Yes, self-employed"}, "order": [0, 1]},
    "rjob_fulltime": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "Part-time (<35h)", 1: "Full-time (35h+)"}, "order": [0, 1]},

    "rturnint_parlhost": {"type": "bar", "valid_codes": [1, 2], "labels": {1: "Yes", 2: "No"}, "order": [1, 2]},
    "rturnint_lochost": {"type": "bar", "valid_codes": [1, 2], "labels": {1: "Yes", 2: "No"}, "order": [1, 2]},

    "rturnreco_lochost": {"type": "bar", "valid_codes": [1, 2, 3], "labels": {1: "Yes", 2: "No", 3: "Not eligible"}, "order": [1, 2, 3]},
    "rturnreco_parlhost": {"type": "bar", "valid_codes": [1, 2, 3], "labels": {1: "Yes", 2: "No", 3: "Not eligible"}, "order": [1, 2, 3]},

    "ragegr": {"type": "bar", "valid_codes": [1, 2, 3, 4], "labels": {1: "≤29", 2: "30-45", 3: "46-64", 4: "65+"}, "order": [1, 2, 3, 4]},

    "rjob_status": {"type": "bar", "valid_codes": [1, 2, 3, 4, 5, 6], "labels": {1: "Paid work", 2: "In education", 3: "Unemployed", 4: "Sick/disabled", 5: "Household", 6: "Other"}, "order": [1, 2, 3, 4, 5, 6]},

    "reducation": {"type": "bar", "valid_codes": [1, 2, 3], "labels": {1: "Primary", 2: "Secondary", 3: "Higher"}, "order": [1, 2, 3]},

    "rjob_pubsec": {"type": "bar", "valid_codes": [1, 2, 3], "labels": {1: "Public", 2: "Private", 3: "Self-employed/other"}, "order": [1, 2, 3]},

    "redenom": {"type": "bar", "valid_codes": [1, 2, 3, 4, 5, 6, 7], "labels": {1: "Catholic", 2: "Protestant", 3: "Orthodox", 4: "Jewish", 5: "Islam", 6: "Other", 7: "None"}, "order": [1, 2, 3, 4, 5, 6, 7]},

    "rchurcha": {"type": "bar", "valid_codes": [1, 2, 3, 4], "labels": {1: "Weekly+", 2: "Monthly", 3: "<Monthly", 4: "Never"}, "order": [1, 2, 3, 4]},

    "rvisithome": {"type": "bar", "valid_codes": [1, 2, 3, 4], "labels": {1: "Never", 2: "<1/3 years", 3: "1/3 years", 4: "Yearly+"}, "order": [1, 2, 3, 4]},

    "rincomehh": {"type": "bar", "valid_codes": list(range(1, 11)), "labels": {i: f"D{i}" for i in range(1, 11)}, "order": list(range(1, 11))},

    "rheadhh": {"type": "bar", "valid_codes": [1, 2], "labels": {1: "Respondent", 2: "Someone else"}, "order": [1, 2]},

    "rlegpermit_type": {"type": "bar", "valid_codes": [1, 2, 3, 4, 5, 6], "labels": {1: "Permanent", 2: "Work", 3: "Study", 4: "Family", 5: "Refugee", 6: "Other"}, "order": [1, 2, 3, 4, 5, 6]},

    "rownhouse": {"type": "bar", "valid_codes": [1, 2], "labels": {1: "Owns", 2: "Rents"}, "order": [1, 2]},

    "rhostil_muslim": {"type": "bar", "valid_codes": [1, 2, 3, 4, 5], "labels": {1: "Never", 2: "Rarely", 3: "Occasionally", 4: "Regularly", 5: "Frequently"}, "order": [1, 2, 3, 4, 5]},

    "rjob_permanent": {"type": "bar", "valid_codes": [0, 1, 2], "labels": {0: "No, fixed-term or temporary contract", 1: "Yes, permanent or undetermined duration contract", 2: "Other (self-employed, business owners or similar)"}, "order": [0, 1, 2]},

    "rhostcitz_interest_a": {"type": "bar", "valid_codes": [0, 1, 2, 3, 4], "labels": {0: "No, certainly not", 1: "Probably not", 2: "Maybe yes, maybe not", 3: "Probably", 4: "Yes, certainly"}, "order": [0, 1, 2, 3, 4]},

    "rcitizfather_current": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},

    "rcitizmother_current": {"type": "bar", "valid_codes": [0, 1], "labels": {0: "No", 1: "Yes"}, "order": [0, 1]},

    # BOX PLOT VARIABLES
    "rtrust_ppl": {"type": "box", "spectrum": ("Low trust", "High trust")},
    "rhostlang_fluent_b": {"type": "box", "spectrum": ("Doesn't speak", "Speaks well")},
    "rhostlang_fluent_c": {"type": "box", "spectrum": ("Doesn't speak", "Speaks well")},
    "rhostlang_fluent_a": {"type": "box", "spectrum": ("Speaks badly", "Speaks fluently")},
    "rselfid_hostppl": {"type": "box", "spectrum": ("Low attachment", "High attachment")},
    "rselfid_samethnic": {"type": "box", "spectrum": ("Low attachment", "High attachment")},
    "rselfid_homecount": {"type": "box", "spectrum": ("Low attachment", "High attachment")},
    "rlrsp": {"type": "box", "spectrum": ("Left", "Right")},
    "ropinion_rolrelig": {"type": "box", "spectrum": ("Low influence", "High influence")},
    "rpolint_host": {"type": "box", "spectrum": ("Low interest", "High interest")},
    "rpolint_home": {"type": "box", "spectrum": ("Low interest", "High interest")},
    "rpolint_intnl": {"type": "bar", "valid_codes": [1, 2, 3, 4], "labels": {1: "Not at all interested", 2: "Not very interested", 3: "Quite interested", 4: "Very interested"}, "order": [1, 2, 3, 4]},
    "ratti_rolwomen": {"type": "box", "spectrum": ("Totally disagree", "Totally agree")},
    "rreligimport": {"type": "box", "spectrum": ("Not important at all", "Extremely important")},
    "refficin": {"type": "box", "spectrum": ("Low", "High")},
    "rtrust_samethnic": {"type": "box", "spectrum": ("Low trust", "High trust")},
    "rselfpercep_host": {"type": "box", "spectrum": ("Low", "High")},
    "ratt_religdivers": {"type": "box", "spectrum": ("Totally disagree", "Totally agree")},
    "ratt_foreigncust": {"type": "box", "spectrum": ("Totally disagree", "Totally agree")},
    "reffecex": {"type": "box", "spectrum": ("Low", "High")},
    "ratti_abortion": {"type": "box", "spectrum": ("Totally disagree", "Totally agree")},
    "rpolint_gen": {"type": "box", "spectrum": ("Low Interest", "High Interest")},
}


# =============================================================================
# COLOR PALETTE - Same Okabe-Ito as LOCALMULTIDEM
# =============================================================================
import colorsys as _colorsys

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

def _shade_hex(base_hex, l_target):
    hx = str(base_hex).lstrip("#")
    r, g, b = int(hx[0:2], 16) / 255.0, int(hx[2:4], 16) / 255.0, int(hx[4:6], 16) / 255.0
    h, l, s = _colorsys.rgb_to_hls(r, g, b)
    r2, g2, b2 = _colorsys.hls_to_rgb(h, max(0.0, min(1.0, l_target)), s)
    return "#{:02x}{:02x}{:02x}".format(int(r2 * 255), int(g2 * 255), int(b2 * 255))

def _expand_palette(base, target_n=15):
    out = list(base)
    if target_n <= len(out):
        return out[:target_n]
    for cyc in range(1, 6):
        for col in base:
            if col.lower() == "#000000":
                continue
            lt = 0.65 if cyc % 2 == 1 else 0.35
            out.append(_shade_hex(col, lt))
            if len(out) >= target_n:
                return out[:target_n]
    return out[:target_n]

_COLORS = _expand_palette(_OKABE_ITO_BASE, target_n=15)
STACK_PATTERN_SHAPES = ["", ".", "/", "\\", "x", "-", "|", "+", "o", "*"]
USE_STACK_PATTERNS = True


def _empty_figure(message: str = "No data available") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(size=16, color="gray"))
    fig.update_layout(template="plotly_white", xaxis=dict(visible=False), yaxis=dict(visible=False), height=360)
    return fig


def _sentence_case(s: str) -> str:
    s = str(s or "").strip().lower()
    return s[:1].upper() + s[1:] if s else s


def _decode_lau1(code: Any) -> str:
    c = str(code).strip()
    if c in LAU_1_DECODER:
        return LAU_1_DECODER[c]
    c_stripped = c.lstrip("0")
    if c_stripped in LAU_1_DECODER:
        return LAU_1_DECODER[c_stripped]
    for width in [6, 8]:
        c_padded = c.zfill(width)
        if c_padded in LAU_1_DECODER:
            return LAU_1_DECODER[c_padded]
    return f"LAU-{c}"


@dataclass
class CivicPolAdapter:
    """Adapter for Civic & Political Integration survey."""

    raw: pd.DataFrame
    codebook: pd.DataFrame
    dict_labels: dict[str, str]
    dict_descriptions: dict[str, str]
    var_type_map: dict[str, str]
    allowed_vars: set[str]
    city_mapping: dict[str, str]
    country_mapping: dict[str, str]
    norm_varname: Callable[[str], str]
    sentence_case: Callable[[str], str]
    build_stack: Callable[..., Any]
    build_yes: Callable[..., Any]
    build_mean_chart: Callable[..., Any]
    group_labels: Optional[dict[int, str]] = None
    TITLE_FONT_SIZE: int = 18

    def __post_init__(self) -> None:
        self.raw = self.raw.copy() if isinstance(self.raw, pd.DataFrame) else pd.DataFrame()
        self.raw.columns = [str(c).strip().lower() for c in self.raw.columns]

        self.codebook = self.codebook.copy() if isinstance(self.codebook, pd.DataFrame) else pd.DataFrame()
        if not self.codebook.empty:
            self.codebook.columns = [str(c).strip().lower() for c in self.codebook.columns]

        for col in ["variable", "label", "description", "theme", "subtheme", "type", "values"]:
            if col not in self.codebook.columns:
                self.codebook[col] = ""

        self.codebook["variable"] = self.codebook["variable"].astype(str).str.strip().str.lower()
        self.codebook["label"] = self.codebook["label"].astype(str).str.strip()
        self.codebook["description"] = self.codebook["description"].astype(str).str.strip()
        self.codebook["theme"] = self.codebook["theme"].astype(str).str.strip()
        self.codebook["subtheme"] = self.codebook["subtheme"].astype(str).str.strip()
        self.codebook["type"] = self.codebook["type"].astype(str).str.strip().str.lower()

        self.dict_labels = {}
        self.dict_descriptions = {}
        self.var_type_map = {}

        for _, row in self.codebook.iterrows():
            v = str(row.get("variable", "")).strip().lower()
            if not v:
                continue
            lab = str(row.get("label", "")).strip()
            desc = str(row.get("description", "")).strip()
            typ = str(row.get("type", "")).strip().lower()
            if lab and lab.lower() != "nan":
                self.dict_labels[v] = lab
            if desc and desc.lower() != "nan":
                self.dict_descriptions[v] = desc
            if typ and typ.lower() != "nan":
                self.var_type_map[v] = typ

        if not self.codebook.empty and not self.raw.empty:
            data_cols = set(self.raw.columns)
            self.codebook = self.codebook[self.codebook["variable"].isin(data_cols)].copy()
        # Remove excluded variables from codebook
        if not self.codebook.empty:
            self.codebook = self.codebook[~self.codebook["variable"].isin(EXCLUDED_VARIABLES)].copy()

        self.allowed_vars = set(self.codebook["variable"].tolist()) if not self.codebook.empty else set()
        self.allowed_vars -= EXCLUDED_VARIABLES
        self._decode_dimensions()

        # Build group color map for consistent colors
        if "group_disp" in self.raw.columns:
            unique_groups = sorted(self.raw["group_disp"].dropna().unique())
            self._group_colors = {g: _COLORS[i % len(_COLORS)] for i, g in enumerate(unique_groups)}
        else:
            self._group_colors = {}

        print(f"[CivicPolAdapter] Initialized with {len(self.raw)} rows, {len(self.allowed_vars)} variables")
        print(f"[CivicPolAdapter] Themes: {self.codebook['theme'].nunique()}, Subthemes: {self.codebook['subtheme'].nunique()}")

    def _decode_dimensions(self) -> None:
        df = self.raw
        if df is None or df.empty:
            return

        if "lau_1" in df.columns:
            df["city"] = df["lau_1"].apply(_decode_lau1)
            df["city_full"] = df["city"]

        if "rgroup" in df.columns:
            df["rgroup_str"] = df["rgroup"].astype(str).str.strip()
            # Only set group_disp if not already present (e.g. from _prepare_civic_dimensions)
            if "group_disp" not in df.columns:
                if self.group_labels:
                    rg_num = pd.to_numeric(df["rgroup"], errors="coerce")
                    df["group_disp"] = rg_num.apply(
                        lambda x: self.group_labels.get(int(x), f"Group {int(x)}") if pd.notna(x) and x >= 0 else None
                    )
                else:
                    df["group_disp"] = df["rgroup_str"]

        # Gender from rgender (1=Male, 2=Female)
        if "rgender" in df.columns:
            g = pd.to_numeric(df["rgender"], errors="coerce")
            df["gender"] = np.where(g == 1, "Male", np.where(g == 2, "Female", "Other"))

        # Birth year from ryrbrn
        if "ryrbrn" in df.columns:
            df["birth_year"] = pd.to_numeric(df["ryrbrn"], errors="coerce")

        self.raw = df

    # =========================================================================
    # DROPDOWN OPTIONS
    # =========================================================================

    def theme_options(self) -> list[dict]:
        if self.codebook.empty or "theme" not in self.codebook.columns:
            return []
        themes = self.codebook["theme"].dropna().astype(str).str.strip().loc[lambda s: s.ne("") & s.ne("nan")].unique().tolist()
        # Filter out excluded themes
        themes = [t for t in themes if t.lower() not in {x.lower() for x in EXCLUDED_THEMES}]
        return [{"label": _sentence_case(t), "value": t} for t in sorted(themes)]

    def subtheme_options(self, theme: str | None) -> list[dict]:
        if self.codebook.empty or "subtheme" not in self.codebook.columns:
            return []
        df = self.codebook
        # Filter out excluded themes
        df = df[~df["theme"].astype(str).str.strip().str.lower().isin({x.lower() for x in EXCLUDED_THEMES})]
        t = str(theme or "").strip()
        if t:
            df = df[df["theme"].astype(str).str.strip() == t]
        subs = df["subtheme"].dropna().astype(str).str.strip().loc[lambda s: s.ne("") & s.ne("nan")].unique().tolist()
        return [{"label": _sentence_case(s), "value": s} for s in sorted(subs)]

    def variable_options(self, theme: str | None, subtheme: str | None) -> list[dict]:
        if self.codebook.empty or "variable" not in self.codebook.columns:
            return []
        df = self.codebook
        # Filter out excluded themes
        df = df[~df["theme"].astype(str).str.strip().str.lower().isin({x.lower() for x in EXCLUDED_THEMES})]
        t = str(theme or "").strip()
        st = str(subtheme or "").strip()
        if t:
            df = df[df["theme"].astype(str).str.strip() == t]
        if st:
            df = df[df["subtheme"].astype(str).str.strip() == st]
        opts = []
        for _, row in df.iterrows():
            v = str(row.get("variable", "")).strip().lower()
            if not v or v == "nan":
                continue
            if v in EXCLUDED_VARIABLES:
                continue
            lab = str(row.get("label", "")).strip()
            label_txt = _sentence_case(lab) if lab and lab.lower() != "nan" else v
            opts.append({"label": label_txt, "value": v})
        return opts

    def label(self, var: str) -> str:
        v = str(var or "").strip().lower()
        lab = self.dict_labels.get(v, "")
        return _sentence_case(lab) if lab else v.upper()

    def description(self, var: str) -> str:
        v = str(var or "").strip().lower()
        return self.dict_descriptions.get(v, "")

    # =========================================================================
    # FILTERING
    # =========================================================================

    def filter_df(
        self,
        cities_full: list[str] | None = None,
        groups: list[Any] | None = None,
        gender_vals: list[str] | None = None,
        birth_year_rng: list[Any] | None = None,
        **_ignored,
    ) -> pd.DataFrame:
        df = self.raw
        if df is None or df.empty:
            return pd.DataFrame()

        sub = df.copy()

        if cities_full:
            keep = set(str(x) for x in cities_full if str(x).strip())
            if "city" in sub.columns:
                sub = sub[sub["city"].astype(str).isin(keep)]

        if groups:
            keep_g = set(str(g) for g in groups if str(g).strip() and g != AUTOCH_KEY)
            want_auto = AUTOCH_KEY in set(str(g) for g in groups)
            if "group_disp" in sub.columns:
                mask = pd.Series(False, index=sub.index)
                if keep_g:
                    mask = mask | sub["group_disp"].astype(str).isin(keep_g)
                if want_auto:
                    mask = mask | (sub["group_disp"] == AUTOCH_LABEL)
                sub = sub[mask]

        # Gender filter
        if gender_vals:
            keep_sex = set(str(g) for g in gender_vals if str(g).strip())
            if "gender" in sub.columns:
                sub = sub[sub["gender"].astype(str).isin(keep_sex)]

        # Birth year filter
        if birth_year_rng and len(birth_year_rng) >= 2:
            lo, hi = birth_year_rng[0], birth_year_rng[1]
            if "birth_year" in sub.columns:
                if lo is not None:
                    sub = sub[pd.to_numeric(sub["birth_year"], errors="coerce") >= float(lo)]
                if hi is not None:
                    sub = sub[pd.to_numeric(sub["birth_year"], errors="coerce") <= float(hi)]

        return sub

    # =========================================================================
    # MAIN DRAW METHOD
    # =========================================================================

    def draw(
        self,
        var: str,
        axis: str = "city",
        orient: str = "h",
        sort_order: str = "desc",
        sep: bool = True,
        cities_full: list[str] | None = None,
        groups: list[Any] | None = None,
        gender_vals: list[str] | None = None,
        birth_year_rng: list[Any] | None = None,
        title_font_size: int = 18,
        include_autoch: bool = True,
        skip_exclusion: bool = False,
        **_ignored,
    ) -> dict[str, Any]:
        v = str(var or "").strip().lower()
        if not v:
            return {"fig": _empty_figure("Select a variable"), "footer_text": "", "description_text": "", "table_df": pd.DataFrame()}

        if self.raw is None or self.raw.empty:
            return {"fig": _empty_figure("No data loaded"), "footer_text": "", "description_text": self.description(v), "table_df": pd.DataFrame()}

        if v not in self.raw.columns:
            return {"fig": _empty_figure(f"Variable not found: {v}"), "footer_text": "", "description_text": "", "table_df": pd.DataFrame()}

        if "city" not in self.raw.columns or "group_disp" not in self.raw.columns:
            return {"fig": _empty_figure("Missing city/group columns"), "footer_text": "", "description_text": "", "table_df": pd.DataFrame()}

        sub = self.filter_df(
            cities_full=cities_full,
            groups=groups,
            gender_vals=gender_vals,
            birth_year_rng=birth_year_rng,
        )

        # Filter out autochthonous if not included
        if not include_autoch and "group_disp" in sub.columns:
            sub = sub[sub["group_disp"] != AUTOCH_LABEL]

        if sub.empty:
            return {"fig": _empty_figure("No data after filters"), "footer_text": "", "description_text": self.description(v), "table_df": pd.DataFrame()}

        # AXIS SWITCHING: determine primary and secondary based on axis parameter
        a = str(axis or "").strip().lower()
        if a == "group" or "group" in a and not a.startswith("city"):
            # Group per city: primary=group, secondary=city
            primary, secondary = "group_disp", "city"
        else:
            # City per group (default): primary=city, secondary=group
            primary, secondary = "city", "group_disp"

        # Determine visualization type
        config = VAR_CONFIG.get(v, {})
        viz_type = config.get("type", "bar")
        cb_type = self.var_type_map.get(v, "").lower()
        if "box" in cb_type:
            viz_type = "box"

        if viz_type == "box":
            fig, table_df, routing_text, excluded_units_info = self._draw_box_plot(sub, v, primary, secondary, orient, sort_order, title_font_size, skip_exclusion=skip_exclusion)
        else:
            fig, table_df, routing_text, excluded_units_info = self._draw_stacked_bar(sub, v, primary, secondary, orient, sort_order, title_font_size, skip_exclusion=skip_exclusion)

        # Build response labels text for footer (WITHOUT exclusion — that goes separately)
        response_labels_text = self._get_response_labels_text(v)

        footer_parts = []
        if response_labels_text:
            footer_parts.append(response_labels_text)
        if routing_text:
            footer_parts.append(routing_text)

        footer_text = "\n".join(footer_parts)

        return {
            "fig": fig,
            "description_text": self.description(v),
            "footer_text": footer_text,
            "excluded_units_info": excluded_units_info,
            "routing_codes": [],
            "routing_df": pd.DataFrame(),
            "table_df": table_df,
        }

    def _get_response_labels_text(self, var: str) -> str:
        config = VAR_CONFIG.get(var, {})
        labels = config.get("labels", {})
        order = config.get("order", [])
        spectrum = config.get("spectrum")

        if spectrum:
            return f"Scale: 0 = {spectrum[0]} ... 1 = {spectrum[1]}"

        if labels and order:
            parts = [f"{code}={labels[code]}" for code in order if code in labels]
            if parts:
                return "Responses: " + " | ".join(parts)

        return ""

    def _draw_stacked_bar(
        self,
        df: pd.DataFrame,
        var: str,
        primary: str,
        secondary: str,
        orient: str,
        sort_order: str,
        title_font_size: int,
        skip_exclusion: bool = False,
    ) -> tuple[go.Figure, pd.DataFrame, str, list[str]]:
        config = VAR_CONFIG.get(var, {})
        valid_codes = config.get("valid_codes")
        labels_map = config.get("labels", {})
        code_order = config.get("order", [])

        work = df[[primary, secondary, var]].copy()
        work["answer_code"] = pd.to_numeric(work[var], errors="coerce")

        df_routing = work[work["answer_code"].isin(ROUTING_CODES) | (work["answer_code"] < 0)].copy()
        df_valid = work[work["answer_code"].notna() & (work["answer_code"] >= 0)].copy()

        if valid_codes is not None:
            df_valid = df_valid[df_valid["answer_code"].isin(valid_codes)].copy()

        routing_parts = []
        for code, label in ROUTING_LABELS.items():
            cnt = (df_routing["answer_code"] == code).sum()
            if cnt > 0:
                routing_parts.append(f"{label} ({code}): {cnt:,}")
        routing_text = "Non-response: " + " | ".join(routing_parts) if routing_parts else ""

        if df_valid.empty:
            return _empty_figure("No substantive values to plot"), pd.DataFrame(), routing_text, []

        df_valid = df_valid.dropna(subset=[primary, secondary])
        if df_valid.empty:
            return _empty_figure("No data after filtering"), pd.DataFrame(), routing_text, []

        if labels_map:
            df_valid["response"] = df_valid["answer_code"].map(lambda x: labels_map.get(int(x), str(int(x))) if pd.notna(x) else str(x))
            if code_order:
                resp_order = [labels_map.get(c, str(c)) for c in code_order if c in labels_map]
            else:
                resp_order = [labels_map.get(c, str(c)) for c in sorted(labels_map.keys())]
        else:
            uniq_codes = sorted(df_valid["answer_code"].dropna().unique())
            is_binary = set(int(x) for x in uniq_codes if pd.notna(x)) <= {0, 1}
            if is_binary:
                df_valid["response"] = df_valid["answer_code"].map({0: "No", 1: "Yes"})
                resp_order = ["No", "Yes"]
            else:
                df_valid["response"] = df_valid["answer_code"].astype(int).astype(str)
                resp_order = [str(int(c)) for c in uniq_codes]

        stack_df = df_valid.groupby([primary, secondary, "response"], dropna=False).size().reset_index(name="n")
        if stack_df.empty:
            return _empty_figure("No data after aggregation"), pd.DataFrame(), routing_text, []

        stack_df["total"] = stack_df.groupby([primary, secondary])["n"].transform("sum")
        stack_df["pct"] = np.where(stack_df["total"] > 0, 100.0 * stack_df["n"] / stack_df["total"], 0.0)
        stack_df = stack_df[stack_df["total"] > 0].copy()

        if stack_df.empty:
            return _empty_figure("No data with positive counts"), pd.DataFrame(), routing_text, []

        stack_df["unit"] = stack_df[primary].astype(str) + " > " + stack_df[secondary].astype(str)

        # --- Min-25 threshold: only when filters are active (skip_exclusion=False) ---
        _excluded_units_info = []
        if not skip_exclusion:
            unit_totals = stack_df.groupby("unit")["n"].sum()
            excluded_units = unit_totals[unit_totals < MIN_NONROUTING_N]
            if not excluded_units.empty:
                _excluded_units_info = [f"{u} (n={int(n)})" for u, n in excluded_units.items()]
                stack_df = stack_df[~stack_df["unit"].isin(excluded_units.index)].copy()
            if stack_df.empty:
                return _empty_figure(f"All combinations have fewer than {MIN_NONROUTING_N} responses"), pd.DataFrame(), routing_text, _excluded_units_info

        sort_asc = str(sort_order).strip().lower().startswith("asc")
        if resp_order:
            r0 = resp_order[0]
            sort_key = stack_df[stack_df["response"] == r0].groupby("unit")["pct"].first()
        else:
            sort_key = stack_df.groupby("unit")["n"].sum()
        unit_order = sort_key.sort_values(ascending=sort_asc).index.tolist()

        fig = go.Figure()
        color_map = {resp: _COLORS[i % len(_COLORS)] for i, resp in enumerate(resp_order)}
        pattern_map = {resp: STACK_PATTERN_SHAPES[i % len(STACK_PATTERN_SHAPES)] for i, resp in enumerate(resp_order)}

        for resp in resp_order:
            subset = stack_df[stack_df["response"] == resp].copy()
            subset = subset.set_index("unit").reindex(unit_order).reset_index()
            cdata = subset[["n", "total"]].values
            marker_kwargs = dict(color=color_map.get(resp, "#999"))
            if USE_STACK_PATTERNS and pattern_map.get(resp, ""):
                marker_kwargs["pattern_shape"] = pattern_map[resp]

            if orient == "h":
                fig.add_trace(go.Bar(
                    y=subset["unit"], x=subset["pct"], name=resp, orientation="h",
                    marker=marker_kwargs,
                    customdata=cdata,
                    width=0.9,
                    hovertemplate="<b>%{y}</b><br>" + resp + ": %{x:.1f}% (n=%{customdata[0]})<br>Total responses: %{customdata[1]}<extra></extra>",
                ))
            else:
                fig.add_trace(go.Bar(
                    x=subset["unit"], y=subset["pct"], name=resp, orientation="v",
                    marker=marker_kwargs,
                    customdata=cdata,
                    width=0.9,
                    hovertemplate="<b>%{x}</b><br>" + resp + ": %{y:.1f}% (n=%{customdata[0]})<br>Total responses: %{customdata[1]}<extra></extra>",
                ))

        title = self.label(var)
        n_units = len(unit_order)

        # Dynamic height: give each bar enough room so it matches LOCALMULTIDEM thickness
        if orient == "h":
            fig_height = max(600, 50 * n_units + 200)
        else:
            fig_height = 600

        fig.update_layout(
            barmode="stack",
            bargap=0.02,
            bargroupgap=0.00,
            template="plotly_white",
            title=dict(text=title, font=dict(size=title_font_size), x=0.5, xanchor="center"),
            legend=dict(
                orientation="h", yanchor="top", y=-0.25, xanchor="left", x=0,
                font=dict(size=10), title_text="Response",
            ),
            margin=dict(l=64, r=22, t=54, b=150),
            height=fig_height,
            autosize=True,
            font=dict(size=12),
            transition={"duration": 0},
        )

        if orient == "h":
            fig.update_xaxes(title="Share (%)", range=[0, 100], tickfont=dict(size=10))
            fig.update_yaxes(title="", categoryorder="array", categoryarray=unit_order[::-1], tickfont=dict(size=10))
        else:
            fig.update_yaxes(title="Share (%)", range=[0, 100], tickfont=dict(size=10))
            fig.update_xaxes(title="", tickangle=-25, categoryorder="array", categoryarray=unit_order, tickfont=dict(size=10))

        table_df = stack_df[[primary, secondary, "response", "n", "total", "pct"]].copy()

        return fig, table_df, routing_text, _excluded_units_info

    def _draw_box_plot(
        self,
        df: pd.DataFrame,
        var: str,
        primary: str,
        secondary: str,
        orient: str,
        sort_order: str,
        title_font_size: int,
        skip_exclusion: bool = False,
    ) -> tuple[go.Figure, pd.DataFrame, str, list[str]]:
        """Draw box plot with colors by group and spectrum labels on x-axis."""
        config = VAR_CONFIG.get(var, {})
        spectrum = config.get("spectrum", ("0", "1"))

        work = df[[primary, secondary, var]].copy()
        work["value"] = pd.to_numeric(work[var], errors="coerce")

        df_routing = work[work["value"].isin(ROUTING_CODES) | (work["value"] < 0)].copy()
        df_valid = work[work["value"].notna() & (work["value"] >= 0)].copy()

        routing_parts = []
        for code, label in ROUTING_LABELS.items():
            cnt = (df_routing["value"] == code).sum()
            if cnt > 0:
                routing_parts.append(f"{label} ({code}): {cnt:,}")
        routing_text = "Non-response: " + " | ".join(routing_parts) if routing_parts else ""

        if df_valid.empty:
            return _empty_figure("No numeric values to plot"), pd.DataFrame(), routing_text, []

        df_valid = df_valid.dropna(subset=[primary, secondary])
        if df_valid.empty:
            return _empty_figure("No data after filtering"), pd.DataFrame(), routing_text, []

        df_valid["unit"] = df_valid[primary].astype(str) + " > " + df_valid[secondary].astype(str)

        # --- Min-25 threshold: only when filters are active (skip_exclusion=False) ---
        _excluded_units_info = []
        if not skip_exclusion:
            unit_counts = df_valid.groupby("unit").size()
            excluded_units = unit_counts[unit_counts < MIN_NONROUTING_N]
            if not excluded_units.empty:
                _excluded_units_info = [f"{u} (n={int(n)})" for u, n in excluded_units.items()]
                df_valid = df_valid[~df_valid["unit"].isin(excluded_units.index)].copy()
            if df_valid.empty:
                return _empty_figure(f"All combinations have fewer than {MIN_NONROUTING_N} responses"), pd.DataFrame(), routing_text, _excluded_units_info

        sort_asc = str(sort_order).strip().lower().startswith("asc")
        medians = df_valid.groupby("unit")["value"].median().sort_values(ascending=sort_asc)
        unit_order = medians.index.tolist()

        # Get unique groups for coloring
        unique_groups = sorted(df_valid[secondary].dropna().unique())
        group_colors = {g: _COLORS[i % len(_COLORS)] for i, g in enumerate(unique_groups)}

        fig = go.Figure()

        # Pre-compute n per unit for hover display
        _unit_n = df_valid.groupby("unit").size().to_dict()

        # Add one box per unit, colored by the secondary (group)
        for unit in unit_order:
            subset = df_valid[df_valid["unit"] == unit]
            if subset.empty:
                continue
            group = subset[secondary].iloc[0]
            color = group_colors.get(group, "#999")
            n_resp = _unit_n.get(unit, len(subset))

            if orient == "h":
                fig.add_trace(go.Box(
                    x=subset["value"],
                    y=[unit] * len(subset),
                    name=str(group),
                    orientation="h",
                    marker=dict(color=color, size=3),
                    line=dict(color=color, width=1),
                    boxpoints="outliers",
                    notched=False,
                    jitter=0,
                    width=0.35,
                    legendgroup=str(group),
                    showlegend=False,
                    hovertemplate=f"<b>{unit}</b> (n={n_resp})<br>"
                                 "Value: %{x:.2f}<extra></extra>",
                ))
            else:
                fig.add_trace(go.Box(
                    y=subset["value"],
                    x=[unit] * len(subset),
                    name=str(group),
                    orientation="v",
                    marker=dict(color=color, size=3),
                    line=dict(color=color, width=1),
                    boxpoints="outliers",
                    notched=False,
                    jitter=0,
                    width=0.35,
                    legendgroup=str(group),
                    showlegend=False,
                    hovertemplate=f"<b>{unit}</b> (n={n_resp})<br>"
                                 "Value: %{y:.2f}<extra></extra>",
                ))

        # Add legend entries for each group (one invisible trace per group)
        for group in unique_groups:
            color = group_colors.get(group, "#999")
            fig.add_trace(go.Scatter(
                x=[None], y=[None],
                mode="markers",
                marker=dict(size=12, color=color, symbol="square"),
                name=str(group),
                legendgroup=str(group),
                showlegend=True,
            ))

        title = self.label(var)
        n_units = len(unit_order)

        legend_title = "City" if secondary == "city_disp" else "Group"
        fig_height = max(1200, min(12000, 60 * max(1, n_units) + 420)) if orient == "h" else 740

        fig.update_layout(
            template="plotly_white",
            title=dict(text=title, font=dict(size=title_font_size), x=0.5, xanchor="center"),
            boxgap=0.35,
            boxgroupgap=0.10,
            legend=dict(
                orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0,
                bgcolor="rgba(255,255,255,0.9)", font=dict(size=10),
                title_text=legend_title,
            ),
            margin=dict(l=70, r=40, t=120, b=260),
            height=fig_height,
            autosize=True,
            transition={"duration": 0},
        )

        if orient == "h":
            fig.update_xaxes(
                title="Value",
                tickvals=[0, 0.5, 1],
                ticktext=[spectrum[0], "", spectrum[1]],
                range=[-0.05, 1.05],
                tickfont=dict(size=10),
            )
            fig.update_yaxes(title="", categoryorder="array", categoryarray=unit_order[::-1], tickfont=dict(size=10))
        else:
            fig.update_yaxes(
                title="Value",
                tickvals=[0, 0.5, 1],
                ticktext=[spectrum[0], "", spectrum[1]],
                range=[-0.05, 1.05],
                tickfont=dict(size=10),
            )
            fig.update_xaxes(title="", tickangle=-25, categoryorder="array", categoryarray=unit_order, tickfont=dict(size=10))

        # Table for download
        summary = df_valid.groupby(["unit", primary, secondary])["value"].agg(["mean", "median", "std", "count"]).reset_index()
        summary.columns = ["unit", primary, secondary, "mean", "median", "std", "n"]

        return fig, summary, routing_text, _excluded_units_info
