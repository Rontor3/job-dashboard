"""Hybrid per-company classifier: dictionary first, LLM fallback, vocab-constrained.
Never raises — any LLM failure / off-vocab output degrades to Other.
"""
from __future__ import annotations

INDUSTRIES = (
    "BFSI", "Insurance", "Fintech", "Consulting & IT Services",
    "IT/Software & SaaS", "AI/ML & Data Platforms", "Healthcare & Pharma",
    "Life Sciences & Scientific", "Retail & E-commerce",
    "Food, Delivery & Q-commerce", "Media/Gaming/Entertainment", "Telecom",
    "Semiconductors & Hardware", "Manufacturing & Industrial",
    "Automotive & Mobility", "Defense & Aerospace",
    "Engineering & Infrastructure", "EdTech", "Energy & Utilities",
    "Travel & Hospitality", "Real Estate & PropTech",
    "Consumer & Local Services", "Public Sector", "Other",
)
COMPANY_TYPES = (
    "Product", "Services/Consultancy", "GCC/Captive", "Startup",
    "Staffing/Agency", "AI Lab/Research", "Other",
)

# Substring key (lower) -> (industry, company_type). Keep specific/longer keys
# first; matching iterates in this order and takes the first hit.
COMPANY_DICT = {
    "tata consultancy": ("Consulting & IT Services", "Services/Consultancy"),
    "accenture": ("Consulting & IT Services", "Services/Consultancy"),
    "capgemini": ("Consulting & IT Services", "Services/Consultancy"),
    "cognizant": ("Consulting & IT Services", "Services/Consultancy"),
    "infosys": ("Consulting & IT Services", "Services/Consultancy"),
    "wipro": ("Consulting & IT Services", "Services/Consultancy"),
    "hcltech": ("Consulting & IT Services", "Services/Consultancy"),
    "deloitte": ("Consulting & IT Services", "Services/Consultancy"),
    "persistent systems": ("IT/Software & SaaS", "Services/Consultancy"),
    "ntt data": ("Consulting & IT Services", "Services/Consultancy"),
    "ust": ("Consulting & IT Services", "Services/Consultancy"),
    "eclerx": ("Consulting & IT Services", "Services/Consultancy"),
    "exl": ("Consulting & IT Services", "Services/Consultancy"),
    "quantiphi": ("AI/ML & Data Platforms", "AI Lab/Research"),
    "mistral": ("AI/ML & Data Platforms", "AI Lab/Research"),
    "jpmorgan": ("BFSI", "Other"),
    "barclays": ("BFSI", "Other"),
    "natwest": ("BFSI", "Other"),
    "mastercard": ("BFSI", "Product"),
    "ameriprise": ("BFSI", "Other"),
    "nvidia": ("Semiconductors & Hardware", "Product"),
    "netflix": ("Media/Gaming/Entertainment", "Product"),
    "reddit": ("Media/Gaming/Entertainment", "Product"),
    "thermo fisher": ("Life Sciences & Scientific", "Product"),
    "husky injection": ("Manufacturing & Industrial", "Product"),
    "general dynamics": ("Defense & Aerospace", "Services/Consultancy"),
    "walmart": ("Retail & E-commerce", "Product"),
    "amazon": ("Retail & E-commerce", "Product"),
    "google": ("IT/Software & SaaS", "Product"),
    "microsoft": ("IT/Software & SaaS", "Product"),
    "adobe": ("IT/Software & SaaS", "Product"),
    "humana": ("Healthcare & Pharma", "Product"),
    "talabat": ("Food, Delivery & Q-commerce", "Product"),
}

_LLM_PROMPT = (
    "Classify the company into EXACTLY one Industry and one Company-type from "
    "the allowed lists. Reply with two lines and nothing else:\n"
    "Industry: <one of the industries>\nCompany-type: <one of the types>\n\n"
    "Industries: {industries}\nCompany-types: {types}\n\n"
    "Company: {company}\nExample role: {title}\nContext: {desc}\n"
)


def _dict_lookup(company_key):
    for key, pair in COMPANY_DICT.items():
        if key in company_key:
            return pair
    return None


def _parse_llm(text):
    industry, ctype = "Other", "Other"
    for line in (text or "").splitlines():
        low = line.lower()
        if low.startswith("industry:"):
            industry = line.split(":", 1)[1].strip()
        elif low.startswith("company-type:") or low.startswith("company type:"):
            ctype = line.split(":", 1)[1].strip()
    industry = industry if industry in INDUSTRIES else "Other"
    ctype = ctype if ctype in COMPANY_TYPES else "Other"
    return industry, ctype


def classify_company(company, sample_title="", sample_desc="", llm=None):
    key = (company or "").strip().lower()
    if not key:
        return ("Other", "Other", "other")
    hit = _dict_lookup(key)
    if hit:
        return (hit[0], hit[1], "dict")
    try:
        if llm is None:
            from job_dashboard.letter.draft import make_default_llm
            llm = make_default_llm()
        prompt = _LLM_PROMPT.format(
            industries=", ".join(INDUSTRIES), types=", ".join(COMPANY_TYPES),
            company=company, title=(sample_title or "")[:120], desc=(sample_desc or "")[:400])
        out = llm(prompt)
        industry, ctype = _parse_llm(out if isinstance(out, str) else "")
        return (industry, ctype, "llm")
    except Exception:
        return ("Other", "Other", "other")
