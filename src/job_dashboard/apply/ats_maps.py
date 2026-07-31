import json
from pathlib import Path

_DIR = Path(__file__).parent / "ats_maps"
KNOWN_ATS = ("greenhouse", "lever", "ashby", "workday")
# Match on distinctive HOST fragments only. A bare "workday" substring would
# false-positive on any URL that merely contains that word (e.g. a careers page
# about a "workday-migration"), tagging it with the wrong field-map.
_DETECT = {"greenhouse.io": "greenhouse", "lever.co": "lever",
           "ashbyhq.com": "ashby", "myworkdayjobs.com": "workday"}


def load_ats_map(name):
    path = _DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(name)
    return json.loads(path.read_text())


def detect_ats(url):
    u = (url or "").lower()
    for needle, name in _DETECT.items():
        if needle in u:
            return name
    return "generic"
