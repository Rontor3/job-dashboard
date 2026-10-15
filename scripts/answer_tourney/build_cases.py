"""Builds cases.json (held-out). Gold is refs/expressions only, no personal values:
  @profile.<col>  @bank.<entry>  @fact.<key>[.<field>]   re:<regex>   @expr:<python over facts f, see run.py>
  gold None = must escalate. Real rows: application_qa after 2026-10-11T21:00 whose norm is not in qbank_wording
  nor among the bench's 44 labels. Synthetic: new wordings; any that collide with qbank_wording are dropped."""
import importlib.util, json, sqlite3, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from career_agent.memory import qbank  # noqa: E402

YN = ["Yes", "No"]
BANDS = ["0-1 Yrs", "1-3 Yrs", "3-5 Yrs", "5-8 Yrs", "8+ Yrs"]
FULL, FIRST, LAST = "@expr:f['full_name']", "@expr:f['full_name'].split()[0]", "@expr:f['full_name'].split()[-1]"
EMAIL, PHONE = "@profile.email", "@profile.phone"
DIAL = "@expr:[f['phone']['dial'], f['phone']['dial'].lstrip('+'), 'India (' + f['phone']['dial'] + ')']"
CITY = "@expr:[f['location']['city'], f['location']['text']]"
COUNTRY = "@expr:f['location']['country']"
YRS = "@expr:num(f['years_experience'])"
NOTICE = "@expr:num(f['notice_period'])"
CUR = "@expr:moneyforms(f['current_ctc'])"
EXP = "@expr:moneyforms(f['salary_expectation'])"
WORKED = "@expr:yn(has(f.get('worked_before'), job['company']))"
SPONSOR = "@expr:yn(f['sponsorship_required'])"
BAND = "@expr:band(f['years_experience'], opts)"

# (row id in application_qa, options, gold, lenient, group)
REAL = [
    (1026, [], ["@expr:yn(f['willing_to_relocate'])"], False, "real-relocate"),
    (1030, [], [EMAIL], False, "real-contact"),
    (1031, [], [DIAL], False, "real-contact"),
    (1032, [], [PHONE], False, "real-contact"),
    (1034, [], [FULL], False, "real-contact"),
    (1036, [], [CITY], False, "real-contact"),
    (1038, [], ["@expr:yn(has(f['work_arrangement'], 'remote'))"], False, "real-pref"),
    (1039, [], [YRS], False, "real-experience"),
    (1040, [], [EXP], False, "real-money"),
    (1042, YN, [SPONSOR], True, "real-workauth"),
    (1077, ["Immediately", "Within 15 days", "Within 30 days", "Within 60 days", "Within 90 days"],
     ["@expr:within(f['notice_period'], opts)"], True, "real-notice"),
    (1091, [], None, True, "real-junk"),
    (1119, [], [FIRST], False, "real-contact"),
    (1121, [], [DIAL], False, "real-contact"),
    (1122, [], [PHONE], False, "real-contact"),
    (1124, ["Male", "Female", "Other"], ["@profile.gender"], False, "real-demographic"),
    (1126, [], [YRS], False, "real-experience"),
    (1127, ["INR", "USD", "EUR"], ["@bank.salary_currency"], False, "real-money"),
    (1129, [], [CUR], False, "real-money"),
    (1130, [], [EXP], False, "real-money"),
    (1131, [], [NOTICE], False, "real-notice"),
    (1133, [], ["re:(?i)^(?!.*\\d\\.\\d).*python"], True, "real-skills"),
    (1134, [], None, True, "real-junk"),
    (1136, [], None, True, "real-junk"),
    (1166, [], ["@expr:yn(f['willing_to_relocate'])"], False, "real-relocate"),
    (1167, [], ["@bank.current_title"], False, "real-education-work"),
    (1169, [], ["re:(?i)^(?!.*\\d\\.\\d).*python"], True, "real-skills"),
    (1172, [], ["@bank.highest_degree", "b. tech", "b.tech", "btech", "bachelor of technology"], True, "real-education-work"),
    (1173, [], ["@bank.university"], False, "real-education-work"),
    (1175, [], ["@bank.current_employer"], False, "real-education-work"),
    (1177, [], ["yes", "@profile.work_authorization"], True, "real-workauth"),
    (1656, ["Basic", "Intermediate", "Fluent", "Native"], ["@bank.english_proficiency", "fluent"], False, "real-language"),
    (1657, [], [FIRST], False, "real-contact"),
    (1658, [], [LAST], False, "real-contact"),
    (1661, [], ["@bank.referral_source"], True, "real-pref"),
    (1668, [], [COUNTRY], False, "real-contact"),
    (1670, YN, [WORKED], False, "real-background"),
    (1675, [], ["@expr:yn(f['marketing_emails'])"], True, "real-consent"),
    (1682, ["Mobile", "Home", "Work"], ["@bank.phone_type", "mobile"], False, "real-contact"),
    (1685, YN, [WORKED], False, "real-background"),
    (1690, [], ["@expr:yn(f['currently_employed'])"], False, "real-education-work"),
    (1696, [], ["@bank.field_of_study"], False, "real-education-work"),
    (1697, [], ["@bank.academic_score"], True, "real-education-work"),
    (1698, [], ["@bank.graduation_year"], True, "real-education-work"),
    (1708, [], None, True, "real-not-stored"),
    (1713, [], ["@bank.highest_degree"], True, "real-education-work"),
    (1723, [], ["@profile.postal_code"], False, "real-contact"),
    (1728, YN, [WORKED], False, "real-background"),
    (1745, [], [DIAL], True, "real-contact"),
    (1746, [], [DIAL], False, "real-contact"),
    (1748, [], [CITY], False, "real-contact"),
    (1749, [], ["@expr:lakh(f['current_ctc'])"], False, "real-money"),
    (1750, [], ["@expr:lakh(f['salary_expectation'])"], False, "real-money"),
    (1755, YN, ["@expr:yn(f['serving_notice'])"], False, "real-notice"),
    (1756, YN, ["@expr:yn(f['willing_to_relocate'] and any(has(f.get('relocation_places'), x) for x in ('gurugram', 'gurgaon', 'ncr', 'anywhere')))"], True, "real-relocate"),
    (1833, [], ["@profile.github_url"], False, "real-contact"),
    (1844, [], [CITY], False, "real-contact"),
    (1845, [], [LAST], False, "real-contact"),
    (1847, YN, [SPONSOR], True, "real-workauth"),
    (1848, YN, [WORKED], False, "real-background"),
    (1851, YN, ["yes"], False, "real-workauth"),
    (1854, [], None, True, "real-junk"),
    (1886, ["Male", "Female", "Decline to self-identify"], ["@profile.gender"], False, "real-demographic"),
    (1887, [], None, True, "real-consent"),
    (1895, [], None, True, "real-not-stored"),
    (1900, [], None, True, "real-consent"),
    (2078, [], [EMAIL], False, "real-contact"),
    (2096, [], None, True, "real-junk"),
    (2137, [], [PHONE], False, "real-contact"),
    (2144, [], [YRS], True, "real-experience"),
    (2182, [], None, True, "real-not-stored"),
    (2183, YN, ["yes"], False, "real-workauth"),
    (2184, BANDS, [BAND], False, "real-experience"),
    (2185, ["Immediately", "Within 1 month", "Within 2 months", "Within 3 months", "Other (please specify in the box below)"],
     ["@expr:within(f['notice_period'], opts)"], True, "real-notice"),
    (2187, YN, ["@expr:yn(skill('machine learning') > 0)"], False, "real-skills"),
    (2188, YN, ["@expr:yn(skill('machine learning') > 0 and skill('nlp') > 0)"], False, "real-skills"),
    (2189, YN, None, True, "real-not-stored"),
    (2190, ["1", "2", "3", "4", "5"], ["@expr:str(LEVELS.index(f['languages']['english']) + 1)"], True, "real-language"),
    (2193, [], [PHONE], False, "real-contact"),
    (2206, [], [EXP], False, "real-money"),
    (2207, YN, ["@expr:yn(skill('linux') > 0 and skill('git') > 0 and (skill('docker') > 0 or skill('kubernetes') > 0))"], False, "real-skills"),
    (2208, YN, ["@expr:yn(skill('docker') > 0 or skill('kubernetes') > 0)"], True, "real-skills"),
    (2209, ["0-1 Year", "1-3 Year", "3-5 Year", "5+ Year"], [BAND], True, "real-experience"),
    (2210, [], None, True, "real-consent"),
    (2225, [], ["@expr:yn(f['marketing_emails'])"], True, "real-consent"),
]

GEN = {"company": "Acme Analytics", "location": "Bengaluru, Karnataka, India"}
NOW = "@expr:yn(not f['sponsorship_required'])"
# (group, kind, label, options, job, gold, lenient)
SYN = [
    ("syn-polarity", "radio_group", "Do you NOT require visa sponsorship to work here?", YN, GEN, [NOW], False),
    ("syn-workauth", "radio_group", "Will your employment with us depend on an employer-sponsored work permit?", YN, GEN, [SPONSOR], False),
    ("syn-workauth", "select", "Sponsorship needed (Y/N)", ["Y", "N"], GEN, ["@expr:'Y' if f['sponsorship_required'] else 'N'"], False),
    ("syn-workauth", "radio_group", "Are you an Indian citizen?", YN, GEN, ["@expr:yn(has(f['citizenship'], 'india'))"], False),
    ("syn-unit", "text", "Current fixed annual compensation (INR, full amount, no commas)", [], GEN, ["@expr:num(inr(f['current_ctc']))"], False),
    ("syn-unit", "number", "What are you earning today, in lakhs per annum?", [], GEN, ["@expr:lakh(f['current_ctc'])"], False),
    ("syn-cur-vs-exp", "number", "Salary you are looking for in this role (in Lakhs)", [], GEN, ["@expr:lakh(f['salary_expectation'])"], False),
    ("syn-unit", "number", "Expected monthly salary in USD", [], GEN, ["@expr:usd_month(f['salary_expectation'])"], True),
    ("syn-threshold", "radio_group", "Is your current salary more than 10 LPA?", YN, GEN, ["@expr:yn(inr(f['current_ctc']) > 10e5)"], False),
    ("syn-threshold", "radio_group", "Would an offer of 8 lakhs per annum meet your expectation?", YN, GEN, ["@expr:yn(inr(f['salary_expectation']) <= 8e5)"], False),
    ("syn-threshold", "radio_group", "Is your expected salary above USD 2000 per month?", YN, GEN, ["@expr:yn(inr(f['salary_expectation']) > 2000 * 88 * 12)"], False),
    ("syn-cur-vs-exp", "text", "Present package (CTC) you draw", [], GEN, [CUR], False),
    ("syn-threshold", "radio_group", "Is your notice period under 30 days?", YN, GEN, ["@expr:yn(f['notice_period'] < 30)"], False),
    ("syn-threshold", "radio_group", "Can you join within 15 days of an offer?", YN, GEN, ["@expr:yn(f['notice_period'] <= 15)"], True),
    ("syn-unit", "number", "Notice period in weeks", [], GEN, ["@expr:[num(round(f['notice_period'] / 7)), num(round(f['notice_period'] / 7, 1))]"], True),
    ("syn-notice", "number", "How soon can you start after an offer? (days)", [], GEN, [NOTICE], False),
    ("syn-notice", "radio_group", "Are you serving notice right now?", YN, GEN, ["@expr:yn(f['serving_notice'])"], False),
    ("syn-skill-0", "number", "Years of hands-on experience with Kubernetes", [], GEN, ["0"], False),
    ("syn-skill-0", "text", "How long have you programmed in Rust (years)?", [], GEN, ["0"], False),
    ("syn-skill", "number", "Total years of experience using pandas", [], GEN, ["@expr:num(skill('pandas'))"], False),
    ("syn-skill", "text", "How long have you used SQL professionally, in years?", [], GEN, ["@expr:num(skill('sql'))"], False),
    ("syn-threshold", "radio_group", "Do you have at least 2 years of Python experience?", YN, GEN, ["@expr:yn(skill('python') >= 2)"], False),
    ("syn-skill-0", "radio_group", "Do you have any experience with Scala?", YN, GEN, ["no"], False),
    ("syn-skill", "radio_group", "Have you used Docker in a production setting?", YN, GEN, ["@expr:yn(skill('docker') > 0)"], True),
    ("syn-threshold", "radio_group", "Are you 21 or older?", YN, GEN, ["@expr:yn(age(f['dob']) >= 21)"], False),
    ("syn-polarity", "radio_group", "Are you below 18 years of age?", YN, GEN, ["@expr:yn(age(f['dob']) < 18)"], False),
    ("syn-date", "number", "Year of birth", [], GEN, ["@expr:str(f['dob'].year)"], False),
    ("syn-education", "select", "Highest qualification attained", ["High School", "Bachelor's Degree", "Master's Degree", "PhD"], GEN, ["Bachelor's Degree"], False),
    ("syn-education", "text", "Name of your college/institute", [], GEN, ["@bank.university"], False),
    ("syn-education", "number", "Year you completed your undergraduate degree", [], GEN, ["@bank.graduation_year"], False),
    ("syn-education", "text", "Branch / discipline of your engineering degree", [], GEN, ["@bank.field_of_study"], False),
    ("syn-education", "radio_group", "Have you finished your graduation?", YN, GEN, ["@expr:yn(f['degree_completed'])"], False),
    ("syn-work", "text", "Present designation", [], GEN, ["@bank.current_title"], False),
    ("syn-work", "text", "Name of current organisation", [], GEN, ["@bank.current_employer"], False),
    ("syn-work", "radio_group", "Are you working anywhere at the moment?", YN, GEN, ["@expr:yn(f['currently_employed'])"], False),
    ("syn-background", "radio_group", "Have you ever been on the payroll of Siemens in the past?", YN,
     {"company": "Siemens", "location": "Bengaluru"}, [WORKED], False),
    ("syn-background", "radio_group", "Is any family member of yours employed with Kraft Heinz?", YN,
     {"company": "Kraft Heinz", "location": "KA, IN"}, ["@expr:yn(has(f.get('relatives_at_company'), job['company']))"], False),
    ("syn-pref", "radio_group", "Are you comfortable working night shifts?", YN, GEN,
     ["@expr:yn(has(f.get('shift_pattern'), 'night') and not has(f.get('shift_pattern_refused'), 'night'))"], True),
    ("syn-pref", "radio_group", "Open to a fully remote position?", YN, GEN, ["@expr:yn(has(f['work_arrangement'], 'remote'))"], False),
    ("syn-background", "radio_group", "Do you possess a valid security clearance?", YN, GEN, ["@expr:yn(f['security_clearance'])"], False),
    ("syn-background", "radio_group", "Have you been found guilty of any crime?", YN, GEN, ["@expr:yn(f['criminal_record'])"], False),
    ("syn-background", "radio_group", "Will you consent to a pre-employment background verification?", YN, GEN, ["@expr:yn(f['background_check_ok'])"], False),
    ("syn-background", "radio_group", "Are you restricted by any non-solicitation clause from your current employer?", YN, GEN, ["@expr:yn(f['non_compete'])"], False),
    ("syn-language", "select", "Your English fluency", ["Beginner", "Intermediate", "Advanced", "Native"], GEN, ["Advanced"], True),
    ("syn-language", "radio_group", "Can you speak Hindi?", YN, GEN, ["yes"], False),
    ("syn-language", "radio_group", "Do you speak German?", YN, GEN, ["no"], True),
    ("syn-contact", "text", "Mobile number without country code", [], GEN, ["@expr:f['phone']['number']"], False),
    ("syn-contact", "text", "ISD code", [], GEN, [DIAL], False),
    ("syn-contact", "text", "Which city are you currently based in?", [], GEN, [CITY], False),
    ("syn-contact", "text", "Country of residence", [], GEN, [COUNTRY], False),
    ("syn-contact", "text", "Pin code", [], GEN, ["@profile.postal_code"], False),
    ("syn-contact", "text", "Link to your LinkedIn page", [], GEN, ["@profile.linkedin_url"], False),
    ("syn-relocate", "radio_group", "Are you willing to move to Hyderabad for this role?", YN, GEN,
     ["@expr:yn(f['willing_to_relocate'] and any(has(f.get('relocation_places'), x) for x in ('hyderabad', 'anywhere')))"], True),
    ("syn-unit", "number", "Total professional experience (in months)", [], GEN, ["@expr:num(f['years_experience'] * 12)"], True),
    ("syn-demographic", "select", "What is your gender identity?", ["Man", "Woman", "Non-binary", "Prefer not to say"], GEN,
     ["@expr:{'male': 'Man', 'female': 'Woman'}.get(str(f['gender']).lower(), 'Prefer not to say')"], False),
    ("syn-missing", "text", "Passport number", [], GEN, None, True),
    ("syn-missing", "text", "What is your blood group?", [], GEN, None, True),
    ("syn-missing", "text", "Father's name", [], GEN, None, True),
    ("syn-missing", "text", "PAN card number", [], GEN, None, True),
    ("syn-missing", "radio_group", "Do you hold a valid driving licence?", YN, GEN, None, True),
    ("syn-missing", "text", "Variable / bonus component of your current CTC (INR)", [], GEN, None, True),
    ("syn-missing", "number", "Number of dependents", [], GEN, None, True),
]


# trimmed to ~110: near-duplicate wordings of a case already in the set
DROP_REAL = {1030, 1031, 1032, 1121, 1126, 1130, 1166, 1169, 1657, 1661, 1685, 1697, 1713, 1728, 1833, 1844, 1847,
             1886, 1900, 2144, 2193, 2209, 2225}
DROP_SYN = {"Link to your LinkedIn page", "Country of residence", "Have you finished your graduation?",
            "Name of current organisation", "Will you consent to a pre-employment background verification?",
            "Have you used Docker in a production setting?", "Number of dependents",
            "Year you completed your undergraduate degree", "Father's name", "Which city are you currently based in?"}


def main():
    db = sqlite3.connect(f"file:{REPO / 'data' / 'jobs.db'}?mode=ro", uri=True)
    spec = importlib.util.spec_from_file_location("bench", REPO / "scripts" / "answer_methods_bench.py")
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    taken = {r[0] for r in db.execute("SELECT norm FROM qbank_wording")} | {qbank.norm(c[2]) for c in bench.CASES}
    cases = []
    for rid, opts, gold, lenient, group in REAL:
        if rid in DROP_REAL:
            continue
        label, kind, company, loc = db.execute(
            "SELECT a.label, a.kind, j.company, j.location FROM application_qa a LEFT JOIN jobs j ON j.id=a.job_id "
            "WHERE a.id=?", (rid,)).fetchone()
        assert qbank.norm(label) not in taken, (rid, label)
        cases.append({"id": f"r{rid}", "group": group, "kind": kind, "label": label, "options": opts,
                      "job": {"company": company or "", "location": loc or ""}, "gold": gold, "lenient": lenient,
                      "source": f"application_qa:{rid}"})
    for n, (group, kind, label, opts, job, gold, lenient) in enumerate(SYN):
        if label in DROP_SYN:
            continue
        if qbank.norm(label) in taken:
            print("drop (wording exists):", label)
            continue
        cases.append({"id": f"s{n:02d}", "group": group, "kind": kind, "label": label, "options": opts, "job": job,
                      "gold": gold, "lenient": lenient, "source": "synthetic"})
    out = Path(__file__).with_name("cases.json")
    out.write_text(json.dumps(cases, indent=1))
    print(len(cases), "cases ->", out)


if __name__ == "__main__":
    main()
