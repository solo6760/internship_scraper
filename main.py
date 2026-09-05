import os
import sys
import argparse
from typing import Optional, List, Dict, Any
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.text import Text

from data.db import JobDatabase
from scraper import InternshipScraper, CATEGORIES
from autofill import FormAutoFiller
from config.profile_loader import load_profile, save_profile, get_flattened_profile

console = Console()

class InternshipApp:
    def __init__(self):
        self.db = JobDatabase()
        self.scraper = InternshipScraper(self.db)
        self.filler = FormAutoFiller(headless=False)

    def print_banner(self):
        stats_s27 = self.db.get_stats(term="Summer 2027")
        cats = stats_s27.get("categories", {})
        statuses = stats_s27.get("statuses", {})

        console.print("\n[bold white]===================================================================[/bold white]")
        console.print("  [bold cyan]INTERNSHIP AUTOFILL & APPLICATION SUITE[/bold cyan] (Summer 2027)")
        console.print(f"  Total: {stats_s27.get('total', 0)} | Hardware: {cats.get('chip_design', 0)} | SWE: {cats.get('software_dev', 0)} | AI/ML: {cats.get('ai_ml', 0)} | Applied: {statuses.get('APPLIED', 0)}")
        console.print("[bold white]===================================================================[/bold white]")

    def show_jobs_table(self, jobs: List[Dict[str, Any]], title: str = "Internship Listings"):
        if not jobs:
            console.print("[yellow]No matching internships found.[/yellow]")
            return

        table = Table(title=title, show_header=True, header_style="bold cyan", border_style="dim")
        table.add_column("#", style="dim", width=4)
        table.add_column("Company", style="bold white", width=18)
        table.add_column("Role / Title", style="bold white", width=34)
        table.add_column("Category", width=13)
        table.add_column("Term", style="yellow", width=14)
        table.add_column("Location", width=20)
        table.add_column("ATS", width=9)
        table.add_column("Status", width=9)

        for i, j in enumerate(jobs, 1):
            cat_style = "yellow" if j["category"] == "chip_design" else "magenta" if j["category"] == "ai_ml" else "green" if j["category"] == "software_dev" else "white"
            status_style = "bold green" if j["status"] == "APPLIED" else "bold red" if j["status"] == "SKIPPED" else "blue"
            
            table.add_row(
                str(i),
                j["company"][:17],
                j["title"][:33],
                f"[{cat_style}]{j['category'][:12]}[/{cat_style}]",
                str(j.get("terms", "Summer 2027"))[:13],
                j["location"][:19],
                j["ats_type"][:8],
                f"[{status_style}]{j['status']}[/{status_style}]"
            )

        console.print(table)

    def search_and_apply_flow(self, default_cat: Optional[str] = None, default_term: str = "Summer 2027"):
        console.print("\n[bold cyan]--- Search Internships ---[/bold cyan]")
        
        category = default_cat
        if not category:
            console.print("Select Category:")
            console.print("  [1] Chip Design / Hardware / Embedded")
            console.print("  [2] AI / Machine Learning")
            console.print("  [3] Software Development")
            console.print("  [4] All Categories")
            choice = Prompt.ask("Choice", choices=["1", "2", "3", "4"], default="1")
            cat_map = {"1": "chip_design", "2": "ai_ml", "3": "software_dev", "4": "all"}
            category = cat_map[choice]

        term = Prompt.ask("Internship Term", choices=["Summer 2027", "Summer", "All"], default=default_term)
        term_param = None if term.lower() == "all" else term

        search_query = Prompt.ask("Keyword filter (e.g. 'NVIDIA', 'Remote')", default="")
        search_query = search_query.strip() if search_query else None
        
        status_filter = Prompt.ask("Status filter", choices=["NEW", "ALL", "APPLIED", "SKIPPED"], default="NEW")

        cat_param = None if category == "all" else category
        jobs = self.db.get_jobs(category=cat_param, search=search_query, term=term_param, status=status_filter, limit=25)

        self.show_jobs_table(jobs, title=f"Top {len(jobs)} Positions ({category.upper()} - {term})")

        if not jobs:
            return

        console.print("\nActions:")
        console.print("  - Enter job number (1 - {}) to Autofill & Apply".format(len(jobs)))
        console.print("  - Enter 'e' to export these {} links to file".format(len(jobs)))
        console.print("  - Enter 'q' to return to menu")
        action = Prompt.ask("Selection", default="e")

        if action.lower() == 'q':
            return
        elif action.lower() in ['e', 'export']:
            filepath = Prompt.ask("Output file path", default="summer_2027_internships.txt")
            out = self.scraper.export_links_to_file(jobs, filepath=filepath, header_note=f"Category: {category.upper()}, Term: {term}, Search: {search_query or 'None'}")
            console.print(f"[bold green][OK] Exported links to: {out}[/bold green]")
            Prompt.ask("\nPress Enter to return to menu")
            return

        try:
            idx = int(action) - 1
            if 0 <= idx < len(jobs):
                selected_job = jobs[idx]
                self.apply_to_job(selected_job)
        except ValueError:
            console.print("[red]Invalid selection.[/red]")

    def export_links_flow(self):
        console.print("\n[bold cyan]--- Export Links to File ---[/bold cyan]")
        console.print("Select Category to Export:")
        console.print("  [1] Chip Design / Hardware / Embedded")
        console.print("  [2] AI / Machine Learning")
        console.print("  [3] Software Development")
        console.print("  [4] All Categories")
        choice = Prompt.ask("Choice", choices=["1", "2", "3", "4"], default="1")
        cat_map = {"1": "chip_design", "2": "ai_ml", "3": "software_dev", "4": "all"}
        category = cat_map[choice]

        term = Prompt.ask("Select Term", choices=["Summer 2027", "Summer", "All"], default="Summer 2027")
        term_param = None if term.lower() == "all" else term

        search_query = Prompt.ask("Keyword filter (optional, e.g. 'Remote', 'NVIDIA')", default="")
        search_query = search_query.strip() if search_query else None

        limit = IntPrompt.ask("How many jobs to export?", default=50)
        default_file = f"{category}_summer_2027.txt" if category != "all" else "summer_2027_internships.txt"
        filepath = Prompt.ask("Enter filename", default=default_file)

        cat_param = None if category == "all" else category
        jobs = self.db.get_jobs(category=cat_param, search=search_query, term=term_param, status="NEW", limit=limit)

        out = self.scraper.export_links_to_file(jobs, filepath=filepath, header_note=f"Category: {category.upper()}, Term: {term}, Search: {search_query or 'None'}")
        console.print(f"\n[bold green][OK] Exported {len(jobs)} jobs to:[/bold green] [cyan]{out}[/cyan]")
        Prompt.ask("\nPress Enter to continue")

    def apply_to_job(self, job: Dict[str, Any]):
        console.print(f"\nPreparing Application: [bold white]{job['company']} - {job['title']}[/bold white]")
        console.print(f"Term: {job.get('terms', 'Summer 2027')}")
        console.print(f"URL: {job['url']}")
        console.print(f"ATS: {job['ats_type']}")

        proceed = Confirm.ask("Launch browser and autofill form?", default=True)
        if not proceed:
            return

        res = self.filler.autofill_page(job["url"])
        
        if res.get("status") == "COMPLETED":
            mark_applied = Confirm.ask(f"Mark application for {job['company']} as APPLIED in database?", default=True)
            if mark_applied:
                self.db.update_job_status(job["url"], "APPLIED")
                console.print(f"[bold green][OK] Updated status to APPLIED for {job['company']}.[/bold green]")
        elif res.get("status") == "ERROR":
            console.print(f"[red][ERROR] Autofill encountered an error: {res.get('error')}[/red]")

    def direct_url_apply(self, initial_url: Optional[str] = None, parse_mode: bool = False):
        self.filler.run_feeder_loop(initial_urls=[initial_url] if initial_url else None, parse_mode=parse_mode)

    def batch_apply_flow(self):
        console.print("\n[bold cyan]--- Batch Auto-Apply Queue (Summer 2027) ---[/bold cyan]")
        
        cat = Prompt.ask("Select Category", choices=["chip_design", "ai_ml", "software_dev", "all"], default="chip_design")
        term = Prompt.ask("Select Term", choices=["Summer 2027", "Summer", "All"], default="Summer 2027")
        cat_param = None if cat == "all" else cat
        term_param = None if term.lower() == "all" else term

        jobs = self.db.get_jobs(category=cat_param, term=term_param, status="NEW", limit=20)

        if not jobs:
            console.print("[yellow]No new unapplied jobs found matching these filters.[/yellow]")
            return

        console.print(f"[green]Found {len(jobs)} pending applications in queue.[/green]")
        for i, job in enumerate(jobs, 1):
            console.print(f"\n[bold cyan]Queue Item {i}/{len(jobs)}:[/bold cyan] {job['company']} - {job['title']}")
            console.print(f"Term: {job.get('terms')} | Location: {job['location']} | ATS: {job['ats_type']}")
            
            action = Prompt.ask("Action", choices=["apply", "skip", "stop"], default="apply")
            if action == "stop":
                break
            elif action == "skip":
                self.db.update_job_status(job["url"], "SKIPPED")
                console.print("[yellow]Marked as SKIPPED.[/yellow]")
                continue
            elif action == "apply":
                res = self.filler.autofill_page(job["url"])
                if res.get("status") == "COMPLETED":
                    if Confirm.ask(f"Mark {job['company']} as APPLIED?", default=True):
                        self.db.update_job_status(job["url"], "APPLIED")

    def manage_profile(self):
        console.print("\n[bold cyan]--- User Profile & Configuration ---[/bold cyan]")
        p = load_profile()
        flat = get_flattened_profile(p)

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Field", style="bold white", width=24)
        table.add_column("Current Value", style="cyan", width=50)

        for k, v in flat.items():
            table.add_row(k.replace("_", " ").title(), str(v))

        console.print(table)
        console.print(f"\nProfile path: {os.path.abspath('config/profile.json')}")
        
        if Confirm.ask("Edit any profile field?", default=False):
            field = Prompt.ask("Enter field name (or 'cancel')", default="cancel")
            if field != "cancel":
                new_val = Prompt.ask(f"Enter new value for {field}")
                if field in p.get("personal", {}):
                    p["personal"][field] = new_val
                elif field in p.get("education", {}):
                    p["education"][field] = new_val
                elif field in p.get("links", {}):
                    p["links"][field] = new_val
                elif field == "resume_path":
                    p["documents"]["resume_path"] = new_val
                save_profile(p)
                self.filler = FormAutoFiller(headless=False)
                console.print("[bold green][OK] Profile updated successfully.[/bold green]")

    def run_demo_test(self):
        console.print("\n[bold cyan]--- Testing Autofill Engine ---[/bold cyan]")
        console.print("Running verification on practice form...")
        res = self.filler.autofill_page("https://demoqa.com/automation-practice-form")
        console.print(f"\nResult: {res}")

    def main_menu(self):
        while True:
            self.print_banner()
            console.print("Main Menu:")
            console.print("  [1] Search & Discover Internships")
            console.print("  [2] Browse & Track Applications")
            console.print("  [3] Fast Link Feeder (Continuous Autofill)")
            console.print("  [4] Parse & Preview Mode (Read Back Links & Repos)")
            console.print("  [5] Batch Auto-Apply Queue")
            console.print("  [6] Export Links to Text File")
            console.print("  [7] Sync Postings from Online Feeds")
            console.print("  [8] View / Edit Profile & Resume Config")
            console.print("  [9] Test Autofill on Demo Form")
            console.print("  [0] Exit")

            choice = Prompt.ask("\nEnter option", choices=["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"], default="3")

            if choice == "1":
                self.search_and_apply_flow()
            elif choice == "2":
                jobs = self.db.get_jobs(term="Summer", limit=30)
                self.show_jobs_table(jobs, title="Tracked Summer Internships (Recent 30)")
                Prompt.ask("\nPress Enter to continue")
            elif choice == "3":
                self.direct_url_apply(parse_mode=False)
            elif choice == "4":
                self.direct_url_apply(parse_mode=True)
            elif choice == "5":
                self.batch_apply_flow()
            elif choice == "6":
                self.export_links_flow()
            elif choice == "7":
                with console.status("[bold green]Syncing latest postings..."):
                    res = self.scraper.sync_database()
                console.print(f"[bold green][OK] Synced {res['scraped']} postings ({res['new']} added).[/bold green]")
                Prompt.ask("\nPress Enter to continue")
            elif choice == "8":
                self.manage_profile()
                Prompt.ask("\nPress Enter to continue")
            elif choice == "9":
                self.run_demo_test()
            elif choice == "0":
                console.print("Exiting...")
                sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Computer Engineering Summer Internship Automation Suite")
    parser.add_argument("--sync", action="store_true", help="Sync latest internships from feeds and exit")
    parser.add_argument("--feed", action="store_true", help="Launch interactive continuous Link Feeder mode")
    parser.add_argument("--parse", nargs="*", default=None, help="Parse mode: read back short list of internships from pasted URLs or GitHub repo without launching browser")
    parser.add_argument("--github", type=str, default=None, help="Scrape & queue internships from a GitHub repo URL")
    parser.add_argument("--category", choices=["chip_design", "ai_ml", "software_dev", "all"], default=None, help="Launch search in category")
    parser.add_argument("--term", type=str, default="Summer 2027", help="Filter by term (default: Summer 2027)")
    parser.add_argument("--apply", type=str, default=None, help="Directly autofill a job application URL")
    parser.add_argument("--export", type=str, default=None, help="Export matching jobs to a .txt file (e.g. --export links.txt)")
    parser.add_argument("--limit", type=int, default=50, help="Limit for export/search")
    args = parser.parse_args()

    app = InternshipApp()

    if args.parse is not None:
        urls = args.parse if len(args.parse) > 0 else None
        app.filler.run_feeder_loop(initial_urls=urls, parse_mode=True)
    elif args.feed:
        app.direct_url_apply()
    elif args.github:
        app.direct_url_apply(initial_url=args.github)
    elif args.sync:
        res = app.scraper.sync_database()
        print(f"Sync complete: {res['new']} internships added.")
    elif args.apply:
        app.filler.autofill_page(args.apply)
    elif args.export:
        cat = None if args.category == "all" else args.category
        term_param = None if args.term.lower() == "all" else args.term
        jobs = app.db.get_jobs(category=cat, term=term_param, status="NEW", limit=args.limit)
        app.scraper.export_links_to_file(jobs, filepath=args.export, header_note=f"Category: {args.category or 'ALL'}, Term: {args.term}")
    elif args.category:
        app.search_and_apply_flow(default_cat=args.category, default_term=args.term)
    else:
        app.main_menu()
