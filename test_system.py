#!/usr/bin/env python3
"""
Automated Test Suite for Internship Automation & Autofill Suite.
Runs end-to-end verification without modifying production data.
"""

import os
import re
import sys
import tempfile
import unittest
from rich.console import Console
from rich.panel import Panel

# Local module imports
from config.profile_loader import load_profile, get_flattened_profile
from data.db import JobDatabase
from scraper import detect_ats, is_valid_internship, InternshipScraper
from autofill import FormAutoFiller
from playwright.sync_api import sync_playwright

console = Console()

class TestProfileConfig(unittest.TestCase):
    def test_profile_loading_and_flattening(self):
        """Verify profile.json is valid and required fields are populated."""
        profile = load_profile()
        self.assertIn("personal", profile)
        self.assertIn("education", profile)
        self.assertIn("documents", profile)

        flat = get_flattened_profile(profile)
        self.assertTrue(bool(flat.get("first_name")), "First name is missing in profile")
        self.assertTrue(bool(flat.get("last_name")), "Last name is missing in profile")
        self.assertTrue(bool(flat.get("email")), "Email is missing in profile")
        self.assertTrue(bool(flat.get("phone")), "Phone is missing in profile")
        self.assertTrue(bool(flat.get("university")), "University is missing in profile")

    def test_resume_file_exists(self):
        """Verify that the configured resume file actually exists on the filesystem."""
        profile = load_profile()
        resume_path = profile.get("documents", {}).get("resume_path", "")
        self.assertTrue(os.path.exists(resume_path), f"Resume file not found at: {resume_path}")
        self.assertGreater(os.path.getsize(resume_path), 0, "Resume file is empty")


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_applications.db")
        self.db = JobDatabase(db_path=self.test_db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_job_lifecycle(self):
        """Verify upserting, querying, updating, and stats in SQLite."""
        sample_job = {
            "company": "NVIDIA",
            "title": "ASIC Design Verification Intern",
            "category": "chip_design",
            "subcategories": ["asic", "verification"],
            "terms": "Summer 2027",
            "location": "Santa Clara, CA",
            "url": "https://nvidia.wd5.myworkdayjobs.com/test-job-1",
            "ats_type": "workday",
            "status": "NEW"
        }

        # 1. Insert job
        is_new = self.db.upsert_job(sample_job)
        self.assertTrue(is_new)

        # 2. Query job
        jobs = self.db.get_jobs(category="chip_design", term="Summer 2027")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["company"], "NVIDIA")
        self.assertEqual(jobs[0]["status"], "NEW")

        # 3. Update status
        updated = self.db.update_job_status(sample_job["url"], status="APPLIED", notes="Submitted online")
        self.assertTrue(updated)

        job_retrieved = self.db.get_job_by_url(sample_job["url"])
        self.assertEqual(job_retrieved["status"], "APPLIED")
        self.assertEqual(job_retrieved["notes"], "Submitted online")

        # 4. Check statistics calculation
        stats = self.db.get_stats(term="Summer 2027")
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["categories"].get("chip_design"), 1)
        self.assertEqual(stats["statuses"].get("APPLIED"), 1)


class TestScraperLogic(unittest.TestCase):
    def test_ats_detection(self):
        """Verify detection of various Applicant Tracking Systems."""
        self.assertEqual(detect_ats("https://boards.greenhouse.io/stripe/jobs/123"), "greenhouse")
        self.assertEqual(detect_ats("https://jobs.lever.co/palantir/abc"), "lever")
        self.assertEqual(detect_ats("https://jobs.ashbyhq.com/anthropic/xyz"), "ashby")
        self.assertEqual(detect_ats("https://nvidia.wd5.myworkdayjobs.com/en-US/jobs/1"), "workday")
        self.assertEqual(detect_ats("https://careers.amd.com/jobs/90379?icims=1"), "icims")
        self.assertEqual(detect_ats("https://example.com/careers/apply"), "generic")

    def test_internship_validation(self):
        """Verify filtering out non-internship and technician roles."""
        self.assertTrue(is_valid_internship("Hardware Design Intern", ["Summer 2027"]))
        self.assertTrue(is_valid_internship("Firmware Co-op", ["Fall 2027"]))
        self.assertTrue(is_valid_internship("AI Engineering Fellow", ["Summer 2027"]))
        
        # Senior / Technician roles without 'intern' in title should be rejected
        self.assertFalse(is_valid_internship("Senior Staff Hardware Engineer", []))
        self.assertFalse(is_valid_internship("Hardware Assembly Technician", []))

    def test_job_categorization(self):
        """Verify categorization logic for CE focus areas."""
        from scraper import classify_job
        
        chip_res = classify_job("FPGA RTL Digital Design Intern", "Hardware")
        self.assertEqual(chip_res["primary"], "chip_design")

        ml_res = classify_job("Deep Learning Vision Intern", "AI Research")
        self.assertEqual(ml_res["primary"], "ai_ml")

        swe_res = classify_job("Backend Systems Software Engineer Intern", "Engineering")
        self.assertEqual(swe_res["primary"], "software_dev")


class TestAutofillEngine(unittest.TestCase):
    def test_headless_form_autofill(self):
        """Spin up a mock HTML application form and verify Playwright heuristic autofill and file upload."""
        from playwright.sync_api import sync_playwright

        filler = FormAutoFiller(headless=True)
        html_content = """
        <!DOCTYPE html>
        <html>
        <head><title>Test Job Application</title></head>
        <body>
            <form id="app-form">
                <label for="first_name">First Name</label>
                <input type="text" id="first_name" name="first_name">

                <label for="last_name">Last Name</label>
                <input type="text" id="last_name" name="last_name">

                <label for="email">Email Address</label>
                <input type="email" id="email" name="email">

                <label for="phone">Phone Number</label>
                <input type="tel" id="phone" name="phone">

                <label for="linkedin">LinkedIn Profile</label>
                <input type="url" id="linkedin" name="urls[LinkedIn]">

                <label for="github">GitHub Profile</label>
                <input type="url" id="github" name="urls[GitHub]">

                <label for="university">School / University</label>
                <input type="text" id="university" name="education_school">

                <label for="resume">Attach Resume / CV</label>
                <input type="file" id="resume" name="resume" accept=".pdf,.doc,.docx">
            </form>
        </body>
        </html>
        """

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html_content)

            # Test Generic Form Filling
            filled_count = filler.fill_generic_heuristics(page)
            self.assertGreaterEqual(filled_count, 5, f"Expected at least 5 fields filled, got {filled_count}")

            # Verify specific field values
            first_name_val = page.input_value("#first_name")
            last_name_val = page.input_value("#last_name")
            email_val = page.input_value("#email")

            self.assertEqual(first_name_val, filler.profile["first_name"])
            self.assertEqual(last_name_val, filler.profile["last_name"])
            self.assertEqual(email_val, filler.profile["email"])

            # Test Resume File Upload
            uploaded = filler.upload_resume(page)
            self.assertTrue(uploaded, "Resume upload should succeed on mock input[type='file']")

            browser.close()

    def test_workday_form_filling(self):
        """Verify Workday data-automation-id input matching."""
        filler = FormAutoFiller(headless=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            html_workday = """
            <!DOCTYPE html>
            <html>
            <body>
                <input data-automation-id="legalNameSection_firstName" />
                <input data-automation-id="legalNameSection_lastName" />
                <input data-automation-id="addressSection_city" />
                <input data-automation-id="phone-number" />
                <input data-automation-id="email" />
            </body>
            </html>
            """
            page.set_content(html_workday)
            filled = filler.fill_workday_form(page)
            self.assertEqual(filled, 5)
            self.assertEqual(page.input_value("input[data-automation-id='legalNameSection_firstName']"), filler.profile["first_name"])
            self.assertEqual(page.input_value("input[data-automation-id='addressSection_city']"), filler.profile["city"])
            browser.close()

    def test_display_jobs_preview(self):
        """Verify jobs preview table renderer formats and displays parsed jobs cleanly."""
        filler = FormAutoFiller(headless=True)
        sample_jobs = [
            {
                "company": "NVIDIA",
                "title": "ASIC Design Intern",
                "category": "chip_design",
                "location": "Santa Clara, CA",
                "ats_type": "workday",
                "url": "https://nvidia.wd5.myworkdayjobs.com/job/1"
            },
            {
                "company": "Apple",
                "title": "Silicon Validation Intern",
                "category": "chip_design",
                "location": "Cupertino, CA",
                "ats_type": "generic",
                "url": "https://jobs.apple.com/en-us/details/2"
            }
        ]
        filler.display_jobs_preview(sample_jobs, title="Test Preview", max_rows=5)


class TestGitHubScraper(unittest.TestCase):
    def setUp(self):
        self.scraper = InternshipScraper()

    def test_github_url_parsing(self):
        """Verify parsing of various GitHub URL formats."""
        res1 = self.scraper.parse_github_url("https://github.com/SimplifyJobs/Summer2027-Internships")
        self.assertEqual(res1["owner"], "SimplifyJobs")
        self.assertEqual(res1["repo"], "Summer2027-Internships")
        self.assertEqual(res1["path"], "README.md")

        res2 = self.scraper.parse_github_url("https://github.com/SimplifyJobs/Summer2027-Internships/blob/dev/README.md")
        self.assertEqual(res2["owner"], "SimplifyJobs")
        self.assertEqual(res2["branch"], "dev")
        self.assertEqual(res2["path"], "README.md")

    def test_markdown_and_html_table_parsing(self):
        """Verify extraction and dual hardware/software categorization from markdown README table."""
        sample_html_table = """
        <h3>Hardware Engineering</h3>
        <table>
            <thead><tr><th>Company</th><th>Role</th><th>Location</th><th>Application</th></tr></thead>
            <tbody>
                <tr>
                    <td><strong>Apple</strong></td>
                    <td>Silicon Design Verification Intern</td>
                    <td>Cupertino, CA</td>
                    <td><a href="https://jobs.apple.com/en-us/details/12345">Apply</a></td>
                </tr>
            </tbody>
        </table>
        <h3>Software Engineering</h3>
        <table>
            <thead><tr><th>Company</th><th>Role</th><th>Location</th><th>Application</th></tr></thead>
            <tbody>
                <tr>
                    <td><strong>Google</strong></td>
                    <td>Software Engineering Intern</td>
                    <td>Mountain View, CA</td>
                    <td><a href="https://careers.google.com/jobs/results/67890">Apply</a></td>
                </tr>
            </tbody>
        </table>
        """
        jobs = self.scraper._parse_markdown_tables(sample_html_table)
        self.assertEqual(len(jobs), 2)
        hw = [j for j in jobs if j["category"] == "chip_design"]
        swe = [j for j in jobs if j["category"] == "software_dev"]
        self.assertEqual(len(hw), 1)
        self.assertEqual(len(swe), 1)
        self.assertEqual(hw[0]["company"], "Apple")
        self.assertEqual(swe[0]["company"], "Google")


class TestAIAssistant(unittest.TestCase):
    def test_ai_initialization_and_mock(self):
        """Verify AI Assistant initializes and handles missing keys gracefully."""
        from ai_assistant import AIAssistant
        assistant = AIAssistant()
        self.assertEqual(assistant.gemini_model, "gemini-3.1-flash-lite")
        self.assertEqual(assistant.openai_model, "5.6-luna")
        self.assertEqual(assistant.temperature, 0.1)
        # Without key, returns None safely
        assistant.api_key = None
        ans = assistant.answer_question("Are you open to starting full-time immediately?", {"university": "Purdue University"})
        self.assertIsNone(ans)

    def test_question_not_matched_as_school_name(self):
        """Verify that a sentence question containing 'school' is recognized as a question and not a university name."""
        question = "Are you open to starting full-time immediately after your internship? (either graduated or willing to take time off from school)*"
        is_question = bool(re.search(r"(\?|\bare you\b|\bwhy\b|\bdescribe\b|\bexplain\b|\bhow did\b|\btell us\b|\bplease specify\b|\bwhat are\b|\bwhat is your\b|\bif yes\b|\bshare with us\b|\bstatement\b|\bcover letter\b)", question, re.I)) or len(question.split()) > 7
        self.assertTrue(is_question)


def run_tests():
    console.print(Panel("[bold cyan]Running Automated Test Suite for Internship Suite[/bold cyan]\n"
                        "Testing Profile Config, Database, Scraper Rules, and Headless Autofill...",
                        border_style="cyan"))

    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestProfileConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabase))
    suite.addTests(loader.loadTestsFromTestCase(TestScraperLogic))
    suite.addTests(loader.loadTestsFromTestCase(TestGitHubScraper))
    suite.addTests(loader.loadTestsFromTestCase(TestAutofillEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestAIAssistant))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        console.print("\n[bold green][+] ALL TESTS PASSED SUCCESSFULLY[/bold green]")
        return 0
    else:
        console.print("\n[bold red][-] SOME TESTS FAILED[/bold red]")
        return 1

if __name__ == "__main__":
    sys.exit(run_tests())
