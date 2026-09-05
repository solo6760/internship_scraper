import os
import re
import sys
import time
from typing import Dict, Any, Optional, List, Tuple, Union
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, ElementHandle, Frame
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.text import Text

from config.profile_loader import load_profile, get_flattened_profile
from data.db import JobDatabase
from scraper import detect_ats, InternshipScraper

console = Console()

class FormAutoFiller:
    def __init__(self, profile_path: Optional[str] = None, headless: bool = False):
        self.raw_profile = load_profile(profile_path)
        self.profile = get_flattened_profile(self.raw_profile)
        self.headless = headless
        self.resume_path = os.path.abspath(self.profile.get("resume_path", ""))
        self.db = JobDatabase()
        self._validate_resume_path()

    def _validate_resume_path(self) -> None:
        """Check if resume exists and warn if missing."""
        if not self.resume_path or not os.path.exists(self.resume_path):
            console.print(f"[yellow][WARN] Resume not found at '{self.resume_path}'. Resume upload may fail.[/yellow]")
        else:
            console.print(f"[green][OK] Resume verified: {self.resume_path} ({os.path.getsize(self.resume_path):,} bytes)[/green]")

    def display_jobs_preview(self, jobs: List[Dict[str, Any]], title: str = "Internships Preview", max_rows: int = 10, show_full_urls: bool = True) -> None:
        """Render a clean, minimal preview table reading back parsed internships with clickable links."""
        if not jobs:
            console.print("[yellow]No internships to display.[/yellow]")
            return

        table = Table(title=title, show_header=True, header_style="bold cyan", border_style="dim")
        table.add_column("#", style="dim", width=4)
        table.add_column("Company", style="bold white", width=18)
        table.add_column("Role / Title", style="bold white", width=32)
        table.add_column("Track", width=12)
        table.add_column("Location", width=18)
        table.add_column("ATS", width=9)
        table.add_column("Application Link", style="cyan", width=18)

        for i, j in enumerate(jobs[:max_rows], 1):
            cat = j.get("category", "other")
            cat_style = "yellow" if cat == "chip_design" else "magenta" if cat == "ai_ml" else "green" if cat == "software_dev" else "white"
            cat_label = "Hardware" if cat == "chip_design" else "AI/ML" if cat == "ai_ml" else "SWE" if cat == "software_dev" else cat

            full_url = j.get("url", "")
            clickable_table_link = f"[link={full_url}][cyan underline]Open Link[/cyan underline][/link]" if full_url else "N/A"

            table.add_row(
                str(i),
                str(j.get("company", "Unknown"))[:17],
                str(j.get("title", "Role"))[:31],
                f"[{cat_style}]{cat_label}[/{cat_style}]",
                str(j.get("location", "USA"))[:17],
                str(j.get("ats_type", detect_ats(full_url)))[:8],
                clickable_table_link
            )

        console.print(table)
        if len(jobs) > max_rows:
            console.print(f"[dim]... and {len(jobs) - max_rows} more internships found.[/dim]")

        if show_full_urls:
            console.print("\n[bold cyan]Clickable Direct Links (Full URLs):[/bold cyan]")
            for i, j in enumerate(jobs[:max_rows], 1):
                full_url = j.get("url", "")
                comp = j.get("company", "Company")
                role = j.get("title", "Role")
                console.print(f"  [{i}] [bold white]{comp}[/bold white] - {role[:36]}:\n      [link={full_url}][cyan underline]{full_url}[/cyan underline][/link]")

    def _get_all_contexts(self, page: Page) -> List[Union[Page, Frame]]:
        """Return main page and all iframe frames to support embedded forms."""
        try:
            contexts: List[Union[Page, Frame]] = [page.main_frame]
            for f in page.frames:
                if f != page.main_frame and f not in contexts:
                    contexts.append(f)
            return contexts
        except Exception:
            return [page]

    def _inject_status_banner(self, page: Page, filled_count: int, resume_uploaded: bool, ats_type: str = "Generic") -> None:
        """Inject an overlay badge showing autofill stats and styling."""
        status_text = f"Autofill: {filled_count} fields populated"
        if resume_uploaded:
            status_text += " | Resume attached"
        
        js_code = f"""
        (() => {{
            let banner = document.getElementById('ag-autofill-banner');
            if (!banner) {{
                banner = document.createElement('div');
                banner.id = 'ag-autofill-banner';
                banner.style.position = 'fixed';
                banner.style.top = '16px';
                banner.style.right = '16px';
                banner.style.zIndex = '99999999';
                banner.style.backgroundColor = '#090d16';
                banner.style.color = '#38bdf8';
                banner.style.padding = '14px 22px';
                banner.style.borderRadius = '12px';
                banner.style.boxShadow = '0 12px 30px rgba(0,0,0,0.6)';
                banner.style.fontFamily = 'system-ui, -apple-system, sans-serif';
                banner.style.fontSize = '14px';
                banner.style.fontWeight = '600';
                banner.style.border = '1.5px solid #0284c7';
                banner.style.transition = 'all 0.3s ease';
                banner.style.cursor = 'default';
                document.body.appendChild(banner);
            }}
            banner.innerHTML = '{status_text}<br><span style="color:#22c55e;font-size:12px">ATS: {ats_type.upper()}</span> | <span style="color:#94a3b8;font-size:12px;font-weight:400">Review required custom fields & submit when ready</span>';
        }})();
        """
        try:
            page.evaluate(js_code)
        except Exception:
            pass

    def _get_element_label_and_context(self, target: Union[Page, Frame], el: ElementHandle) -> str:
        """Extract label text, placeholder, aria attributes, name, and id for fuzzy matching."""
        try:
            return target.evaluate("""(el) => {
                let text = '';
                if (el.id) text += ' ' + el.id;
                if (el.name) text += ' ' + el.name;
                if (el.placeholder) text += ' ' + el.placeholder;
                if (el.getAttribute('aria-label')) text += ' ' + el.getAttribute('aria-label');
                if (el.getAttribute('autocomplete')) text += ' ' + el.getAttribute('autocomplete');
                if (el.getAttribute('data-qa')) text += ' ' + el.getAttribute('data-qa');
                if (el.getAttribute('data-automation-id')) text += ' ' + el.getAttribute('data-automation-id');
                
                // Label with 'for'
                if (el.id) {
                    let label = document.querySelector(`label[for="${el.id}"]`);
                    if (label) text += ' ' + label.innerText;
                }
                
                // Parent label
                let parentLabel = el.closest('label');
                if (parentLabel) text += ' ' + parentLabel.innerText;
                
                // Container headings / spans
                let container = el.closest('.form-group, .field, .input-container, .application-question, [data-automation-id="formField"], div');
                if (container) {
                    let headers = container.querySelectorAll('label, span, p, h3, h4, legend');
                    headers.forEach(h => text += ' ' + h.innerText);
                }
                return text.toLowerCase();
            }""", el)
        except Exception:
            return ""

    def upload_resume(self, page: Page) -> bool:
        """Find and upload resume PDF across all frames with multi-strategy matching."""
        if not self.resume_path or not os.path.exists(self.resume_path):
            console.print("[dim][-] Resume file not found on disk, skipping upload.[/dim]")
            return False

        contexts = self._get_all_contexts(page)

        # Strategy 1: Look for file inputs directly across all frames (visible or hidden)
        for ctx in contexts:
            try:
                file_inputs = ctx.query_selector_all('input[type="file"]')
                for finput in file_inputs:
                    context = self._get_element_label_and_context(ctx, finput)
                    if any(k in context for k in ["resume", "cv", "curriculum", "file", "attach", "upload", "document"]) or len(file_inputs) == 1:
                        finput.set_input_files(self.resume_path)
                        console.print(f"[bold green][OK] Uploaded resume to matching file input.[/bold green]")
                        time.sleep(1)
                        return True
            except Exception:
                pass

        # Strategy 2: Specific ATS file selectors
        selectors = [
            'input[data-automation-id="file-upload-input-ref"]',
            '#resume_file',
            '[data-qa="resume-upload"]',
            'input[name*="resume"]',
            '.application-resume-file input[type="file"]',
            '#resume-upload-input',
            'input[id*="resume"]',
            'input[id*="cv"]'
        ]
        for ctx in contexts:
            for sel in selectors:
                try:
                    elem = ctx.query_selector(sel)
                    if elem:
                        elem.set_input_files(self.resume_path)
                        console.print(f"[bold green][OK] Uploaded resume via selector: {sel}[/bold green]")
                        time.sleep(1)
                        return True
                except Exception:
                    pass

        # Strategy 3: Click dropzone/upload button expecting file chooser
        clickable_selectors = [
            'button:has-text("Upload Resume")',
            'button:has-text("Attach Resume")',
            'button:has-text("Upload CV")',
            'button[data-automation-id="file-upload-button"]',
            '.dropzone',
            '[data-qa="dropzone"]'
        ]
        for ctx in contexts:
            for c_sel in clickable_selectors:
                try:
                    btn = ctx.query_selector(c_sel)
                    if btn and btn.is_visible():
                        with page.expect_file_chooser(timeout=2500) as fc_info:
                            btn.click()
                        file_chooser = fc_info.value
                        file_chooser.set_files(self.resume_path)
                        console.print(f"[bold green][OK] Uploaded resume via button file chooser: {c_sel}[/bold green]")
                        time.sleep(1)
                        return True
                except Exception:
                    pass

        return False

    def fill_workday_form(self, page: Page) -> int:
        """Dedicated handler for Workday job applications (myworkdayjobs.com)."""
        filled = 0
        p = self.profile

        # Check if landing page has "Apply Manually" or "Apply" button
        try:
            apply_manually_btn = page.query_selector('button[data-automation-id="applyManually"], a[data-automation-id="applyManually"], button:has-text("Apply Manually")')
            if apply_manually_btn and apply_manually_btn.is_visible():
                console.print("[cyan][*] Workday landing page detected: Clicking 'Apply Manually'...[/cyan]")
                apply_manually_btn.click()
                page.wait_for_load_state("domcontentloaded", timeout=8000)
                time.sleep(2)
        except Exception:
            pass

        contexts = self._get_all_contexts(page)
        for ctx in contexts:
            workday_mappings = [
                ('input[data-automation-id*="legalNameSection_firstName"], input[data-automation-id="firstName"]', p["first_name"]),
                ('input[data-automation-id*="legalNameSection_lastName"], input[data-automation-id="lastName"]', p["last_name"]),
                ('input[data-automation-id*="addressSection_addressLine1"], input[data-automation-id="addressLine1"]', p["street_address"]),
                ('input[data-automation-id*="addressSection_city"], input[data-automation-id="city"]', p["city"]),
                ('input[data-automation-id*="addressSection_postalCode"], input[data-automation-id="postalCode"]', p["zip_code"]),
                ('input[data-automation-id="phone-number"], input[data-automation-id="contactInfoPhone-number"], input[type="tel"]', p["phone"]),
                ('input[data-automation-id="email"]', p["email"]),
            ]

            for selector, value in workday_mappings:
                if not value:
                    continue
                try:
                    elems = ctx.query_selector_all(selector)
                    for elem in elems:
                        if elem.is_visible() and not (elem.input_value() or "").strip():
                            elem.fill(value)
                            filled += 1
                            ctx.evaluate("(el) => { el.style.outline = '2px solid #22c55e'; el.style.backgroundColor = '#f0fdf4'; }", elem)
                except Exception:
                    pass

            # Workday terms checkbox
            try:
                cb = ctx.query_selector('input[data-automation-id="agreementCheckbox"], input[type="checkbox"][id*="agreement"]')
                if cb and not cb.is_checked():
                    cb.check(force=True)
                    filled += 1
            except Exception:
                pass

        return filled

    def fill_greenhouse_form(self, page: Page) -> int:
        """Dedicated handler for Greenhouse job applications."""
        filled = 0
        p = self.profile
        contexts = self._get_all_contexts(page)

        field_mappings = [
            ("#first_name", p["first_name"]),
            ("#last_name", p["last_name"]),
            ("#email", p["email"]),
            ("#phone", p["phone"]),
            ("input[autocomplete='custom-question-linkedin-profile']", p["linkedin"]),
            ("input[autocomplete='custom-question-website']", p["portfolio"] or p["github"]),
            ("input[id*='job_application_answers_attributes_'][id*='linkedin']", p["linkedin"]),
            ("input[id*='job_application_answers_attributes_'][id*='github']", p["github"]),
            ("input[id*='job_application_answers_attributes_'][id*='website']", p["portfolio"] or p["github"]),
            ("input[id*='education_school_name']", p["university"]),
            ("input[id*='education_degree']", p["degree"]),
            ("input[id*='education_discipline']", p["major"]),
            ("input[id*='job_application_answers_attributes_'][id*='school']", p["university"]),
            ("input[id*='job_application_answers_attributes_'][id*='major']", p["major"]),
            ("input[id*='job_application_answers_attributes_'][id*='gpa']", p["gpa"]),
        ]

        for ctx in contexts:
            for selector, value in field_mappings:
                if not value:
                    continue
                try:
                    elems = ctx.query_selector_all(selector)
                    for elem in elems:
                        if elem.is_visible() and not (elem.input_value() or "").strip():
                            elem.fill(value)
                            filled += 1
                            ctx.evaluate("(el) => { el.style.outline = '2px solid #22c55e'; el.style.backgroundColor = '#f0fdf4'; }", elem)
                except Exception:
                    pass

            # Greenhouse Demographic EEO Dropdowns
            eeo_selects = [
                ("#job_application_gender", p["gender"]),
                ("#job_application_hispanic_ethnicity", p["hispanic_latino"]),
                ("#job_application_race", p["race_ethnicity"]),
                ("#job_application_veteran_status", p["veteran_status"]),
                ("#job_application_disability_status", p["disability_status"])
            ]
            for sel_id, val in eeo_selects:
                if not val:
                    continue
                try:
                    sel = ctx.query_selector(sel_id)
                    if sel:
                        opts = sel.query_selector_all("option")
                        for opt in opts:
                            txt = (opt.text_content() or "").lower()
                            if val.lower() in txt or (val.lower() == "no" and ("not" in txt or "no" in txt)):
                                sel.select_option(value=opt.get_attribute("value") or opt.text_content())
                                filled += 1
                                break
                except Exception:
                    pass

        return filled

    def fill_lever_form(self, page: Page) -> int:
        """Dedicated handler for Lever job applications."""
        filled = 0
        p = self.profile
        contexts = self._get_all_contexts(page)

        lever_mappings = [
            ("input[name='name']", p["full_name"]),
            ("input[name='email']", p["email"]),
            ("input[name='phone']", p["phone"]),
            ("input[name='org']", p["university"]),
            ("input[name='urls[LinkedIn]']", p["linkedin"]),
            ("input[name='urls[GitHub]']", p["github"]),
            ("input[name='urls[Portfolio]']", p["portfolio"] or p["github"]),
            ("input[name='urls[Twitter]']", p["twitter"]),
            ("input[name='urls[Other]']", p["portfolio"])
        ]

        for ctx in contexts:
            for selector, value in lever_mappings:
                if not value:
                    continue
                try:
                    elems = ctx.query_selector_all(selector)
                    for elem in elems:
                        if elem.is_visible() and not (elem.input_value() or "").strip():
                            elem.fill(value)
                            filled += 1
                            ctx.evaluate("(el) => { el.style.outline = '2px solid #22c55e'; el.style.backgroundColor = '#f0fdf4'; }", elem)
                except Exception:
                    pass

            # Lever consent checkbox
            try:
                cbs = ctx.query_selector_all("input[type='checkbox'][name*='consent'], input[type='checkbox'][name*='agree']")
                for cb in cbs:
                    if not cb.is_checked():
                        cb.check(force=True)
                        filled += 1
            except Exception:
                pass

        return filled

    def fill_ashby_form(self, page: Page) -> int:
        """Dedicated handler for Ashby job applications."""
        filled = 0
        p = self.profile
        contexts = self._get_all_contexts(page)

        ashby_mappings = [
            ("input[name='_systemfield_name']", p["full_name"]),
            ("input[name='_systemfield_email']", p["email"]),
            ("input[name='_systemfield_phoneNumber']", p["phone"]),
            ("input[name*='linkedin']", p["linkedin"]),
            ("input[name*='github']", p["github"]),
            ("input[name*='website']", p["portfolio"] or p["github"]),
            ("input[name*='school']", p["university"]),
            ("input[name*='major']", p["major"])
        ]

        for ctx in contexts:
            for selector, value in ashby_mappings:
                if not value:
                    continue
                try:
                    elems = ctx.query_selector_all(selector)
                    for elem in elems:
                        if elem.is_visible() and not (elem.input_value() or "").strip():
                            elem.fill(value)
                            filled += 1
                            ctx.evaluate("(el) => { el.style.outline = '2px solid #22c55e'; el.style.backgroundColor = '#f0fdf4'; }", elem)
                except Exception:
                    pass

        return filled

    def fill_smartrecruiters_form(self, page: Page) -> int:
        """Dedicated handler for SmartRecruiters applications."""
        filled = 0
        p = self.profile
        contexts = self._get_all_contexts(page)

        sr_mappings = [
            ("input[id='first-name-input'], input[name='firstName']", p["first_name"]),
            ("input[id='last-name-input'], input[name='lastName']", p["last_name"]),
            ("input[id='email-input'], input[name='email']", p["email"]),
            ("input[id='phone-number-input'], input[name='phoneNumber']", p["phone"]),
            ("input[id='city-input'], input[name='city']", p["city"]),
            ("input[name*='linkedin' i]", p["linkedin"]),
            ("input[name*='website' i]", p["portfolio"] or p["github"])
        ]

        for ctx in contexts:
            for selector, value in sr_mappings:
                if not value:
                    continue
                try:
                    elems = ctx.query_selector_all(selector)
                    for elem in elems:
                        if elem.is_visible() and not (elem.input_value() or "").strip():
                            elem.fill(value)
                            filled += 1
                            ctx.evaluate("(el) => { el.style.outline = '2px solid #22c55e'; el.style.backgroundColor = '#f0fdf4'; }", elem)
                except Exception:
                    pass

        return filled

    def fill_tesla_form(self, page: Page) -> int:
        """Dedicated handler for Tesla Careers job applications."""
        filled = 0
        p = self.profile
        contexts = self._get_all_contexts(page)

        tesla_mappings = [
            ("input[name*='firstName' i], input[id*='firstName' i], input[data-testid*='first-name' i]", p["first_name"]),
            ("input[name*='lastName' i], input[id*='lastName' i], input[data-testid*='last-name' i]", p["last_name"]),
            ("input[name*='email' i], input[id*='email' i], input[type='email']", p["email"]),
            ("input[name*='phone' i], input[id*='phone' i], input[type='tel']", p["phone"]),
            ("input[name*='address' i], input[id*='address' i]", p["street_address"]),
            ("input[name*='city' i], input[id*='city' i]", p["city"]),
            ("input[name*='zip' i], input[id*='zip' i], input[name*='postal' i], input[id*='postal' i]", p["zip_code"]),
            ("input[name*='linkedin' i], input[id*='linkedin' i]", p["linkedin"]),
            ("input[name*='github' i], input[id*='github' i]", p["github"]),
            ("input[name*='website' i], input[id*='website' i]", p["portfolio"] or p["github"]),
        ]

        for ctx in contexts:
            for selector, value in tesla_mappings:
                if not value:
                    continue
                try:
                    elems = ctx.query_selector_all(selector)
                    for elem in elems:
                        if elem.is_visible() and not (elem.input_value() or "").strip():
                            elem.fill(value)
                            filled += 1
                            ctx.evaluate("(el) => { el.style.outline = '2px solid #22c55e'; el.style.backgroundColor = '#f0fdf4'; }", elem)
                            break
                except Exception:
                    pass

        return filled

    def fill_generic_heuristics(self, page: Page) -> int:
        """Universal heuristic matcher for standard and modern form fields across all frames."""
        p = self.profile
        filled = 0
        contexts = self._get_all_contexts(page)

        patterns: List[Tuple[re.Pattern, str]] = [
            (re.compile(r"\b(first\s*name|fname|given\s*name|forename)\b", re.I), p["first_name"]),
            (re.compile(r"\b(last\s*name|lname|surname|family\s*name)\b", re.I), p["last_name"]),
            (re.compile(r"\b(full\s*name|^name$|applicant\s*name|your\s*name)\b", re.I), p["full_name"]),
            (re.compile(r"\b(e-?mail|email\s*address|useremail)\b", re.I), p["email"]),
            (re.compile(r"\b(phone|mobile|cell|telephone|contact\s*num)\b", re.I), p["phone"]),
            (re.compile(r"\b(birth\s*date|dob|date\s*of\s*birth|birthday)\b", re.I), p.get("dob_picker") or p["dob_formatted"]),
            (re.compile(r"\b(current\s*address|home\s*address|street\s*address|address\s*line\s*1|address1|address)\b", re.I), p.get("full_address") or p["street_address"]),
            (re.compile(r"\b(address\s*line\s*2|address2|suite|apt|apartment|unit)\b", re.I), p["address_line2"]),
            (re.compile(r"\b(city|town|municipality)\b", re.I), p["city"]),
            (re.compile(r"\b(state|province|region)\b", re.I), p["state"]),
            (re.compile(r"\b(zip\s*code|postal\s*code|postcode|zip)\b", re.I), p["zip_code"]),
            (re.compile(r"\b(country)\b", re.I), p["country"]),
            (re.compile(r"\b(university|school|college|institution|alma\s*mater)\b", re.I), p["university"]),
            (re.compile(r"\b(major|discipline|field\s*of\s*study|degree\s*subject|program)\b", re.I), p["major"]),
            (re.compile(r"\b(degree|education\s*level)\b", re.I), p["degree"]),
            (re.compile(r"\b(gpa|grade\s*point)\b", re.I), p["gpa"]),
            (re.compile(r"\b(grad\s*date|grad\s*year|expected\s*grad|graduation)\b", re.I), p["graduation_date"] or p["graduation_year"]),
            (re.compile(r"\b(linkedin)\b", re.I), p["linkedin"]),
            (re.compile(r"\b(github)\b", re.I), p["github"]),
            (re.compile(r"\b(portfolio|personal\s*website|website|homepage)\b", re.I), p["portfolio"] or p["github"]),
            (re.compile(r"\b(referral|how\s*did\s*you\s*hear|source)\b", re.I), "LinkedIn"),
        ]

        for ctx in contexts:
            # 1. Text Inputs and Textareas
            try:
                inputs = ctx.query_selector_all("input:not([type='hidden']):not([type='file']):not([type='checkbox']):not([type='radio']):not([type='submit']):not([type='button']), textarea")
                for inp in inputs:
                    try:
                        context = self._get_element_label_and_context(ctx, inp)
                        if not context:
                            continue

                        is_dob = bool(re.search(r"(date\s*of\s*birth|dateofbirth|\bbirth\b|\bdob\b|\bbirthday\b)", context, re.I))

                        current_val = inp.input_value()
                        if current_val and current_val.strip() and not is_dob:
                            continue

                        if is_dob:
                            inp_type = inp.get_attribute("type") or "text"
                            if inp_type == "date":
                                inp.fill(p.get("dob_dash", "2007-01-12"))
                            else:
                                dob_val = p.get("dob_picker", "12 Jan 2007")
                                try:
                                    inp.click()
                                    page.keyboard.press("Control+A")
                                    page.keyboard.type(dob_val)
                                    page.keyboard.press("Enter")
                                except Exception:
                                    inp.fill(dob_val)
                            filled += 1
                            ctx.evaluate("(el) => { el.style.outline = '2px solid #22c55e'; el.style.backgroundColor = '#f0fdf4'; }", inp)
                            continue

                        for pattern, value in patterns:
                            if not value:
                                continue
                            if pattern.search(context):
                                inp.fill(value)
                                filled += 1
                                ctx.evaluate("(el) => { el.style.outline = '2px solid #22c55e'; el.style.backgroundColor = '#f0fdf4'; }", inp)
                                break
                    except Exception:
                        pass
            except Exception:
                pass

            # 2. Native Select Dropdowns
            try:
                selects = ctx.query_selector_all("select")
                for sel in selects:
                    try:
                        context = self._get_element_label_and_context(ctx, sel)
                        if not context:
                            continue

                        # Gender
                        if re.search(r"\b(gender|sex)\b", context, re.I) and p["gender"]:
                            for opt in sel.query_selector_all("option"):
                                if p["gender"].lower() in (opt.text_content() or "").lower():
                                    sel.select_option(value=opt.get_attribute("value") or opt.text_content())
                                    filled += 1
                                    break

                        # Race / Ethnicity
                        elif re.search(r"\b(race|ethnicity)\b", context, re.I) and p["race_ethnicity"]:
                            for opt in sel.query_selector_all("option"):
                                if p["race_ethnicity"].lower() in (opt.text_content() or "").lower():
                                    sel.select_option(value=opt.get_attribute("value") or opt.text_content())
                                    filled += 1
                                    break

                        # Veteran Status
                        elif re.search(r"\b(veteran)\b", context, re.I):
                            for opt in sel.query_selector_all("option"):
                                txt = (opt.text_content() or "").lower()
                                if "not a" in txt or "not protected" in txt or "no" in txt or "i am not" in txt:
                                    sel.select_option(value=opt.get_attribute("value") or opt.text_content())
                                    filled += 1
                                    break

                        # Disability Status
                        elif re.search(r"\b(disability)\b", context, re.I):
                            for opt in sel.query_selector_all("option"):
                                txt = (opt.text_content() or "").lower()
                                if "do not have" in txt or "no" in txt:
                                    sel.select_option(value=opt.get_attribute("value") or opt.text_content())
                                    filled += 1
                                    break

                        # Work authorization
                        elif re.search(r"\b(authorized|eligible|work\s*auth)\b", context, re.I):
                            for opt in sel.query_selector_all("option"):
                                txt = (opt.text_content() or "").lower()
                                if p["authorized_in_us"].lower() == "yes" and "yes" in txt:
                                    sel.select_option(value=opt.get_attribute("value") or opt.text_content())
                                    filled += 1
                                    break

                        # Sponsorship
                        elif re.search(r"\b(sponsorship|require.*sponsor|visa)\b", context, re.I):
                            for opt in sel.query_selector_all("option"):
                                txt = (opt.text_content() or "").lower()
                                if p["requires_sponsorship"].lower() == "no" and "no" in txt:
                                    sel.select_option(value=opt.get_attribute("value") or opt.text_content())
                                    filled += 1
                                    break

                        # State
                        elif re.search(r"\b(state|province)\b", context, re.I):
                            for opt in sel.query_selector_all("option"):
                                txt = (opt.text_content() or "").lower()
                                val = (opt.get_attribute("value") or "").lower()
                                if p["state"].lower() == val or p["state_full"].lower() in txt:
                                    sel.select_option(value=opt.get_attribute("value") or opt.text_content())
                                    filled += 1
                                    break

                        # Degree
                        elif re.search(r"\b(degree|education\s*level)\b", context, re.I):
                            for opt in sel.query_selector_all("option"):
                                txt = (opt.text_content() or "").lower()
                                if "bachelor" in txt or "bs" in txt or "undergraduate" in txt:
                                    sel.select_option(value=opt.get_attribute("value") or opt.text_content())
                                    filled += 1
                                    break
                    except Exception:
                        pass
            except Exception:
                pass

            # 3. Custom Dropdowns / ARIA Comboboxes (Modern SPAs, Workday, Ashby, React-Select)
            try:
                combos = ctx.query_selector_all("div[role='combobox'], button[aria-haspopup='listbox'], div[class*='select__control'], div[data-automation-id*='select']")
                for combo in combos:
                    try:
                        context = self._get_element_label_and_context(ctx, combo)
                        if not context:
                            continue

                        target_val = None
                        if re.search(r"\b(state|province)\b", context, re.I):
                            target_val = p["state_full"]
                        elif re.search(r"\b(country)\b", context, re.I):
                            target_val = "United States"
                        elif re.search(r"\b(gender)\b", context, re.I):
                            target_val = "Male"
                        elif re.search(r"\b(authorized|work\s*auth)\b", context, re.I):
                            target_val = "Yes"
                        elif re.search(r"\b(sponsorship)\b", context, re.I):
                            target_val = "No"

                        if target_val:
                            combo.click()
                            time.sleep(0.3)
                            page.keyboard.type(target_val)
                            time.sleep(0.2)
                            page.keyboard.press("Enter")
                            filled += 1
                    except Exception:
                        pass
            except Exception:
                pass

            # 4. Radio Buttons
            try:
                radios = ctx.query_selector_all("input[type='radio']")
                for r in radios:
                    context = self._get_element_label_and_context(ctx, r)
                    own_label = ctx.evaluate("""(r) => {
                        let text = '';
                        if (r.value) text += ' ' + r.value;
                        if (r.id) {
                            let l = document.querySelector(`label[for="${r.id}"]`);
                            if (l) text += ' ' + l.innerText;
                        }
                        let parentLabel = r.closest('label');
                        if (parentLabel) text += ' ' + parentLabel.innerText;
                        return text.toLowerCase();
                    }""", r)

                    def check_radio(radio_el):
                        try:
                            radio_el.check(force=True)
                        except Exception:
                            ctx.evaluate("(el) => el.click()", radio_el)

                    # Work auth YES
                    if re.search(r"\b(authorized|eligible\s*to\s*work)\b", context, re.I) and "yes" in own_label:
                        check_radio(r)
                        filled += 1
                    # Sponsorship NO
                    elif re.search(r"\b(sponsorship|require.*sponsor|visa)\b", context, re.I) and "no" in own_label:
                        check_radio(r)
                        filled += 1
                    # 18+ YES
                    elif re.search(r"\b(18|age)\b", context, re.I) and "yes" in own_label:
                        check_radio(r)
                        filled += 1
                    # Previous employee NO
                    elif re.search(r"\b(previously\s*employed|worked\s*for|former\s*employee)\b", context, re.I) and "no" in own_label:
                        check_radio(r)
                        filled += 1
                    # Gender Male/Female
                    elif re.search(r"\b(gender|sex)\b", context, re.I):
                        if p["gender"].lower() in own_label and (p["gender"].lower() != "male" or "female" not in own_label):
                            check_radio(r)
                            filled += 1
                    # Hispanic / Latino NO
                    elif re.search(r"\b(hispanic|latino)\b", context, re.I) and "no" in own_label:
                        check_radio(r)
                        filled += 1
                    # Veteran NO
                    elif re.search(r"\b(veteran)\b", context, re.I) and ("not a" in own_label or "no" in own_label or "i am not" in own_label):
                        check_radio(r)
                        filled += 1
                    # Disability NO
                    elif re.search(r"\b(disability)\b", context, re.I) and ("do not have" in own_label or "no" in own_label):
                        check_radio(r)
                        filled += 1
            except Exception:
                pass

            # 5. Consent & Legal Checkboxes
            try:
                checkboxes = ctx.query_selector_all("input[type='checkbox']")
                for cb in checkboxes:
                    context = self._get_element_label_and_context(ctx, cb)
                    if any(k in context for k in ["agree", "consent", "acknowledge", "certify", "privacy", "terms", "policy", "terms of use"]):
                        if not cb.is_checked():
                            cb.check(force=True)
                            filled += 1
            except Exception:
                pass

        return filled

    def autofill_page(self, url: str) -> Dict[str, Any]:
        """Open application page, autofill all personal info, and upload resume."""
        ats_type = detect_ats(url)
        console.print(f"\n[bold cyan]>> Opening application URL:[/bold cyan] {url}")
        console.print(f"     ATS Detected: [bold yellow]{ats_type.upper()}[/bold yellow]")

        results = {
            "url": url,
            "ats_type": ats_type,
            "fields_filled": 0,
            "resume_uploaded": False,
            "status": "IN_PROGRESS"
        }

        with sync_playwright() as p:
            browser_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
            ]
            launch_kwargs = {
                "headless": self.headless,
                "slow_mo": 60 if not self.headless else 0,
                "args": browser_args,
                "ignore_default_args": ["--enable-automation"]
            }
            mac_chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            linux_chrome = "/usr/bin/google-chrome"
            if os.path.exists(linux_chrome):
                launch_kwargs["executable_path"] = linux_chrome
            elif os.path.exists(mac_chrome):
                launch_kwargs["executable_path"] = mac_chrome

            browser = p.chromium.launch(**launch_kwargs)
            ua = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                if sys.platform == "darwin"
                else "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            )
            context = browser.new_context(
                viewport={"width": 1366, "height": 850},
                user_agent=ua
            )
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                console.print("[dim][*] Navigating to application page...[/dim]")
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                time.sleep(2)

                # Check security challenges / bot protection
                page_title = page.title()
                if "Access Denied" in page_title or "Security Check" in page_title:
                    console.print("\n[yellow][WARN] Bot/Security Verification Detected.[/yellow]")
                    console.print("    Please solve any visible CAPTCHA or verification challenge in the browser window.")
                    time.sleep(4)

                # 1. Upload Resume
                resume_uploaded = self.upload_resume(page)
                results["resume_uploaded"] = resume_uploaded
                time.sleep(1)

                # 2. Run ATS-Specific Form Engines
                fields_count = 0
                url_lower = url.lower()
                if "greenhouse.io" in url_lower or "gh_jid" in url_lower:
                    fields_count += self.fill_greenhouse_form(page)
                elif "lever.co" in url_lower:
                    fields_count += self.fill_lever_form(page)
                elif "ashbyhq.com" in url_lower:
                    fields_count += self.fill_ashby_form(page)
                elif "myworkdayjobs.com" in url_lower or "workday" in url_lower:
                    fields_count += self.fill_workday_form(page)
                elif "smartrecruiters.com" in url_lower:
                    fields_count += self.fill_smartrecruiters_form(page)
                elif "tesla.com" in url_lower:
                    fields_count += self.fill_tesla_form(page)

                # 3. Run Universal Heuristic Matcher
                fields_count += self.fill_generic_heuristics(page)
                results["fields_filled"] = fields_count

                console.print(f"[bold green][OK] Successfully autofilled {fields_count} fields.[/bold green]")
                if resume_uploaded:
                    console.print("[bold green][OK] Resume PDF attached successfully.[/bold green]")
                else:
                    console.print("[yellow][WARN] Resume file input not detected or requires manual attachment.[/yellow]")

                # Inject HUD badge
                self._inject_status_banner(page, fields_count, resume_uploaded, ats_type=ats_type)

                if not self.headless:
                    console.print("\n" + "-" * 60)
                    console.print("[bold cyan]BROWSER READY FOR REVIEW & SUBMISSION[/bold cyan]")
                    console.print("1. Review the populated fields (highlighted in green).")
                    console.print("2. Fill any unique custom essay / screening questions.")
                    console.print("3. Click [bold green]'Submit Application'[/bold green] when ready.")
                    console.print("-" * 60)
                    try:
                        input("\nPress [Enter] in this terminal once you finish submitting to close browser...")
                    except (KeyboardInterrupt, EOFError):
                        pass

                results["status"] = "COMPLETED"

            except Exception as e:
                console.print(f"[red][ERROR] Error during autofill execution: {e}[/red]")
                results["status"] = "ERROR"
                results["error"] = str(e)
                if not self.headless:
                    try:
                        input("\nPress [Enter] to close browser...")
                    except (KeyboardInterrupt, EOFError):
                        pass
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

        return results

    def run_feeder_loop(self, initial_urls: Optional[List[str]] = None, parse_mode: bool = False) -> None:
        """
        Continuous Link Feeder & Parse Mode:
        Takes URLs interactively (or from a pre-loaded list/GitHub repo).
        In Parse Mode, reads back a short preview list of internships from the link(s) without opening the browser.
        """
        scraper = InternshipScraper(self.db)
        queue: List[str] = list(initial_urls) if initial_urls else []

        mode_badge = "[bold magenta]Mode: PARSE & PREVIEW (no browser)[/bold magenta]" if parse_mode else "[bold cyan]Mode: LIVE AUTOFILL & FEED[/bold cyan]"

        console.print(Panel(
            Text("LINK FEEDER & PARSE MODE\n", style="bold cyan") +
            Text("Feed direct job URLs or GitHub repository links.\n", style="white") +
            Text("- Paste any career URL (Greenhouse, Lever, Workday, Ashby, etc.) to autofill.\n", style="dim") +
            Text("- Paste a GitHub repo (e.g. Summer2027-Internships) to parse Hardware & SWE jobs.\n", style="dim") +
            Text("- Paste multiple links at once (separated by space or newline).\n", style="dim") +
            Text("- Type 'parse' to toggle Parse-Only preview mode ON/OFF.\n", style="dim") +
            Text("- Enter 'q' at any time to return.", style="italic yellow"),
            subtitle=mode_badge,
            border_style="cyan", padding=(1, 2)
        ))

        while True:
            if not queue:
                prompt_label = "[bold magenta]Paste link(s) to parse/preview[/bold magenta]" if parse_mode else "[bold green]Paste link(s)[/bold green]"
                console.print(f"\n[bold cyan]Feed URL(s), GitHub repository link, or command:[/bold cyan] (Type 'parse' to toggle mode, 'q' to quit)")
                user_input = Prompt.ask(prompt_label, default="q").strip()

                if not user_input or user_input.lower() == 'q':
                    console.print("[yellow]Exiting Link Feeder.[/yellow]")
                    break

                if user_input.lower() == 'parse':
                    parse_mode = not parse_mode
                    state_str = "[bold magenta]ENABLED (preview only, no browser auto-launch)[/bold magenta]" if parse_mode else "[bold cyan]DISABLED (live autofill)[/bold cyan]"
                    console.print(f">> Parse Mode is now {state_str}")
                    continue

                explicit_parse = False
                if user_input.lower().startswith("parse "):
                    explicit_parse = True
                    user_input = user_input[6:].strip()

                # Check if input is a text file path
                if os.path.isfile(user_input):
                    with open(user_input, "r", encoding="utf-8") as f:
                        lines = [line.strip() for line in f if line.strip() and line.strip().startswith("http")]
                    queue.extend(lines)
                    console.print(f"[green][OK] Loaded {len(lines)} links from file: {user_input}[/green]")
                    continue

                # Extract all URLs from input
                found_urls = re.findall(r"https?://[^\s\"'>]+", user_input)
                if not found_urls:
                    console.print("[red]No valid URLs detected. Please paste a full http:// or https:// URL.[/red]")
                    continue

                # Check if user fed a GitHub repo link
                first_url = found_urls[0]
                if "github.com" in first_url:
                    console.print(f"\n[bold magenta]>> Detected GitHub repository link:[/bold magenta] {first_url}")
                    with console.status("[cyan]Fetching repository listings...[/cyan]"):
                        extracted_jobs = scraper.scrape_github_repo(first_url)

                    if not extracted_jobs:
                        console.print("[yellow][WARN] No internship listings could be extracted from this GitHub repo.[/yellow]")
                        continue

                    # Index into database
                    scraper.db.upsert_jobs_batch(extracted_jobs)
                    hw_jobs = [j for j in extracted_jobs if j["category"] == "chip_design"]
                    swe_jobs = [j for j in extracted_jobs if j["category"] == "software_dev"]
                    ai_jobs = [j for j in extracted_jobs if j["category"] == "ai_ml"]

                    console.print(f"[bold green][OK] Successfully extracted {len(extracted_jobs)} internships from repository.[/bold green]")
                    console.print(f"  - Hardware/Chip Design : [bold yellow]{len(hw_jobs)}[/bold yellow]")
                    console.print(f"  - Software Development : [bold green]{len(swe_jobs)}[/bold green]")
                    console.print(f"  - AI / Machine Learning : [bold magenta]{len(ai_jobs)}[/bold magenta]")

                    # Read back short list of internships
                    self.display_jobs_preview(
                        extracted_jobs[:8], 
                        title=f"Parsed Internships Preview (Top 8 of {len(extracted_jobs)})"
                    )

                    is_preview_mode = parse_mode or explicit_parse
                    if is_preview_mode:
                        while True:
                            console.print("\n[bold cyan]Parse Mode Actions:[/bold cyan]")
                            console.print("  [1] Read back Hardware / Chip Design roles")
                            console.print("  [2] Read back Software Development roles")
                            console.print("  [3] Read back AI / Machine Learning roles")
                            console.print("  [4] Export roles to text file")
                            console.print("  [5] Queue roles to autofill now")
                            console.print("  [6] Done (paste next link)")
                            p_act = Prompt.ask("Select action", choices=["1", "2", "3", "4", "5", "6"], default="1")
                            if p_act == "1":
                                self.display_jobs_preview(hw_jobs[:15], title=f"Hardware / Chip Design Roles (Top {min(15, len(hw_jobs))} of {len(hw_jobs)})", max_rows=15)
                            elif p_act == "2":
                                self.display_jobs_preview(swe_jobs[:15], title=f"Software Development Roles (Top {min(15, len(swe_jobs))} of {len(swe_jobs)})", max_rows=15)
                            elif p_act == "3":
                                self.display_jobs_preview(ai_jobs[:15], title=f"AI / Machine Learning Roles (Top {min(15, len(ai_jobs))} of {len(ai_jobs)})", max_rows=15)
                            elif p_act == "4":
                                exp_choice = Prompt.ask("Export which track?", choices=["hardware", "swe", "ai_ml", "all"], default="hardware")
                                exp_jobs = hw_jobs if exp_choice == "hardware" else swe_jobs if exp_choice == "swe" else ai_jobs if exp_choice == "ai_ml" else extracted_jobs
                                fname = Prompt.ask("Output file name", default=f"{exp_choice}_internships.txt")
                                scraper.export_links_to_file(exp_jobs, fname)
                                console.print(f"[green][OK] Exported {len(exp_jobs)} listings to {fname}[/green]")
                            elif p_act == "5":
                                cat_choice = Prompt.ask("Which track to queue for applying?", choices=["hardware", "swe", "ai_ml", "all"], default="hardware")
                                target_jobs = hw_jobs if cat_choice == "hardware" else swe_jobs if cat_choice == "swe" else ai_jobs if cat_choice == "ai_ml" else extracted_jobs
                                limit_ask = Prompt.ask(f"How many to queue from {len(target_jobs)} jobs? (or 'all')", default="10")
                                limit_n = len(target_jobs) if limit_ask.lower() == "all" else int(limit_ask)
                                queue.extend([j["url"] for j in target_jobs[:limit_n]])
                                console.print(f"[bold green]Queued {len(queue)} jobs for autofill![/bold green]")
                                break
                            elif p_act == "6":
                                break
                        if not queue:
                            continue
                    else:
                        action = Prompt.ask(
                            "Action", 
                            choices=["parse_only", "apply_hardware", "apply_swe", "apply_ai", "apply_all", "export", "cancel"], 
                            default="apply_hardware"
                        )
                        if action == "cancel":
                            continue
                        elif action == "parse_only":
                            cat_choice = Prompt.ask("Read back which track?", choices=["hardware", "swe", "ai_ml", "all"], default="hardware")
                            target_jobs = hw_jobs if cat_choice == "hardware" else swe_jobs if cat_choice == "swe" else ai_jobs if cat_choice == "ai_ml" else extracted_jobs
                            self.display_jobs_preview(target_jobs[:15], title=f"{cat_choice.upper()} Preview (Top {min(15, len(target_jobs))})", max_rows=15)
                            if Confirm.ask("Queue these for autofill?", default=False):
                                limit_ask = Prompt.ask(f"How many to queue? (or 'all')", default="10")
                                limit_n = len(target_jobs) if limit_ask.lower() == "all" else int(limit_ask)
                                queue.extend([j["url"] for j in target_jobs[:limit_n]])
                                console.print(f"[bold green]Queued {len(queue)} jobs for autofill![/bold green]")
                            continue
                        elif action == "export":
                            exp_choice = Prompt.ask("Export which track?", choices=["hardware", "swe", "ai_ml", "all"], default="hardware")
                            exp_jobs = hw_jobs if exp_choice == "hardware" else swe_jobs if exp_choice == "swe" else ai_jobs if exp_choice == "ai_ml" else extracted_jobs
                            fname = Prompt.ask("Output file name", default=f"{exp_choice}_internships.txt")
                            scraper.export_links_to_file(exp_jobs, fname)
                            console.print(f"[green][OK] Exported {len(exp_jobs)} listings to {fname}[/green]")
                            continue
                        else:
                            if action == "apply_hardware":
                                target_jobs = hw_jobs
                            elif action == "apply_swe":
                                target_jobs = swe_jobs
                            elif action == "apply_ai":
                                target_jobs = ai_jobs
                            else:
                                target_jobs = extracted_jobs

                            limit_ask = Prompt.ask(f"How many to queue from {len(target_jobs)} jobs? (or 'all')", default="10")
                            limit_n = len(target_jobs) if limit_ask.lower() == "all" else int(limit_ask)
                            queue.extend([j["url"] for j in target_jobs[:limit_n]])
                            console.print(f"[bold green]Queued {len(queue)} jobs for autofill![/bold green]")
                            continue

                # Direct Career Links:
                preview_items = []
                for u in found_urls:
                    db_job = self.db.get_job_by_url(u)
                    ats = detect_ats(u)
                    if db_job:
                        preview_items.append(db_job)
                    else:
                        parsed_netloc = urlparse(u).netloc
                        comp_name = parsed_netloc.split(".")[0].capitalize() if parsed_netloc else "Direct Link"
                        preview_items.append({
                            "company": comp_name,
                            "title": "Application Form",
                            "category": "direct_feed",
                            "location": "Online",
                            "ats_type": ats,
                            "url": u
                        })

                # Read back short list of pasted URLs
                self.display_jobs_preview(preview_items, title=f"Pasted Link(s) Read-Back ({len(found_urls)} detected)")

                if parse_mode or explicit_parse:
                    if not Confirm.ask(f"Queue these {len(found_urls)} link(s) for autofill now?", default=False):
                        continue

                queue.extend(found_urls)

            # Process next URL in queue
            current_url = queue.pop(0)
            console.print(f"\n[bold]------------------------------------------------------------[/bold]")
            console.print(f"[bold cyan]Queue Status: {len(queue)} remaining | Current Target:[/bold cyan] {current_url}")
            
            existing = self.db.get_job_by_url(current_url)
            if existing:
                console.print(f"Company: [bold white]{existing['company']}[/bold white] | Role: [bold white]{existing['title']}[/bold white] | Status: {existing['status']}")

            res = self.autofill_page(current_url)

            if res.get("status") == "COMPLETED":
                was_submitted = Confirm.ask("Did you submit this application?", default=True)
                if was_submitted:
                    if existing:
                        self.db.update_job_status(current_url, "APPLIED")
                    else:
                        comp = Prompt.ask("Company Name (optional)", default="Company")
                        role = Prompt.ask("Role Title (optional)", default="Summer Intern")
                        self.db.upsert_job({
                            "company": comp,
                            "title": role,
                            "category": "other",
                            "terms": ["Summer 2027"],
                            "url": current_url,
                            "status": "APPLIED"
                        })
                    console.print("[bold green][OK] Application recorded in database as APPLIED![/bold green]")
            elif res.get("status") == "ERROR":
                console.print(f"[red]Error during autofill: {res.get('error')}[/red]")

            if queue:
                cont = Confirm.ask(f"Proceed to next queued link ({len(queue)} left)?", default=True)
                if not cont:
                    queue.clear()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="High-Precision Form Auto-Filler, Parser & Continuous Link Feeder")
    parser.add_argument("urls", nargs="*", help="Job Application URLs or GitHub repo to autofill or parse")
    parser.add_argument("--feed", action="store_true", help="Launch interactive continuous Link Feeder mode")
    parser.add_argument("--parse", action="store_true", help="Parse mode: read back a short preview list of internships from pasted URLs/GitHub repos without launching browser")
    parser.add_argument("--headless", action="store_true", help="Run browser headlessly")
    args = parser.parse_args()

    filler = FormAutoFiller(headless=args.headless)

    if args.feed or not args.urls:
        filler.run_feeder_loop(initial_urls=args.urls if args.urls else None, parse_mode=args.parse)
    else:
        filler.run_feeder_loop(initial_urls=args.urls, parse_mode=args.parse)
