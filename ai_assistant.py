import os
import json
import requests
from typing import Optional, Dict, Any, List, Tuple
from rich.console import Console
from rich.prompt import Prompt, Confirm

console = Console()

DEFAULT_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
DEFAULT_OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"

class AIAssistant:
    def __init__(self, config_path: str = "config/profile.json"):
        self.config_path = config_path
        self.api_key: Optional[str] = None
        self.provider: str = "gemini"
        self._load_config()

    def _load_config(self) -> None:
        """Load API key from environment or local profile.json."""
        # 1. Check environment variables
        if os.environ.get("GEMINI_API_KEY"):
            self.api_key = os.environ.get("GEMINI_API_KEY")
            self.provider = "gemini"
            return
        if os.environ.get("OPENAI_API_KEY"):
            self.api_key = os.environ.get("OPENAI_API_KEY")
            self.provider = "openai"
            return

        # 2. Check profile.json
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                ai_settings = data.get("ai_settings", {})
                if ai_settings.get("api_key"):
                    self.api_key = ai_settings.get("api_key")
                    self.provider = ai_settings.get("provider", "gemini")
            except Exception:
                pass

    def prompt_user_for_key_if_missing(self) -> None:
        """Ask user for API key on first run if missing, and store in private profile.json."""
        if self.api_key:
            return

        console.print("\n[bold cyan]------------------------------------------------------------[/bold cyan]")
        console.print("[bold cyan]AI Assistant Setup (Screening Questions & Free Responses)[/bold cyan]")
        console.print("An API key (Gemini or OpenAI) allows the autofiller to intelligently answer")
        console.print("custom screening questions (availability, full-time interest, essay prompts).")
        console.print("[dim]Your key will be stored in private 'config/profile.json' (strictly git-ignored).[/dim]")
        
        want_ai = Confirm.ask("Would you like to configure an AI API key now?", default=True)
        if not want_ai:
            console.print("[yellow]Skipping AI setup. Form autofiller will run in standard heuristic mode.[/yellow]")
            console.print("[bold cyan]------------------------------------------------------------[/bold cyan]\n")
            return

        provider = Prompt.ask("Choose provider", choices=["gemini", "openai"], default="gemini")
        if provider == "gemini":
            console.print("[dim]Tip: You can get a free Gemini API key at https://aistudio.google.com/[/dim]")
        else:
            console.print("[dim]Tip: You can get an OpenAI key at https://platform.openai.com/api-keys[/dim]")

        key = Prompt.ask(f"Enter your {provider.upper()} API Key (or press Enter to skip)", default="").strip()
        if not key:
            console.print("[yellow]No key entered. Continuing in standard mode.[/yellow]")
            console.print("[bold cyan]------------------------------------------------------------[/bold cyan]\n")
            return

        self.api_key = key
        self.provider = provider

        # Save to local profile.json
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["ai_settings"] = {
                    "provider": provider,
                    "api_key": key
                }
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                console.print(f"[bold green][OK] Saved {provider.upper()} key to private config/profile.json[/bold green]")
            except Exception as e:
                console.print(f"[yellow]Could not write key to profile.json: {e}[/yellow]")

        console.print("[bold cyan]------------------------------------------------------------[/bold cyan]\n")

    def answer_question(self, question: str, profile_data: Dict[str, Any], options: Optional[List[str]] = None) -> Optional[str]:
        """
        Generate an accurate, concise answer to a job application question based on profile.
        """
        if not self.api_key:
            return None

        # Build candidate context
        cand_context = (
            f"Candidate: {profile_data.get('full_name', 'Student')}\n"
            f"School: {profile_data.get('university', 'Purdue University')}\n"
            f"Major: {profile_data.get('major', 'Computer Engineering')}\n"
            f"Degree: {profile_data.get('degree', 'Bachelor of Science')}\n"
            f"GPA: {profile_data.get('gpa', '3.80')}\n"
            f"Graduation: {profile_data.get('graduation_date', profile_data.get('graduation_year', 'May 2026'))}\n"
            f"US Work Authorized: {profile_data.get('work_auth', 'Yes')}\n"
            f"Requires Sponsorship: {profile_data.get('sponsorship', 'No')}\n"
            f"Target Position: Summer 2027 Internship / Co-op\n"
        )

        prompt = (
            f"You are helping the applicant answer a specific job application screening question.\n\n"
            f"APPLICANT PROFILE:\n{cand_context}\n\n"
            f"APPLICATION QUESTION:\n\"{question}\"\n\n"
        )

        if options:
            options_str = ", ".join(f"'{opt}'" for opt in options)
            prompt += (
                f"AVAILABLE OPTIONS: [{options_str}]\n"
                f"INSTRUCTIONS:\n"
                f"Select the single best option from the available list that accurately represents the candidate.\n"
                f"Return ONLY the exact option text without quotes or explanations.\n"
            )
        else:
            prompt += (
                f"INSTRUCTIONS:\n"
                f"1. Write a direct, professional, 1 to 2 sentence answer.\n"
                f"2. If asked about availability, readiness to start full-time after graduation, or willingness to take time off from school, answer affirmatively based on their graduation date ({profile_data.get('graduation_date', 'May 2026')}).\n"
                f"3. Do not include quotes, greetings, or meta-talk. Output only the exact text to paste into the form.\n"
            )

        try:
            if self.provider == "gemini":
                return self._call_gemini(prompt)
            else:
                return self._call_openai(prompt)
        except Exception as e:
            console.print(f"[dim][WARN] AI answer call failed: {e}[/dim]")
            return None

    def _call_gemini(self, prompt: str) -> Optional[str]:
        url = f"{DEFAULT_GEMINI_ENDPOINT}?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 200
            }
        }
        res = requests.post(url, headers=headers, json=payload, timeout=8)
        if res.status_code == 200:
            data = res.json()
            candidates = data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    return parts[0].get("text", "").strip().strip('"')
        return None

    def _call_openai(self, prompt: str) -> Optional[str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a professional assistant answering job application screening questions directly, truthfully, and concisely."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 200
        }
        res = requests.post(DEFAULT_OPENAI_ENDPOINT, headers=headers, json=payload, timeout=8)
        if res.status_code == 200:
            data = res.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip().strip('"')
        return None
