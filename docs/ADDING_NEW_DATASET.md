# Adding Your Own Survey Dataset

This guide explains how to add a new survey dataset to the Data Playground. The application uses an **adapter pattern** — each survey gets its own Python module, so you can add new data without modifying the core application.

---

## What You Need

1. **A responses file** (CSV or TSV) — one row per respondent, one column per survey question
2. **A codebook file** (CSV) — one row per variable, with columns for variable name, theme, subtheme, and label
3. **Column mappings** — which columns in your data represent city, group, gender, year of birth, etc.

---

## Step 1: Prepare Your Data Files

Place your data files in your `DATA_DIR` directory (the folder you set via the `DATA_DIR` environment variable).

**Naming convention:** `{surveyname}_{content}.{ext}`

| File | Purpose | Example |
|------|---------|---------|
| `mysurvey_responses.csv` | Main data (one row per respondent) | Like `civic_responses.csv` |
| `mysurvey_codebook.csv` | Variable descriptions | Like `civic_codebook.csv` |

---

## Step 2: Create a Survey Adapter

Create a new file in the `app/` directory, e.g., `app/survey_mysurvey.py`. Use `survey_civic.py` as a template.

Your adapter must implement these methods:

```python
from dataclasses import dataclass
import pandas as pd

@dataclass
class MySurveyAdapter:
    raw: pd.DataFrame           # The loaded survey data
    codebook: pd.DataFrame      # Variable metadata
    dict_labels: dict           # {variable_name: human_label}
    allowed_vars: set           # Variables to show in the UI

    def theme_options(self) -> list[dict]:
        """Return dropdown options for themes.
        Each item: {"label": "Theme Name", "value": "theme_name"}
        """
        ...

    def subtheme_options(self, theme: str) -> list[dict]:
        """Return dropdown options for subthemes within a theme."""
        ...

    def variable_options(self, theme: str, subtheme: str) -> list[dict]:
        """Return dropdown options for variables within a subtheme."""
        ...

    def label(self, var: str) -> str:
        """Return human-readable label for a variable name."""
        return self.dict_labels.get(var, var)

    def draw(self, var, cities, groups, orient, sort_order, title_font_size,
             yob_rng=None, genders=None, born_here=None, skip_exclusion=False):
        """
        Main method: generate a chart + data table for the given variable.

        Parameters:
            var: variable name (column in the data)
            cities: list of selected city codes
            groups: list of selected group codes
            orient: "h" (horizontal) or "v" (vertical) bars
            sort_order: how to sort the bars
            title_font_size: font size for chart title
            yob_rng: year of birth range [min, max] or None
            genders: list of selected gender codes or None
            born_here: filter for born-in-country or None
            skip_exclusion: if True, skip the min-25 exclusion check

        Returns: (fig, table_df, routing_text, excluded_units_info)
            fig: Plotly Figure object
            table_df: pandas DataFrame for the data table
            routing_text: string describing routing/missing codes
            excluded_units_info: list of excluded city x group combinations
        """
        ...
```

### Key Things Your Adapter Must Handle

**1. Column mapping** — Map your column names to the concepts the app needs:

```python
COL_CITY = "location_code"      # or "city", "lau_1", etc.
COL_GROUP = "ethnicity"          # or "group", "rgroup", etc.
COL_GENDER = "sex"               # or "gender", "rgender", etc.
COL_BIRTH_YEAR = "birth_year"    # or "ryrbrn", "q2", etc.
```

**2. City/group name mapping** — Convert numeric codes to display names:

```python
CITY_MAPPING = {1: "Amsterdam", 2: "Brussels", 3: "Lyon"}
GROUP_MAPPING = {1: "Turkish", 2: "Moroccan", 3: "Italian"}
```

**3. Routing/missing codes** — Define which values mean "not applicable":

```python
ROUTING_CODES = {-995, -996, -997, -998, -999}
```

**4. Variable configuration** — Define each variable's chart type and valid codes:

```python
VAR_CONFIG = {
    "ridentity": {
        "type": "bar chart",           # or "box plot", "bar chart yes no"
        "codes": {0, 1, 2, 3, 4},      # valid response codes
        "labels": {0: "Not at all", 1: "Not very", 2: "Somewhat",
                   3: "Fairly", 4: "Very strongly"},
    },
}
```

**5. Minimum sample size** — Exclude subgroups with too few responses:

```python
MIN_NONROUTING_N = 25  # minimum responses to show a city x group combination
```

---

## Step 3: Register the Adapter

In `app/app_main.py`, add the import at the top:

```python
from survey_mysurvey import MySurveyAdapter
```

Then add to the `init_adapters()` function:

```python
# --- My Survey ---
MY_CSV_PATH = DATA_DIR / "mysurvey_responses.csv"
MY_CODEBOOK_PATH = DATA_DIR / "mysurvey_codebook.csv"

if MY_CSV_PATH.exists():
    my_df = pd.read_csv(MY_CSV_PATH, sep=";", encoding="latin-1", low_memory=False)
    my_codebook = pd.read_csv(MY_CODEBOOK_PATH, sep=";")
    my_adapter = MySurveyAdapter(raw=my_df, codebook=my_codebook, ...)
    SURVEYS_REGISTRY["mysurvey"] = my_adapter
    print("[init_adapters] My survey adapter initialized")
```

---

## Step 4: Add a Tab in the UI

In `app/app_main.py`, find the tab layout (search for `dbc.Tab`) and add:

```python
dbc.Tab(label="My Survey Name", tab_id="mysurvey"),
```

---

## Step 5: Test

```bash
export DATA_DIR=~/my-survey-data
python app/app_main.py
```

Open http://127.0.0.1:8050 and verify:
- The new tab appears
- Themes, subthemes, and variables load in the dropdowns
- Charts display correctly
- Filters work as expected
- Small subgroups show exclusion warnings

---

## Codebook File Format

Your codebook CSV should have these columns:

```csv
variable;theme;subtheme;label
ridentity;Identity;National Identity;How strongly do you identify with [country]?
rinterest;Political Engagement;Political Interest;How interested are you in politics?
```

| Column | Required | Description |
|--------|----------|-------------|
| `variable` | Yes | Variable name (must match a column in the responses file) |
| `theme` | Yes | Top-level grouping for the dropdown |
| `subtheme` | Yes | Second-level grouping |
| `label` | Yes | Human-readable description of the variable |

---

## Tips

- **Encoding:** European survey data often uses `latin-1` or `windows-1252` encoding, not UTF-8. Specify the correct encoding when loading with `pd.read_csv()`.
- **Separators:** Check whether your CSV uses commas (`,`), semicolons (`;`), or tabs as delimiters.
- **Large datasets:** If your dataset is very large (>100 MB), consider pre-calculating aggregations and storing them as a separate CSV to improve performance.
- **Chart colors:** The existing adapters use the Okabe-Ito color palette for accessibility. You can reuse it or define your own.

---

## Checklist

- [ ] Data file placed in DATA_DIR with clear naming
- [ ] Codebook file prepared
- [ ] Adapter Python file created in `app/`
- [ ] Adapter implements: `theme_options()`, `subtheme_options()`, `variable_options()`, `label()`, `draw()`
- [ ] Adapter registered in `app_main.py` → `init_adapters()` → `SURVEYS_REGISTRY`
- [ ] New tab added to the Dash layout
- [ ] Tested locally — charts load, filters work, exclusion warnings appear
