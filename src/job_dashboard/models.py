from dataclasses import dataclass
from typing import Optional


@dataclass
class JobListing:
    source: str
    title: str
    company: str
    job_url: str
    description: str
    location: Optional[str] = None
    external_id: Optional[str] = None
    job_type: Optional[str] = None
    is_remote: Optional[bool] = None
    salary_text: Optional[str] = None
    posted_date: Optional[str] = None


@dataclass
class Company:
    name: str
    funding_amount: Optional[str] = None
    funding_round: Optional[str] = None
    sector: Optional[str] = None
    hq: Optional[str] = None
    founders: Optional[str] = None
    source: str = "startup_sheet"
