# EMM Survey Data Playground

An open-source interactive web application for exploring survey data through charts, filters, and data tables. Built with Python Dash and Plotly.

**Live demo:** https://dataplayground.ethmigsurveydatahub.eu

---

## What It Does

The Data Playground provides an interactive dashboard for exploring survey datasets. Users can:

- Browse variables organized by **theme** and **subtheme**
- Filter respondents by city, ethnic group, gender, year of birth, and more
- View **stacked bar charts**, **box plots**, and **data tables**
- Download filtered data as **CSV**
- See sample-size warnings when subgroups have fewer than 25 responses

The application uses an **adapter pattern** — each survey dataset gets its own Python module. This makes it easy to add new datasets without modifying the core application.

---

## Screenshots

The application displays survey data as interactive stacked bar charts grouped by city and ethnic group:

<!-- Add screenshots here if desired -->

---

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/OPENMIN-project/EMM-Data-Playground.git
cd EMM-Data-Playground
```

### 2. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate        # Mac/Linux
# venv\Scripts\activate          # Windows

pip install -r requirements.txt
```

### 3. Prepare Your Data

The application expects data files in a directory you specify via the `DATA_DIR` environment variable. Data files are **not included** in this repository.

Create a data directory and place your files there:

```bash
mkdir ~/my-survey-data
```

See [Data File Format](#data-file-format) below for the expected file structure.

### 4. Run the Application

```bash
export DATA_DIR=~/my-survey-data
python app/app_main.py
```

Opens at **http://127.0.0.1:8050**

### 5. Run in Production (Optional)

```bash
export DATA_DIR=~/my-survey-data
gunicorn app.app_main:server -b 0.0.0.0:8000 -w 2
```

---

## Project Structure

```
EMM-Data-Playground/
├── README.md                      # This file
├── requirements.txt               # Python dependencies
├── app/
│   ├── app_main.py                # Main Dash application (entry point)
│   ├── survey_civic.py            # Civic & Political Integration adapter
│   ├── survey_localmultidem.py    # LOCALMULTIDEM adapter
│   ├── codebook_parser.py         # Codebook CSV parser
│   └── assets/
│       ├── brand.css              # Visual styling
│       └── ETHMIG_logo_cmyk.png   # Project logo
├── data/                          # Data files go here (not committed)
│   └── .gitkeep
└── docs/
    └── ADDING_NEW_DATASET.md      # Guide for adding your own survey
```

---

## Architecture

The application follows an **adapter pattern**. Each survey dataset has its own adapter module that handles dataset-specific logic (column names, coding schemes, chart types). The main application coordinates everything through a registry:

```
app_main.py
  ├── imports LocalMultiAdapter   from survey_localmultidem.py
  ├── imports CivicPolAdapter     from survey_civic.py
  └── imports load_civic_codebook from codebook_parser.py

At startup → init_adapters():
  ├── Survey A data → AdapterA → SURVEYS_REGISTRY["survey_a"]
  └── Survey B data → AdapterB → SURVEYS_REGISTRY["survey_b"]

At runtime → user selects survey tab:
  adapter = SURVEYS_REGISTRY[survey_key]
  fig, table = adapter.draw(variable, cities, groups, filters...)
```

Each adapter implements:
- `theme_options()` — dropdown options for themes
- `subtheme_options(theme)` — dropdown options for subthemes
- `variable_options(theme, subtheme)` — dropdown options for variables
- `label(var)` — human-readable label for a variable
- `draw(var, cities, groups, ...)` — generate chart + data table

---

## Data File Format

The application expects survey data as CSV or TSV files. Each survey needs at minimum:

### Responses File (one row per respondent)

| Column | Description | Example |
|--------|-------------|---------|
| City identifier | Numeric code or name for the city | `1`, `2`, `3` or `"Lyon"`, `"London"` |
| Group identifier | Numeric code or name for the ethnic/social group | `1`, `2` or `"Turkish"`, `"Moroccan"` |
| Gender | Numeric code | `1` (male), `2` (female) |
| Year of birth | 4-digit year | `1965`, `1980` |
| Survey variables | One column per question, numeric coded responses | `1`, `2`, `3`, `4`, `5` |

### Codebook File (one row per variable)

| Column | Description | Example |
|--------|-------------|---------|
| `variable` | Variable name (matches column in responses) | `ridentity` |
| `theme` | Thematic grouping | `Identity` |
| `subtheme` | Sub-grouping within theme | `National Identity` |
| `label` | Human-readable description | `How strongly do you identify with [country]?` |

### Routing/Missing Codes

Survey data often uses special codes for missing or not-applicable responses. Define these in your adapter:

```python
ROUTING_CODES = {-995, -996, -997, -998, -999}
# -995 = not asked, -996 = not applicable, -997 = refused, etc.
```

The application automatically excludes routing codes from charts.

---

## Adding Your Own Survey Dataset

The adapter pattern makes it straightforward to add new datasets. See [docs/ADDING_NEW_DATASET.md](docs/ADDING_NEW_DATASET.md) for a step-by-step guide covering:

- How to create an adapter module
- Required methods and their signatures
- Column mapping and city/group name translation
- Chart type configuration
- Registering the adapter in the main application

---

## Technology Stack

| Technology | Role |
|-----------|------|
| **Dash** | Web framework (interactive dashboard) |
| **Plotly** | Charting (bar charts, box plots) |
| **Pandas** | Data analysis (CSV reading, filtering, grouping) |
| **Dash Bootstrap Components** | Responsive layout and styling |
| **Gunicorn** | Production WSGI server |

---

## Configuration

The application uses environment variables for configuration:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATA_DIR` | `~/dataplayground-data` | Directory containing data files |
| `MEDIAN_CSV` | `(inside DATA_DIR)` | Path to pre-calculated medians (if applicable) |

---

## Contributing

Contributions are welcome. To add a new survey dataset:

1. Fork this repository
2. Create your adapter module (see [Adding Your Own Survey](docs/ADDING_NEW_DATASET.md))
3. Test locally with your data
4. Submit a pull request

---

## License

This project is part of the **ETHMIG Survey Data Hub** — a platform for harmonized survey data on immigrant integration in Europe.

<!-- Specify your license here, e.g.: -->
<!-- MIT License — see [LICENSE](LICENSE) for details -->

---

## Citation

If you use this software in your research, please cite:

```
ETHMIG Survey Data Hub — Data Playground
https://dataplayground.ethmigsurveydatahub.eu
```
