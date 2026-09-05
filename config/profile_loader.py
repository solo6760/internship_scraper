import json
import os
from typing import Dict, Any, Optional

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "profile.json")

def load_profile(path: Optional[str] = None) -> Dict[str, Any]:
    """Load profile configuration from JSON file."""
    config_file = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(config_file):
        template_file = os.path.join(os.path.dirname(config_file), "profile.template.json")
        if os.path.exists(template_file):
            config_file = template_file
        else:
            raise FileNotFoundError(f"Profile configuration file not found at: {config_file}")
    
    with open(config_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

def save_profile(profile: Dict[str, Any], path: Optional[str] = None) -> None:
    """Save profile configuration to JSON file."""
    config_file = path or DEFAULT_CONFIG_PATH
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)

def get_flattened_profile(profile: Dict[str, Any]) -> Dict[str, str]:
    """Flattens profile into simple key-value pairs for quick lookup."""
    personal = profile.get("personal", {})
    bday = personal.get("birthday", {})
    addr = personal.get("address", {})
    edu = profile.get("education", {})
    links = profile.get("links", {})
    auth = profile.get("work_authorization", {})
    demo = profile.get("demographics", {})
    docs = profile.get("documents", {})

    street_parts = [addr.get("street", ""), addr.get("line2", "")]
    street_str = " ".join(p for p in street_parts if p).strip()
    city_state_zip = f"{addr.get('city', '')}, {addr.get('state', '')} {addr.get('zip_code', '')}".strip(", ")
    full_addr = f"{street_str}, {city_state_zip}".strip(", ") if street_str and street_str != addr.get('city') else city_state_zip

    resume_candidate = docs.get("resume_path", "")
    if not resume_candidate or not os.path.exists(resume_candidate):
        # Dynamically scan data/ directory for any PDF resume
        data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
        if os.path.exists(data_dir):
            for fname in sorted(os.listdir(data_dir)):
                if fname.lower().endswith(".pdf"):
                    resume_candidate = os.path.join(data_dir, fname)
                    break

    return {
        "first_name": personal.get("first_name", ""),
        "last_name": personal.get("last_name", ""),
        "full_name": personal.get("full_name", f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip()),
        "email": personal.get("email", ""),
        "phone": personal.get("phone", ""),
        "dob_month": bday.get("month", ""),
        "dob_day": bday.get("day", ""),
        "dob_year": bday.get("year", ""),
        "dob_formatted": bday.get("formatted_slash", ""),
        "dob_dash": bday.get("formatted_dash", ""),
        "dob_picker": bday.get("formatted_picker", f"{bday.get('day', '12')} Jan {bday.get('year', '2007')}"),
        "street_address": addr.get("street", ""),
        "address_line2": addr.get("line2", ""),
        "city": addr.get("city", ""),
        "state": addr.get("state", ""),
        "state_full": addr.get("state_full", ""),
        "zip_code": addr.get("zip_code", ""),
        "country": addr.get("country", "United States"),
        "full_address": full_addr,
        "university": edu.get("university", ""),
        "degree": edu.get("degree", ""),
        "major": edu.get("major", ""),
        "minor": edu.get("minor", ""),
        "gpa": edu.get("gpa", ""),
        "graduation_year": edu.get("graduation_year", ""),
        "graduation_month": edu.get("graduation_month", ""),
        "graduation_date": edu.get("graduation_date_formatted", ""),
        "linkedin": links.get("linkedin", ""),
        "github": links.get("github", ""),
        "portfolio": links.get("portfolio", ""),
        "twitter": links.get("twitter", ""),
        "authorized_in_us": auth.get("authorized_in_us", "Yes"),
        "requires_sponsorship": auth.get("requires_sponsorship", "No"),
        "requires_sponsorship_future": auth.get("requires_sponsorship_future", "No"),
        "citizenship_status": auth.get("citizenship_status", "Citizen"),
        "is_18_or_older": auth.get("is_18_or_older", "Yes"),
        "previously_employed": auth.get("previously_employed", "No"),
        "gender": demo.get("gender", "Male"),
        "race_ethnicity": demo.get("race_ethnicity", "Asian"),
        "hispanic_latino": demo.get("hispanic_latino", "No"),
        "veteran_status": demo.get("veteran_status", "I am not a protected veteran"),
        "disability_status": demo.get("disability_status", "No, I do not have a disability"),
        "resume_path": resume_candidate,
        "cover_letter_path": docs.get("cover_letter_path", "")
    }
