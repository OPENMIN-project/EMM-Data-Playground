# survey_localmultidem.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd


def _sentence_case(s: str) -> str:
    """Lowercase then capitalize first letter only (no Title Case)."""
    s = str(s or "").strip().lower()
    return s[:1].upper() + s[1:] if s else s


@dataclass
class LocalMultiAdapter:
    """Adapter for LOCALMULTIDEM.

    This adapter does NOT re-implement plotting; it delegates to functions already defined
    in typeserver.py (build_stack, build_yes, build_mean_chart, apply_filters, etc.) via
    injected callables.

    The goal: typeserver.py becomes survey-agnostic, and all LOCALMULTIDEM-specific
    assumptions stay here.
    """

    # Core data + metadata
    raw: pd.DataFrame
    var_meta: pd.DataFrame  # columns: theme, subtheme, variable
    dict_labels: dict[str, str]  # var -> label
    var_type_map: dict[str, Any]  # var -> type code
    allowed_vars: set[str]  # normalized allowed varnames, e.g. _norm_varname(v)

    # Helpers injected from typeserver.py
    norm_varname: Callable[[str], str]
    sentence_case: Callable[[str], str]

    # Filtering + question/routing helpers
    apply_filters: Callable[..., pd.DataFrame]
    find_questions_for_var: Callable[[str], list[tuple[str, str]]]
    routing_line_for_var: Callable[[str], str]
    country_line_for_var: Callable[[str], str]
    nonresponse_counts_labeled: Callable[[pd.DataFrame, str], dict[str, int]]
    count_special_codes: Callable[[pd.DataFrame, str], dict[str, int]]

    # Plot builders injected from typeserver.py
    build_stack: Callable[..., Any]
    build_yes: Callable[..., Any]
    build_mean_chart: Callable[..., Any]
    multi_share_generic: Callable[..., Any]
    yes_share_for_var: Callable[..., Any]

    # Numeric/scale detection from your existing code
    is_numeric_var: Callable[[str], bool]
    is_binary_var: Callable[[str], bool]
    is_numeric_scale_from_labels: Callable[[str], bool]

    TITLE_FONT_SIZE: int = 18

    # ---------------------------
    # Dropdown option providers
    # ---------------------------

    def theme_options(self) -> list[dict]:
        df = self.var_meta
        if df is None or df.empty or "theme" not in df.columns:
            return []
        themes = (
            df["theme"].astype(str).str.strip()
            .loc[lambda s: s.ne("")]
            .drop_duplicates()
            .tolist()
        )
        themes = sorted(themes)
        return [{"label": t, "value": t} for t in themes]

    def subtheme_options(self, theme: str | None) -> list[dict]:
        df = self.var_meta
        if df is None or df.empty or "subtheme" not in df.columns:
            return []
        t = str(theme or "").strip()
        if t:
            df = df[df["theme"].astype(str).str.strip() == t]
        subs = (
            df["subtheme"].astype(str).str.strip()
            .loc[lambda s: s.ne("")]
            .drop_duplicates()
            .tolist()
        )
        subs = sorted(subs)
        return [{"label": s, "value": s} for s in subs]

    def variable_options(self, theme: str | None, subtheme: str | None) -> list[dict]:
        """UI requirement: show ONLY the variable label (sentence case), value remains var code."""
        df = self.var_meta
        if df is None or df.empty or "variable" not in df.columns:
            return []

        t = str(theme or "").strip()
        st = str(subtheme or "").strip()
        if t:
            df = df[df["theme"].astype(str).str.strip() == t]
        if st:
            df = df[df["subtheme"].astype(str).str.strip() == st]

        vars_ = (
            df["variable"].astype(str).str.strip().str.lower()
            .drop_duplicates()
            .tolist()
        )

        opts: list[dict] = []
        for v in vars_:
            if not v:
                continue

            lab = ""
            try:
                lab = str(self.dict_labels.get(v, "")).strip()
            except Exception:
                lab = ""

            # prefer injected sentence_case if provided; fall back to local helper
            _sc = self.sentence_case if callable(self.sentence_case) else _sentence_case
            label_txt = _sc(lab) if lab else v
            opts.append({"label": label_txt, "value": v})

        return opts

    # ---------------------------
    # Metadata getters
    # ---------------------------

    def label(self, var: str) -> str:
        v = str(var or "").strip().lower()
        lab = str(self.dict_labels.get(v, "")).strip()
        # Use injected sentence_case for UI friendliness
        if lab:
            _sc = self.sentence_case if callable(self.sentence_case) else _sentence_case
            return _sc(lab)
        return str(var).strip()

    def description(self, var: str) -> str:
        # LOCALMULTIDEM uses questionnaire mapping; description not used the same way
        return ""

    # ---------------------------
    # Survey-specific filtering
    # ---------------------------

    def filter_df(
        self,
        *,
        yob_rng=None,
        yoa_rng=None,
        yc_rng=None,
        yc_life=None,
        reason_vals=None,
        alone_sel=None,
        legal_vals=None,
        genders=None,
        born_here_sel=None,
    ) -> pd.DataFrame:
        return self.apply_filters(
            self.raw,
            yob_rng=yob_rng,
            yoa_rng=yoa_rng,
            yc_rng=yc_rng,
            yc_life=yc_life or [],
            reason_vals=reason_vals,
            alone_sel=alone_sel,
            legal_vals=legal_vals,
            genders=genders,
            born_here_sel=born_here_sel,
        )

    # ---------------------------
    # MAIN: draw a figure + meta blocks
    # ---------------------------

    def draw(
        self,
        *,
        var: str | None,
        axis: str,
        orient: str,
        sort_order: str,
        sep: bool,
        # filters (LOCALMULTIDEM only)
        yob_rng=None,
        yoa_rng=None,
        yc_rng=None,
        yc_life=None,
        reason_vals=None,
        alone_sel=None,
        legal_vals=None,
        genders=None,
        born_here=None,
        # group/city selections
        cities_full=None,
        groups=None,
        # mode & type (from your existing store)
        vtype: Any = None,
        vmode: str | None = None,
        # misc
        title_font_size: int | None = None,
        include_autoch: bool = True,
        **_ignored,
    ) -> dict:
        """Return dict with keys: fig, question_block, routing_text, footer_text, table_df."""

        v = str(var or "").strip().lower()
        if not v:
            return {"fig": None, "question_block": [], "routing_text": "", "footer_text": "", "table_df": pd.DataFrame()}

        # Gatekeeper: allowed vars
        if (v not in self.raw.columns) or (self.norm_varname(v) not in self.allowed_vars):
            return {"fig": None, "question_block": [], "routing_text": "", "footer_text": "", "table_df": pd.DataFrame()}

        # Force horizontal if the server removed orientation UI
        orient = "h" if orient not in {"h", "v"} else orient

        sort_asc = str(sort_order).lower() == "asc"
        title_fs = int(title_font_size or self.TITLE_FONT_SIZE)

        df_use = self.filter_df(
            yob_rng=yob_rng,
            yoa_rng=yoa_rng,
            yc_rng=yc_rng,
            yc_life=yc_life,
            reason_vals=reason_vals,
            alone_sel=alone_sel,
            legal_vals=legal_vals,
            genders=genders,
            born_here_sel=born_here,
        )

        if df_use.empty:
            df_use = self.raw.copy()

        # figure/table selection
        vtype_int = int(vtype) if (isinstance(vtype, (int, float)) or (isinstance(vtype, str) and str(vtype).isdigit())) else -1
        mode = (vmode or ("yes" if vtype_int in (1, 2) else "stack"))

        primary_key = "group_disp" if str(axis).lower() == "group" else "city_full"
        secondary_key = "city_full" if str(axis).lower() == "group" else "group_disp"
        x_key = primary_key

        table_df = pd.DataFrame()
        fig = None

        # numeric scale detection
        if self.is_numeric_scale_from_labels(v) or self.is_numeric_var(v) or vtype_int == 4:
            fig, table_df = self.build_mean_chart(
                df=df_use,
                var=v,
                primary_key=primary_key,
                secondary_key=secondary_key,
                orient=orient,
                sep=sep,
                sort_asc=sort_asc,
            )

        elif (vtype_int in (1, 2)) and self.is_binary_var(v) and (mode == "yes"):
            by = [x_key, "group_disp"]
            table_df = self.yes_share_for_var(df_use, v, by).reset_index(drop=True)
            fig = self.build_yes(
                df=df_use,
                var=v,
                colour_key="group_disp",
                x_key=x_key,
                orient=orient,
                city_codes=None,
                groups=groups,
                genders=genders,
                sort_asc=sort_asc,
                include_autochthonous=include_autoch,
                sep=sep,
            )

        else:
            g, _resp_order = self.multi_share_generic(df_use, v, by=[primary_key, secondary_key])
            table_df = g.copy()
            fig = self.build_stack(
                df=df_use,
                var=v,
                x_key=("group_disp" if str(axis).lower() == "group" else "city_full"),
                orient=orient,
                city_codes=None,
                groups=groups,
                genders=genders,
                include_autochthonous=include_autoch,
                sep=sep,
                sort_asc=sort_asc,
            )

        # title
        if fig is not None:
            fig.update_layout(
                title={"text": self.label(v), "x": 0.5, "xanchor": "center"},
                title_font_size=title_fs,
            )

        # question block + routing + footer
        qrows = self.find_questions_for_var(v)
        routing_text = self.routing_line_for_var(v) or ""

        # footer: nonresponse + special codes + country line
        try:
            nn = self.nonresponse_counts_labeled(df_use, v)
            specials = self.count_special_codes(df_use, v)
        except Exception:
            nn, specials = {}, {}

        try:
            country_line = self.country_line_for_var(v) or ""
        except Exception:
            country_line = ""

        question_text = (self.dict_labels.get(v, "") or "").strip()
        _sc = self.sentence_case if callable(self.sentence_case) else _sentence_case
        question_text = _sc(question_text) if question_text else ""

        meta_parts: list[str] = []
        if question_text:
            meta_parts.append(f"Question (codebook): {question_text}")
        if country_line:
            meta_parts.append(country_line)
        meta_block = "  \n".join(meta_parts)

        footer_bits: list[str] = []
        if nn:
            footer_bits.append(" | ".join(f"{k}: {v}" for k, v in nn.items()))
        if specials:
            footer_bits.append(" · ".join(f"{k}: {v}" for k, v in specials.items()))

        footer_text = (
            (meta_block + ("  \n" if meta_block else ""))
            + ("Negative/Non-response — " + " | ".join(footer_bits) if footer_bits else "")
        ).strip()

        return {
            "fig": fig,
            "question_block": qrows,
            "routing_text": routing_text,
            "footer_text": footer_text,
            "table_df": table_df if isinstance(table_df, pd.DataFrame) else pd.DataFrame(),
        }