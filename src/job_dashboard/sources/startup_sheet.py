import csv
import io

import requests

from job_dashboard.models import Company

SHEET_CSV_URL_TEMPLATE = "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"


def fetch_funded_startups(sheet_id="19zHtZ1F8-PD8THr8AJ7iN-cyES-5UHWGua_oPERnDvQ"):
    url = SHEET_CSV_URL_TEMPLATE.format(sheet_id=sheet_id)
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.text))
    companies = []
    for row in reader:
        name = (row.get("Company") or "").strip()
        if not name:
            continue
        companies.append(
            Company(
                name=name,
                funding_amount=row.get("Money Raised"),
                funding_round=row.get("Round"),
                sector=row.get("Sector"),
                hq=row.get("HQ"),
                founders=row.get("Founders"),
                source="startup_sheet",
            )
        )
    return companies
