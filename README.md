# Internship Scraper & Form Autofill Suite

A high-precision internship scraper, categorizer, and multi-ATS form autofiller designed for Computer Engineering students. The tool indexes live postings (including GitHub repositories like SimplifyJobs), classifies positions into hardware and software tracks, and automates application form filling with resume attachment.

---

## Key Features

- **Multi-ATS Form Autofill Engine**:
  - Dedicated automation for **Workday**, **Greenhouse**, **Lever**, **Ashby**, **SmartRecruiters**, and **Tesla**.
  - Universal heuristic fuzzy-matching for arbitrary application forms.
  - Multi-frame (`<iframe>`) traversal for embedded job boards.
  - Multi-strategy resume uploader (file inputs, hidden fields, and file-chooser dropzones).
  - Visual in-browser HUD badge indicating field counts and highlighting populated fields in green.

- **GitHub Repository & Markdown Parsing**:
  - Ingests internship repositories directly from GitHub URLs (e.g. `https://github.com/SimplifyJobs/Summer2027-Internships`).
  - Automatically parses markdown tables and structured JSON listings.

- **Intelligent Track Categorization**:
  - **Hardware / Chip Design** (`chip_design`): ASIC, FPGA, VLSI, Silicon, Verification, Embedded Systems, Microarchitecture.
  - **Software Development** (`software_dev`): SWE, Backend, Full Stack, Systems Engineering.
  - **AI / Machine Learning** (`ai_ml`): Deep Learning, Computer Vision, NLP, Data Science.

- **Continuous Fast Link Feeder**:
  - Interactive loop to paste application links or GitHub repos continuously without restarting the script.
  - Automatic status tracking (`NEW`, `APPLIED`, `SKIPPED`) in a local SQLite database (`data/applications.db`).

- **Minimal CLI**:
  - Clean text output with standard status tags (`[OK]`, `[WARN]`, `[ERROR]`, `>>`) and zero emoji clutter.

---

## Project Structure

```text
├── main.py                  # Interactive CLI entry point and menu system
├── autofill.py              # Playwright multi-ATS automation & continuous link feeder
├── scraper.py               # Feed sync, GitHub parser, and job classification engine
├── test_system.py           # Automated unit test suite (10 test cases)
├── requirements.txt         # Core Python dependencies
├── config/
│   ├── profile.json         # Applicant personal info, education, links, and demographics
│   └── profile_loader.py    # Profile schema validation and data flattener
└── data/
    ├── db.py                # SQLite database interface
    ├── applications.db      # Indexed internship jobs and tracking history
    └── [Your_Resume].pdf    # PDF resume for automatic attachment
```

---

## Installation & Setup

1. **Clone Repository**:
   ```bash
   git clone https://github.com/solo6760/internship_scraper.git
   cd internship_scraper
   ```

2. **Create and Activate Virtual Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

4. **Configure Profile & Resume**:
   - Edit `config/profile.json` with your personal details, education, portfolio links, and demographic answers.
   - Place your resume PDF in `data/` or specify an absolute path in `config/profile.json`.

---

## Usage

### 1. Fast Link Feeder Mode (Continuous Autofill)
Launch the continuous link feeder to paste job URLs or GitHub repos one after another:
```bash
.venv/bin/python3 main.py --feed
```
You can also feed one or more URLs directly via the CLI:
```bash
.venv/bin/python3 autofill.py https://boards.greenhouse.io/example/jobs/12345
```

### 2. Parse & Preview Mode (Read Back Postings Without Launching Browser)
Read back a short list preview of positions from direct links or a GitHub repo:
```bash
# Launch interactive parse mode:
.venv/bin/python3 main.py --parse

# Or parse a GitHub repository directly:
.venv/bin/python3 main.py --parse https://github.com/SimplifyJobs/Summer2027-Internships

# Or via autofill.py:
.venv/bin/python3 autofill.py --parse https://github.com/SimplifyJobs/Summer2027-Internships
```
Inside the interactive feeder loop, you can also toggle Parse Mode anytime simply by typing `parse`.

### 2. Ingest a GitHub Repository
Scrape and index internship listings directly from a GitHub repository:
```bash
.venv/bin/python3 scraper.py --github https://github.com/SimplifyJobs/Summer2027-Internships
```

### 3. Interactive CLI Dashboard
Run the main menu to browse, filter by track (Hardware vs SWE vs AI/ML), export link lists, or view application statistics:
```bash
.venv/bin/python3 main.py
```

### 4. Export Internship Links to Text File
Export filtered listings (e.g. Hardware roles for Summer 2027):
```bash
.venv/bin/python3 scraper.py --category chip_design --term "Summer 2027" --export hardware_links.txt
```

---

## Testing

Run the built-in automated test suite to verify configuration loading, database integrity, ATS rules, and headless form autofill:
```bash
.venv/bin/python3 test_system.py
```

---

## Configuration Reference (`config/profile.json`)

```json
{
  "personal": {
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane.doe@example.com",
    "phone": "5551234567",
    "address": {
      "street": "123 Main St",
      "city": "City",
      "state": "CA",
      "zip_code": "90001",
      "country": "United States"
    }
  },
  "education": {
    "university": "Your University",
    "degree": "Bachelor of Science",
    "major": "Computer Engineering",
    "gpa": "3.80",
    "graduation_date_formatted": "05/2026"
  },
  "demographics": {
    "gender": "Male",
    "race_ethnicity": "Asian",
    "veteran_status": "No",
    "disability_status": "No",
    "authorized_to_work_in_us": "Yes",
    "requires_sponsorship": "No",
    "is_18_or_older": "Yes",
    "previously_employed": "No"
  }
}
```
