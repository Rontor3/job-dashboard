import json
from pathlib import Path

_DIR = Path(__file__).parent / "ats_maps"
KNOWN_ATS = ("greenhouse", "lever", "ashby", "workday")
_DETECT = {"greenhouse.io": "greenhouse", "lever.co": "lever",
           "ashbyhq.com": "ashby", "myworkdayjobs.com": "workday", "workday": "workday"}


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
