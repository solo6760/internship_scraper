import os
import sys
import argparse
import json
import re
import urllib.request
import urllib.parse
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from data.db import JobDatabase

# Categorization rules with priority keywords
CATEGORIES = {
    "chip_design": {
        "name": "Chip Design / Hardware / Embedded",
        "keywords": [
            "asic", "fpga", "rtl", "vlsi", "silicon", "hardware", "chip", "chips",
            "firmware", "embedded", "digital design", "systemverilog", "verilog",
            "soc", "microarchitecture", "computer architecture", "pcb", "semiconductor",
            "cadence", "synopsys", "physical design", "analog", "rfic", "eda", "circuits",
            "dsp", "logic design", "fpga engineer", "silicon design", "emulation",
            "hardware engineer", "hardware design", "validation intern", "design verification"
        ],
        "exclude": ["sales", "recruiter", "account", "human resources", "marketing", "attorney"]
    },
    "ai_ml": {
        "name": "Machine Learning / AI / Data Science",
        "keywords": [
            "machine learning", "deep learning", "computer vision", "nlp",
            "natural language", "llm", "large language", "neural", "reinforcement learning",
            "applied scientist", "ai engineer", "ai intern", "ml engineer", "ml intern",
            "data science", "pytorch", "generative ai", "artificial intelligence", "data engineering",
            "autonomous", "perception", "robotics"
        ],
        "exclude": ["sales", "recruiter", "account", "marketing"]
    },
    "software_dev": {
        "name": "Software Development / Systems / Core",
        "keywords": [
            "software", "swe", "sde", "backend", "frontend", "full stack", "fullstack",
            "systems", "infrastructure", "developer", "distributed", "platform",
            "compiler", "kernel", "linux", "c++", "python", "cloud", "security",
            "devops", "sre", "reliability", "mobile", "ios", "android", "web"
        ],
        "exclude": ["sales", "recruiter", "account", "marketing"]
    }
}

FEED_URLS = [
    {
        "name": "Simplify Summer 2027 Tech Internships Feed",
        "url": "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json",
        "type": "json"
    },
    {
        "name": "Simplify Summer 2026/2027 Internships Feed",
        "url": "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
        "type": "json"
    },
    {
        "name": "Simplify Summer 2025/2026 Internships Feed",
        "url": "https://raw.githubusercontent.com/SimplifyJobs/Summer2025-Internships/dev/.github/scripts/listings.json",
        "type": "json"
    }
]

NON_INTERN_KEYWORDS = [
    "technician", "assembler", "operator", "senior ", "lead ",
    "principal ", "staff ", "director", "manager", "vp ", "vice president"
]

def detect_ats(url: str) -> str:
    """Detect Applicant Tracking System from job URL."""
    url_lower = url.lower()
    if "greenhouse.io" in url_lower or "gh_jid" in url_lower:
        return "greenhouse"
    elif "lever.co" in url_lower:
        return "lever"
    elif "ashbyhq.com" in url_lower:
        return "ashby"
    elif "myworkdayjobs.com" in url_lower or "workday" in url_lower:
        return "workday"
    elif "icims" in url_lower:
        return "icims"
    elif "smartrecruiters.com" in url_lower:
        return "smartrecruiters"
    elif "taleo.net" in url_lower:
        return "taleo"
    return "generic"

def is_valid_internship(title: str, terms: List[str]) -> bool:
    """Strictly verify that the role is an internship/co-op and not a technician/full-time role."""
    title_lower = title.lower()
    terms_lower = [t.lower() for t in terms]

    has_intern_kw = any(k in title_lower for k in ["intern", "co-op", "coop", "fellow", "student", "apprentice"])
    terms_has_intern = any("intern" in t or "co-op" in t or "summer" in t or "spring" in t or "fall" in t or "winter" in t for t in terms_lower)

    if not (has_intern_kw or terms_has_intern):
        return False

    # Exclude non-intern technician/senior roles unless 'intern' is explicitly in the title
    if any(k in title_lower for k in NON_INTERN_KEYWORDS) and "intern" not in title_lower:
        return False

    return True

def classify_job(title: str, category_field: str = "") -> Dict[str, Any]:
    """Classify job into computer engineering categories."""
    title_lower = title.lower()
    cat_lower = category_field.lower()
    search_text = f"{title_lower} {cat_lower}"

    matched_categories = []
    
    for cat_key, cat_data in CATEGORIES.items():
        if any(exc in search_text for exc in cat_data["exclude"]):
            continue
        for kw in cat_data["keywords"]:
            pattern = rf"\b{re.escape(kw)}\b"
            if re.search(pattern, search_text):
                matched_categories.append(cat_key)
                break

    primary_cat = matched_categories[0] if matched_categories else "other"
    return {
        "primary": primary_cat,
        "all_matches": matched_categories
    }

class InternshipScraper:
    def __init__(self, db: Optional[JobDatabase] = None):
        self.db = db or JobDatabase()

    def fetch_feed_text(self, url: str) -> str:
        """Download raw text content from URL."""
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read().decode("utf-8")
        except Exception as e:
            return ""

    def fetch_feed_json(self, url: str) -> List[Dict[str, Any]]:
        """Download and parse JSON feed from URL."""
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                content = response.read().decode("utf-8")
                return json.loads(content)
        except Exception as e:
            return []

    def parse_github_url(self, github_url: str) -> Dict[str, str]:
        """Parse GitHub repo URL into owner, repo, branch, path."""
        cleaned = github_url.strip()
        if cleaned.endswith(".git"):
            cleaned = cleaned[:-4]

        # raw.githubusercontent.com/owner/repo/branch/path
        m_raw = re.match(r"https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)(?:/(.*))?", cleaned, re.I)
        if m_raw:
            return {"owner": m_raw.group(1), "repo": m_raw.group(2), "branch": m_raw.group(3), "path": m_raw.group(4) or "README.md"}

        # github.com/owner/repo/blob|tree/branch/path
        m_blob = re.match(r"https?://github\.com/([^/]+)/([^/]+)/(?:blob|tree)/([^/]+)(?:/(.*))?", cleaned, re.I)
        if m_blob:
            return {"owner": m_blob.group(1), "repo": m_blob.group(2), "branch": m_blob.group(3), "path": m_blob.group(4) or "README.md"}

        # github.com/owner/repo
        m_repo = re.match(r"https?://github\.com/([^/]+)/([^/]+)/?", cleaned, re.I)
        if m_repo:
            return {"owner": m_repo.group(1), "repo": m_repo.group(2), "branch": "", "path": "README.md"}

        return {"owner": "", "repo": "", "branch": "", "path": ""}

    def scrape_github_repo(self, github_url: str) -> List[Dict[str, Any]]:
        """
        Scrape internship postings from any GitHub repository or Markdown file.
        Supports both structured JSON (Simplify/PittCSC) and raw Markdown/HTML tables.
        """
        info = self.parse_github_url(github_url)
        if not info["owner"] or not info["repo"]:
            print(f"[!] Invalid GitHub URL provided: {github_url}")
            return []

        owner, repo = info["owner"], info["repo"]
        branches = [info["branch"]] if info["branch"] else ["dev", "main", "master"]

        print(f"[*] Analyzing GitHub repository: [bold cyan]{owner}/{repo}[/bold cyan]...")

        # Strategy 1: Check for structured listings.json in repo
        for branch in branches:
            json_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/.github/scripts/listings.json"
            raw_data = self.fetch_feed_json(json_url)
            if not raw_data:
                json_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/listings.json"
                raw_data = self.fetch_feed_json(json_url)

            if raw_data and isinstance(raw_data, list) and len(raw_data) > 0:
                print(f"[OK] Found structured listings ({len(raw_data)} entries) in branch '{branch}'!")
                jobs = []
                seen_urls = set()
                for item in raw_data:
                    if item.get("active") is False or item.get("is_visible") is False:
                        continue
                    url = item.get("url") or item.get("application_url") or item.get("link")
                    if not url or url in seen_urls:
                        continue

                    title = item.get("title") or item.get("role") or "Intern"
                    terms = item.get("terms", ["Summer 2027"])
                    terms_list = terms if isinstance(terms, list) else [str(terms)]
                    if not is_valid_internship(title, terms_list):
                        continue

                    cat_meta = item.get("category", "")
                    classification = classify_job(title, cat_meta)
                    # Detect hardware / chip design from Simplify category if present
                    if "hardware" in cat_meta.lower():
                        classification["primary"] = "chip_design"
                    elif "software" in cat_meta.lower() and classification["primary"] == "other":
                        classification["primary"] = "software_dev"
                    elif ("ai" in cat_meta.lower() or "data" in cat_meta.lower()) and classification["primary"] == "other":
                        classification["primary"] = "ai_ml"

                    locs = item.get("locations", [])
                    loc_str = ", ".join(locs) if isinstance(locs, list) else str(locs or "USA")

                    jobs.append({
                        "id": item.get("id") or str(hash(url)),
                        "company": item.get("company_name") or item.get("company") or "Unknown",
                        "title": title,
                        "category": classification["primary"],
                        "subcategories": classification["all_matches"],
                        "terms": terms_list,
                        "location": loc_str,
                        "url": url,
                        "ats_type": detect_ats(url),
                        "sponsorship": item.get("sponsorship", "Unknown"),
                        "degrees": ", ".join(item.get("degrees", [])) if isinstance(item.get("degrees"), list) else str(item.get("degrees") or ""),
                        "date_posted": str(item.get("date_posted") or item.get("date_updated") or "")
                    })
                    seen_urls.add(url)
                return jobs

        # Strategy 2: Fetch and parse Markdown / HTML README tables
        markdown_text = ""
        resolved_branch = ""
        for branch in branches:
            readme_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{info['path']}"
            content = self.fetch_feed_text(readme_url)
            if content:
                markdown_text = content
                resolved_branch = branch
                break

        if not markdown_text:
            print(f"[WARN] Could not locate README or markdown table in {owner}/{repo}")
            return []

        print(f"[OK] Retrieved Markdown content from branch '{resolved_branch}' ({len(markdown_text):,} chars). Parsing tables...")
        return self._parse_markdown_tables(markdown_text)

    def _parse_markdown_tables(self, content: str) -> List[Dict[str, Any]]:
        """Parse HTML and Markdown tables in README to extract internship positions."""
        jobs = []
        seen_urls = set()
        soup = BeautifulSoup(content, "html.parser")
        tables = soup.find_all("table")

        current_category = "software_dev"
        last_company = ""

        # Check if tables exist via HTML tags
        if tables:
            for table in tables:
                # Check for preceding heading
                prev_heading = table.find_previous(["h1", "h2", "h3", "h4"])
                heading_text = prev_heading.get_text().lower() if prev_heading else ""
                if "hardware" in heading_text or "chip" in heading_text or "silicon" in heading_text:
                    current_category = "chip_design"
                elif "ai" in heading_text or "data" in heading_text or "machine learning" in heading_text:
                    current_category = "ai_ml"
                elif "software" in heading_text or "swe" in heading_text:
                    current_category = "software_dev"

                rows = table.find_all("tr")
                for tr in rows:
                    tds = tr.find_all("td")
                    if len(tds) < 3:
                        continue

                    # 1. Company
                    comp_text = tds[0].get_text(strip=True)
                    if comp_text == "↳" or not comp_text:
                        comp_name = last_company
                    else:
                        comp_name = re.sub(r"[🔥⭐🔒🚨]", "", comp_text).strip()
                        last_company = comp_name

                    # 2. Role Title
                    title_text = tds[1].get_text(strip=True)
                    if not is_valid_internship(title_text, ["Summer"]):
                        continue

                    # 3. Location
                    loc_text = tds[2].get_text(strip=True) if len(tds) > 2 else "USA"

                    # 4. Application URL
                    app_td = tds[3] if len(tds) > 3 else tds[-1]
                    links = app_td.find_all("a", href=True)
                    if not links:
                        continue

                    # Prefer direct ATS or company link over simplify badge
                    best_url = ""
                    for a in links:
                        href = a["href"].strip()
                        if "simplify.jobs/p/" in href or "simplify.jobs/install" in href:
                            if not best_url:
                                best_url = href
                        else:
                            best_url = href
                            break

                    if not best_url or best_url in seen_urls:
                        continue

                    # Clean tracking params if desired
                    clean_url = best_url

                    # Classify
                    cls = classify_job(title_text)
                    cat = cls["primary"]
                    if cat == "other":
                        cat = current_category

                    jobs.append({
                        "id": str(hash(clean_url)),
                        "company": comp_name or "Unknown",
                        "title": title_text,
                        "category": cat,
                        "subcategories": cls["all_matches"],
                        "terms": ["Summer 2027"],
                        "location": loc_text,
                        "url": clean_url,
                        "ats_type": detect_ats(clean_url),
                        "sponsorship": "Unknown",
                        "degrees": "",
                        "date_posted": ""
                    })
                    seen_urls.add(clean_url)

        # Also support pipe-delimited Markdown tables if HTML tables were not used
        if not jobs:
            lines = content.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("#"):
                    lh = line.lower()
                    if "hardware" in lh or "chip" in lh:
                        current_category = "chip_design"
                    elif "ai" in lh or "machine learning" in lh:
                        current_category = "ai_ml"
                    elif "software" in lh:
                        current_category = "software_dev"
                    continue

                if "|" in line and not line.startswith("|---") and not line.startswith("| Company"):
                    parts = [p.strip() for p in line.split("|")[1:-1]]
                    if len(parts) >= 4:
                        comp_raw, role_raw, loc_raw, app_raw = parts[0], parts[1], parts[2], parts[3]
                        m_comp = re.search(r"\[(.*?)\]", comp_raw)
                        comp_name = m_comp.group(1) if m_comp else re.sub(r"[*_`]", "", comp_raw).strip()
                        if comp_name == "↳" or not comp_name:
                            comp_name = last_company
                        else:
                            last_company = comp_name

                        role_title = re.sub(r"[*_`]", "", role_raw).strip()
                        if not is_valid_internship(role_title, ["Summer"]):
                            continue

                        # Extract URL from markdown link
                        m_url = re.search(r"\((https?://[^\)]+)\)", app_raw)
                        if not m_url:
                            continue
                        url = m_url.group(1)
                        if url in seen_urls:
                            continue

                        cls = classify_job(role_title)
                        cat = cls["primary"] if cls["primary"] != "other" else current_category

                        jobs.append({
                            "id": str(hash(url)),
                            "company": comp_name,
                            "title": role_title,
                            "category": cat,
                            "subcategories": cls["all_matches"],
                            "terms": ["Summer 2027"],
                            "location": loc_raw,
                            "url": url,
                            "ats_type": detect_ats(url),
                            "sponsorship": "Unknown",
                            "degrees": "",
                            "date_posted": ""
                        })
                        seen_urls.add(url)

        return jobs

    def ingest_github_url(self, github_url: str, clear_first: bool = False) -> Dict[str, Any]:
        """Scrape GitHub URL, insert into database, and report statistics."""
        if clear_first:
            self.db.clear_database()

        jobs = self.scrape_github_repo(github_url)
        new_cnt, updated_cnt = self.db.upsert_jobs_batch(jobs)

        # Count by category
        cat_counts = {}
        for j in jobs:
            c = j["category"]
            cat_counts[c] = cat_counts.get(c, 0) + 1

        return {
            "total_extracted": len(jobs),
            "new_added": new_cnt,
            "updated": updated_cnt,
            "categories": cat_counts,
            "jobs": jobs
        }

    def scrape_all_feeds(self) -> List[Dict[str, Any]]:
        """Fetch all listings across feeds and normalize them."""
        all_jobs = []
        seen_urls = set()

        for feed in FEED_URLS:
            print(f"[*] Fetching feed: {feed['name']}...")
            raw_data = self.fetch_feed_json(feed["url"])
            print(f"    -> Received {len(raw_data)} raw records.")

            for item in raw_data:
                if "active" in item and not item["active"]:
                    continue
                if "is_visible" in item and not item["is_visible"]:
                    continue

                url = item.get("url") or item.get("application_url") or item.get("link")
                if not url or url in seen_urls:
                    continue

                company = item.get("company_name") or item.get("company") or "Unknown"
                title = item.get("title") or item.get("role") or "Intern"
                raw_terms = item.get("terms", [])
                terms_list = raw_terms if isinstance(raw_terms, list) else [str(raw_terms)]

                # Strict internship check
                if not is_valid_internship(title, terms_list):
                    continue

                # Classify
                classification = classify_job(title, item.get("category", ""))
                
                # Locations
                locs = item.get("locations", [])
                location_str = ", ".join(locs) if isinstance(locs, list) else str(locs or "USA")
                
                sponsorship = item.get("sponsorship", "Unknown")
                degrees = item.get("degrees", [])
                degrees_str = ", ".join(degrees) if isinstance(degrees, list) else str(degrees or "")

                job_record = {
                    "id": item.get("id") or str(hash(url)),
                    "company": company,
                    "title": title,
                    "category": classification["primary"],
                    "subcategories": classification["all_matches"],
                    "terms": terms_list,
                    "location": location_str,
                    "url": url,
                    "ats_type": detect_ats(url),
                    "sponsorship": sponsorship,
                    "degrees": degrees_str,
                    "date_posted": str(item.get("date_posted") or item.get("date_updated") or "")
                }
                
                all_jobs.append(job_record)
                seen_urls.add(url)

        return all_jobs

    def sync_database(self, clear_first: bool = True) -> Dict[str, Any]:
        """Scrape latest postings and sync to the SQLite database."""
        if clear_first:
            self.db.clear_database()
        jobs = self.scrape_all_feeds()
        new_cnt, updated_cnt = self.db.upsert_jobs_batch(jobs)
        stats = self.db.get_stats()
        return {
            "scraped": len(jobs),
            "new": new_cnt,
            "updated": updated_cnt,
            "stats": stats
        }

    def search_jobs(
        self,
        category: Optional[str] = None,
        keywords: Optional[str] = None,
        status: Optional[str] = None,
        ats_type: Optional[str] = None,
        term: Optional[str] = "Summer 2027",
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Search and filter internships from the local database."""
        return self.db.get_jobs(
            category=category,
            status=status,
            search=keywords,
            ats_type=ats_type,
            term=term,
            limit=limit
        )

    def export_links_to_file(
        self,
        jobs: List[Dict[str, Any]],
        filepath: str = "internship_links.txt",
        header_note: str = ""
    ) -> str:
        """Export a list of jobs to a clean, human-readable text file."""
        import time
        out_path = os.path.abspath(filepath)
        if os.path.dirname(out_path):
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write("=" * 90 + "\n")
            f.write("SUMMER 2027 INTERNSHIP LINKS FOR HUMAN VERIFICATION / REVIEW\n")
            f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')} | Total Jobs: {len(jobs)}\n")
            if header_note:
                f.write(f"Filter Note: {header_note}\n")
            f.write("=" * 90 + "\n\n")

            if not jobs:
                f.write("No matching internships found for the selected filters.\n")
            else:
                for i, j in enumerate(jobs, 1):
                    f.write(f"[{i}] {j['company']} - {j['title']}\n")
                    f.write(f"    Category : {j['category'].upper()}\n")
                    f.write(f"    Term(s)  : {j.get('terms', 'Summer 2027')}\n")
                    f.write(f"    Location : {j['location']}\n")
                    f.write(f"    ATS Type : {j['ats_type']}\n")
                    f.write(f"    Status   : {j['status']}\n")
                    f.write(f"    Apply URL: {j['url']}\n")
                    f.write("-" * 90 + "\n")

        print(f"[OK] Exported {len(jobs)} internship links to: {out_path}")
        return out_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internship Scraper for Computer Engineering")
    parser.add_argument("--sync", action="store_true", help="Sync latest internships from live feeds")
    parser.add_argument("--category", choices=["chip_design", "software_dev", "ai_ml", "all"], default="all", help="Category filter")
    parser.add_argument("--term", type=str, default="Summer 2027", help="Internship term filter (e.g. 'Summer 2027', 'Summer', 'all')")
    parser.add_argument("--search", type=str, default=None, help="Search query (e.g. 'NVIDIA', 'ASIC', 'Remote')")
    parser.add_argument("--limit", type=int, default=25, help="Number of results to display")
    parser.add_argument("--status", type=str, default="NEW", help="Application status filter (NEW, APPLIED, etc.)")
    parser.add_argument("--github", type=str, default=None, help="Scrape and import internships directly from a GitHub repository or Markdown URL")
    parser.add_argument("--export", type=str, default=None, help="Export results to a .txt file (e.g. --export links.txt)")
    args = parser.parse_args()

    scraper = InternshipScraper()

    if args.github:
        print(f"[*] Ingesting postings from GitHub repository: {args.github}")
        res = scraper.ingest_github_url(args.github)
        print(f"[OK] Extracted {res['total_extracted']} total internships ({res['new_added']} new indexed into database).")
        cats = res.get("categories", {})
        print(f"    Hardware/Chip Design: {cats.get('chip_design', 0)} | SWE: {cats.get('software_dev', 0)} | AI/ML: {cats.get('ai_ml', 0)}")
        sys.exit(0)
    
    if args.sync or scraper.db.get_stats()["total"] == 0:
        print("[*] Syncing internship database for Summer internships...")
        res = scraper.sync_database()
        print(f"[OK] Sync complete: {res['new']} internship listings indexed.")

    cat = None if args.category == "all" else args.category
    term_param = None if args.term.lower() == "all" else args.term
    results = scraper.search_jobs(category=cat, keywords=args.search, term=term_param, status=args.status, limit=args.limit)

    print(f"\nFound {len(results)} jobs matching filters (Category: {args.category}, Term: {args.term}, Search: {args.search}):")
    print("-" * 90)
    for j in results:
        print(f"[{j['category'].upper()}] {j['company']} - {j['title']}")
        print(f"    Term: {j.get('terms')} | Location: {j['location']} | ATS: {j['ats_type']} | Status: {j['status']}")
        print(f"    Apply URL: {j['url']}")
        print("-" * 90)

    if args.export:
        scraper.export_links_to_file(results, filepath=args.export, header_note=f"Category: {args.category}, Term: {args.term}, Search: {args.search}")
