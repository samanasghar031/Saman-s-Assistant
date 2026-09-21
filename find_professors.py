import csv
import io
import json
import re
import shutil
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


BASE_FOLDER = Path(__file__).resolve().parent

EVIDENCE_FILE = BASE_FOLDER / "student_research_evidence.json"
CONFIRMED_FILE = BASE_FOLDER / "professor_candidates.csv"
LEADS_FILE = BASE_FOLDER / "recruitment_leads.csv"
REPORT_FILE = BASE_FOLDER / "recruitment_search_report.txt"
ARCHIVE_FOLDER = BASE_FOLDER / "search_archive"

TARGET_YEAR = "2027"
WEB_TIMEOUT = 30
MAX_DOCUMENT_CHARACTERS = 200000

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/124.0 "
    "AcademicResearchAssistant/4.0"
)

BLOCKED_HOSTS = (
    "academia.edu",
    "facebook.com",
    "google.com",
    "instagram.com",
    "linkedin.com",
    "openalex.org",
    "researchgate.net",
    "scholar.google",
    "semanticscholar.org",
    "wikipedia.org",
    "x.com",
)

ACADEMIC_SUFFIXES = (
    ".ac.jp",
    ".ac.nz",
    ".ac.uk",
    ".edu",
    ".edu.au",
    ".edu.cn",
    ".edu.hk",
    ".edu.pk",
    ".edu.sg",
    ".edu.tw",
    ".go.jp",
)

# Public suffixes that contain more than one label.  Keeping these here lets
# the validator recognize two official subdomains of the same institution
# (for example, ims.utoronto.ca and dfcm.utoronto.ca) without treating every
# site under a country-code domain as related.
MULTI_LABEL_PUBLIC_SUFFIXES = (
    "ac.jp",
    "ac.nz",
    "ac.uk",
    "co.jp",
    "co.nz",
    "co.uk",
    "com.au",
    "edu.au",
    "edu.cn",
    "edu.hk",
    "edu.pk",
    "edu.sg",
    "edu.tw",
    "go.jp",
    "gov.au",
    "gov.uk",
    "org.au",
    "org.nz",
    "org.uk",
)

ACADEMIC_MARKERS = (
    "college",
    "department",
    "faculty",
    "graduate",
    "institute",
    "laboratory",
    "programme",
    "program",
    "research centre",
    "research center",
    "school of",
    "university",
)

CURRENT_POSITION_TERMS = (
    "assistant professor",
    "associate professor",
    "full professor",
    "group leader",
    "investigator",
    "lecturer",
    "principal investigator",
    "professor",
    "research officer",
    "researcher",
)

FORMER_POSITION_TERMS = (
    "deceased",
    "emerita",
    "emeritus",
    "former professor",
    "in memoriam",
    "retired",
)

TOPIC_GROUPS = {
    "addiction/substance use": (
        "addiction",
        "addictive",
        "alcohol use",
        "drug dependence",
        "opioid",
        "substance abuse",
        "substance use",
    ),
    "genetics/genomics": (
        "dna",
        "gene",
        "genes",
        "genetic",
        "genetics",
        "genomic",
        "genomics",
        "sequencing",
        "variant",
        "variants",
    ),
    "molecular biology": (
        "biochemical",
        "cellular",
        "gene expression",
        "molecular",
        "molecular biology",
    ),
    "neuroscience/neurogenetics": (
        "brain",
        "neural",
        "neuron",
        "neuronal",
        "neurogenetic",
        "neurogenetics",
        "neurological",
        "neuroscience",
        "neuropsychiatric",
        "nervous system",
    ),
    "bioinformatics/computational genomics": (
        "bioinformatic",
        "bioinformatics",
        "computational genomics",
        "genomic data",
        "sequence analysis",
        "statistical genetics",
    ),
    "drug discovery": (
        "drug discovery",
        "drug repurposing",
        "molecular docking",
        "pharmacology",
        "therapeutic development",
    ),
    "neurodegeneration": (
        "alzheimer",
        "dementia",
        "neurodegeneration",
        "neurodegenerative",
        "parkinson",
    ),
    "forensic genetics": (
        "dna profiling",
        "forensic dna",
        "forensic genetic",
        "forensic genetics",
        "forensic genomics",
    ),
}

FIELDS = [
    "candidate_id",
    "name",
    "institution",
    "country",
    "research_topic",
    "research_area",
    "official_profile_url",
    "recruitment_url",
    "recruitment_quote",
    "opportunity_url",
    "opportunity_quote",
    "target_start",
    "recruitment_status",
    "profile_verified",
    "quote_verified",
    "checked_date",
    "research_overlap",
    "verification_notes",
    "recent_paper",
    "year",
    "citations",
    "doi",
    "openalex_author_url",
    "verified_email",
    "status",
]


def norm(value):
    value = unicodedata.normalize(
        "NFKC",
        value or "",
    )

    value = (
        value.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip().lower()


def clean(value):
    return re.sub(
        r"\s+",
        " ",
        value or "",
    ).strip()


def valid_url(url):
    try:
        parsed = urlparse(url)

        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.netloc)
        )

    except ValueError:
        return False


def host_of(url):
    return (
        urlparse(url)
        .netloc.lower()
        .split(":")[0]
        .removeprefix("www.")
    )


def blocked_url(url):
    host = host_of(url)

    return any(
        host == blocked
        or host.endswith("." + blocked)
        for blocked in BLOCKED_HOSTS
    )


def related_hosts(first_url, second_url):
    first = host_of(first_url)
    second = host_of(second_url)

    if not first or not second:
        return False

    if (
        first == second
        or first.endswith("." + second)
        or second.endswith("." + first)
    ):
        return True

    def institutional_domain(host):
        labels = [
            label
            for label in host.split(".")
            if label
        ]

        if len(labels) < 2:
            return host

        last_two = ".".join(labels[-2:])

        if (
            last_two
            in MULTI_LABEL_PUBLIC_SUFFIXES
            and len(labels) >= 3
        ):
            return ".".join(labels[-3:])

        return ".".join(labels[-2:])

    return (
        institutional_domain(first)
        == institutional_domain(second)
    )


def read_student_evidence():
    if not EVIDENCE_FILE.exists():
        raise FileNotFoundError(
            "student_research_evidence.json was not found. "
            "Import and approve the student's research documents first."
        )

    try:
        data = json.loads(
            EVIDENCE_FILE.read_text(
                encoding="utf-8",
            )
        )

    except json.JSONDecodeError as error:
        raise ValueError(
            "student_research_evidence.json is not valid JSON."
        ) from error

    if data.get("approved_by_user") is not True:
        raise ValueError(
            "The student research evidence is not approved."
        )

    if not clean(
        data.get(
            "approved_search_evidence",
            "",
        )
    ):
        raise ValueError(
            "The approved student research evidence is empty."
        )

    return data


def fetch_document(url):
    if not valid_url(url) or blocked_url(url):
        raise ValueError(
            "An allowed official http or https URL is required."
        )

    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
        },
        timeout=WEB_TIMEOUT,
        allow_redirects=True,
    )

    response.raise_for_status()

    final_url = response.url

    content_type = response.headers.get(
        "Content-Type",
        "",
    ).lower()

    looks_like_pdf = (
        "pdf" in content_type
        or final_url.lower()
        .split("?", 1)[0]
        .endswith(".pdf")
    )

    if looks_like_pdf:
        try:
            from pypdf import PdfReader

        except ImportError as error:
            raise RuntimeError(
                "PDF evidence needs pypdf. Run: "
                "python -m pip install pypdf"
            ) from error

        reader = PdfReader(
            io.BytesIO(response.content)
        )

        pages = []

        for page in reader.pages:
            pages.append(
                page.extract_text() or ""
            )

        text = clean(
            "\n".join(pages)
        )

        title = (
            Path(
                urlparse(final_url).path
            ).name
            or "Official PDF"
        )

        document_type = "PDF"

    else:
        if (
            "html" not in content_type
            and "text" not in content_type
        ):
            raise ValueError(
                "The URL did not return a readable "
                "HTML or PDF document."
            )

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        title = (
            clean(
                soup.title.get_text(
                    " ",
                    strip=True,
                )
            )
            if soup.title
            else ""
        )

        for tag in soup(
            [
                "script",
                "style",
                "svg",
                "noscript",
            ]
        ):
            tag.decompose()

        text = clean(
            soup.get_text(
                " ",
                strip=True,
            )
        )

        document_type = "HTML"

    if len(text) < 150:
        raise ValueError(
            "The official document contains "
            "too little readable text."
        )

    return {
        "url": final_url,
        "title": title,
        "text": text[:MAX_DOCUMENT_CHARACTERS],
        "type": document_type,
    }


def likely_official_document(document):
    url = document["url"]
    text = document["text"]
    host = host_of(url)

    if not host or blocked_url(url):
        return False

    academic_host = any(
        host.endswith(suffix)
        for suffix in ACADEMIC_SUFFIXES
    )

    academic_text = any(
        marker in norm(text)
        for marker in ACADEMIC_MARKERS
    )

    if academic_host:
        return academic_text

    if host.endswith(".ca"):
        return academic_text

    return False


def contains_phd(text):
    return bool(
        re.search(
            r"\b(?:ph\.?d|doctoral|doctorate)\b",
            norm(text),
        )
    )


def has_2027_intake_evidence(text):
    lowered = norm(text)

    if (
        TARGET_YEAR not in lowered
        or not contains_phd(lowered)
    ):
        return False

    intake_terms = (
        "admission",
        "admissions",
        "application",
        "applications",
        "apply",
        "commence",
        "enrolment",
        "enrollment",
        "intake",
        "recruitment",
        "scholarship",
        "start",
    )

    for match in re.finditer(
        TARGET_YEAR,
        lowered,
    ):
        start = max(
            0,
            match.start() - 450,
        )

        end = min(
            len(lowered),
            match.end() + 650,
        )

        window = lowered[start:end]

        if any(
            term in window
            for term in intake_terms
        ):
            return True

    return False


def has_professor_opportunity_evidence(text):
    lowered = norm(text)

    patterns = (
        (
            r"(?:accepting|recruiting|seeking|looking for)"
            r"\b.{0,220}\b"
            r"(?:ph\.?d|doctoral|student|candidate)"
        ),
        (
            r"\b(?:ph\.?d|doctoral)\b"
            r".{0,220}\b"
            r"(?:accepting|recruiting|seeking|looking for|"
            r"suitable|apply|contact)"
        ),
        (
            r"\bsuitable for\b"
            r".{0,120}\b"
            r"(?:ph\.?d|doctoral)\b"
        ),
        (
            r"\b(?:ph\.?d|doctoral)\b"
            r".{0,160}\b"
            r"(?:project|position|studentship)\b"
        ),
        r"\bcontact (?:the )?supervisors?\b",
    )

    return (
        contains_phd(lowered)
        and any(
            re.search(
                pattern,
                lowered,
            )
            for pattern in patterns
        )
    )


def evidence_fragments(
    text,
    required_year=None,
    professor_name=None,
):
    normalized = clean(text)
    lowered = norm(normalized)
    anchors = []

    if required_year:
        anchors.extend(
            match.start()
            for match in re.finditer(
                required_year,
                lowered,
            )
        )

    if professor_name:
        family_name = name_parts(
            professor_name
        )[-1]

        anchors.extend(
            match.start()
            for match in re.finditer(
                re.escape(family_name),
                lowered,
            )
        )

    fragments = []
    seen = set()

    for anchor in anchors:
        start = max(
            0,
            anchor - 420,
        )

        end = min(
            len(normalized),
            anchor + 760,
        )

        fragment = normalized[
            start:end
        ].strip(" |:-")

        if (
            required_year
            and required_year
            not in norm(fragment)
        ):
            continue

        if (
            professor_name
            and not name_in_text(
                professor_name,
                fragment,
            )
        ):
            continue

        key = norm(fragment)

        if key not in seen:
            seen.add(key)
            fragments.append(fragment)

    return fragments[:5]


def choose_fragment(
    fragments,
    label,
):
    if not fragments:
        raise ValueError(
            f"No exact {label} passage "
            "could be isolated."
        )

    print()
    print(
        f"Exact {label} passages found:"
    )
    print()

    for number, fragment in enumerate(
        fragments,
        start=1,
    ):
        print(
            f"{number}. {fragment}"
        )
        print()

    if len(fragments) == 1:
        print(
            "The only available passage was "
            "selected automatically."
        )
        return fragments[0]

    while True:
        selection = input(
            f"{label} passage number "
            f"(1-{len(fragments)}): "
        ).strip()

        if selection.isdigit():
            index = int(selection) - 1

            if 0 <= index < len(fragments):
                return fragments[index]

        print(
            "Please enter a number from 1 to "
            f"{len(fragments)}."
        )


def name_parts(name):
    parts = re.findall(
        r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+",
        norm(name),
    )

    if len(parts) < 2:
        raise ValueError(
            "Enter the professor's full name."
        )

    return parts


def name_in_text(name, text):
    parts = name_parts(name)
    lowered = norm(text)

    return (
        parts[-1] in lowered
        and parts[0] in lowered
    )


def person_contexts(
    name,
    text,
    radius=1200,
):
    lowered = norm(text)
    parts = name_parts(name)
    full_name = " ".join(parts)

    matches = list(
        re.finditer(
            re.escape(full_name),
            lowered,
        )
    )

    # Some official profiles insert credentials or initials into the displayed
    # name.  In that case, fall back to every occurrence of the family name.
    if not matches:
        matches = list(
            re.finditer(
                re.escape(parts[-1]),
                lowered,
            )
        )

    contexts = []

    for match in matches:
        start = max(
            0,
            match.start() - radius,
        )

        end = min(
            len(lowered),
            match.end() + radius,
        )

        context = lowered[start:end]

        if context not in contexts:
            contexts.append(context)

    return contexts


def person_context(
    name,
    text,
    radius=1200,
):
    return " ".join(
        person_contexts(
            name,
            text,
            radius,
        )
    )


def current_position_ok(
    name,
    profile_text,
):
    contexts = person_contexts(
        name,
        profile_text,
    )

    if not contexts:
        return False

    for context in contexts:
        if any(
            term in context
            for term in FORMER_POSITION_TERMS
        ):
            continue

        if any(
            term in context
            for term in CURRENT_POSITION_TERMS
        ):
            return True

    return False


def institution_matches(
    institution,
    profile_text,
):
    words = [
        word
        for word in re.findall(
            r"[a-z][a-z0-9-]+",
            norm(institution),
        )
        if (
            len(word) >= 4
            and word
            not in {
                "college",
                "institute",
                "university",
            }
        )
    ]

    lowered = norm(profile_text)

    return bool(
        words
        and any(
            word in lowered
            for word in words
        )
    )


def active_topic_groups(topic):
    lowered = norm(topic)
    active = []

    for group, aliases in TOPIC_GROUPS.items():
        if any(
            alias in lowered
            for alias in aliases
        ):
            active.append(group)

    return active


def topic_group_matches(
    topic,
    evidence_text,
):
    lowered = norm(evidence_text)
    active = active_topic_groups(topic)
    matched = []
    missing = []

    for group in active:
        aliases = TOPIC_GROUPS[group]

        if any(
            alias in lowered
            for alias in aliases
        ):
            matched.append(group)

        else:
            missing.append(group)

    return active, matched, missing


MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def detected_deadlines(text):
    lowered = norm(
        clean(text)
    )

    results = []

    month_names = "|".join(
        MONTHS
    )

    date_patterns = (
        (
            r"(?<!\d)(?P<day>\d{1,2})"
            r"\s*(?:st|nd|rd|th)?\s+"
            rf"(?P<month>{month_names})\b"
            r"\s*,?\s*(?P<year>20\d{2})(?!\d)"
        ),
        (
            rf"\b(?P<month>{month_names})\b\s+"
            r"(?P<day>\d{1,2})"
            r"\s*(?:st|nd|rd|th)?\s*,?\s*"
            r"(?P<year>20\d{2})(?!\d)"
        ),
        (
            r"(?<!\d)(?P<year>20\d{2})-"
            r"(?P<month_num>\d{2})-"
            r"(?P<day>\d{2})(?!\d)"
        ),
    )

    deadline_terms = (
        "application deadline",
        "application deadlines",
        "applications close",
        "closing date",
        "deadline",
        "due date",
        "final date",
        "submit by",
    )

    opening_patterns = (
        (
            r"\bapplications?\b.{0,30}"
            r"\b(?:will\s+)?open(?:s)?\b"
            r"(?:\s+(?:on|from))?\s*[:\-–—]?\s*$"
        ),
        (
            r"\b(?:open|opening) date\b"
            r"\s*(?:is|:)?\s*$"
        ),
        r"\bavailable from\b\s*[:\-–—]?\s*$",
        r"\bwill\s+open\b\s*[:\-–—]?\s*$",
        r"\bopens?\s+(?:on|from)\b\s*$",
    )

    for pattern in date_patterns:
        for match in re.finditer(
            pattern,
            lowered,
        ):
            context = lowered[
                max(
                    0,
                    match.start() - 500,
                ):
                match.end() + 120
            ]

            if not any(
                term in context
                for term in deadline_terms
            ):
                continue

            nearby_before = lowered[
                max(
                    0,
                    match.start() - 70,
                ):
                match.start()
            ]

            has_opening_language = any(
                re.search(
                    pattern,
                    nearby_before,
                )
                for pattern in opening_patterns
            )

            if has_opening_language:
                continue

            year = int(
                match.group("year")
            )

            day = int(
                match.group("day")
            )

            if match.groupdict().get(
                "month_num"
            ):
                month = int(
                    match.group("month_num")
                )

            else:
                month = MONTHS[
                    match.group("month")
                ]

            try:
                value = date(
                    year,
                    month,
                    day,
                )

            except ValueError:
                continue

            if value not in results:
                results.append(value)

    return sorted(results)


def ensure_deadline_open(documents):
    deadlines = []

    for document in documents:
        deadlines.extend(
            detected_deadlines(
                document["text"]
            )
        )

    deadlines = sorted(
        set(deadlines)
    )

    if (
        deadlines
        and max(deadlines)
        < datetime.now(
            timezone.utc
        ).date()
    ):
        formatted = ", ".join(
            value.isoformat()
            for value in deadlines
        )

        raise ValueError(
            "The official evidence contains "
            "only expired application deadlines: "
            f"{formatted}. This opportunity "
            "cannot be saved."
        )

    return deadlines


def ask_basic_details():
    print()
    print(
        "Search and verify one research "
        "direction at a time."
    )

    print(
        "Example: addiction genetics "
        "and molecular neurogenetics"
    )

    topic = input(
        "\nSpecific research topic: "
    ).strip()

    if len(topic) < 8:
        raise ValueError(
            "Enter one clear research topic."
        )

    active = active_topic_groups(
        topic
    )

    if not active:
        raise ValueError(
            "The topic is too general. Include terms "
            "such as addiction, genetics, neurogenetics, "
            "bioinformatics, drug discovery, "
            "neurodegeneration, or forensic genetics."
        )

    country = input(
        "Country: "
    ).strip()

    if len(country) < 3:
        raise ValueError(
            "Enter the country for this opportunity."
        )

    return topic, country


def collect_and_validate(
    topic,
    country,
):
    print()
    print(
        "This importer requires "
        "three official sources."
    )

    print(
        "The same URL may be used more than once "
        "only if it contains all evidence."
    )

    print()

    name = input(
        "Professor's full name: "
    ).strip()

    name_parts(name)

    institution = input(
        "Institution: "
    ).strip()

    if len(institution) < 4:
        raise ValueError(
            "Enter the full institution name."
        )

    intake_input = input(
        "Official 2027 PhD "
        "intake/scholarship URL: "
    ).strip()

    opportunity_input = input(
        "Official professor-specific PhD "
        "project/recruitment URL: "
    ).strip()

    profile_input = input(
        "Official professor profile URL: "
    ).strip()

    print()
    print(
        "Reading official evidence..."
    )

    intake = fetch_document(
        intake_input
    )

    opportunity = fetch_document(
        opportunity_input
    )

    profile = fetch_document(
        profile_input
    )

    failures = []

    for label, document in (
        ("2027 intake", intake),
        (
            "professor opportunity",
            opportunity,
        ),
        (
            "professor profile",
            profile,
        ),
    ):
        if not likely_official_document(
            document
        ):
            failures.append(
                f"The {label} source is not "
                "recognized as official "
                "academic evidence"
            )

    if not related_hosts(
        intake["url"],
        opportunity["url"],
    ):
        failures.append(
            "The intake and professor-opportunity "
            "pages are on different institutions"
        )

    if not related_hosts(
        opportunity["url"],
        profile["url"],
    ):
        failures.append(
            "The opportunity and professor-profile "
            "pages are on different institutions"
        )

    if not has_2027_intake_evidence(
        intake["text"]
    ):
        failures.append(
            "The intake source lacks exact 2027 "
            "PhD admission or scholarship wording"
        )

    if not name_in_text(
        name,
        opportunity["text"],
    ):
        failures.append(
            "The professor's full name is not "
            "present on the opportunity page"
        )

    if not has_professor_opportunity_evidence(
        opportunity["text"]
    ):
        failures.append(
            "The opportunity page does not "
            "explicitly seek or invite PhD students"
        )

    if not name_in_text(
        name,
        profile["text"],
    ):
        failures.append(
            "The professor's full name is not "
            "present on the profile"
        )

    if not current_position_ok(
        name,
        profile["text"],
    ):
        failures.append(
            "A current academic or research "
            "position was not confirmed near "
            "the professor's name"
        )

    if not institution_matches(
        institution,
        profile["text"],
    ):
        failures.append(
            "The institution name is not "
            "supported by the professor profile"
        )

    (
        active,
        matched,
        missing,
    ) = topic_group_matches(
        topic,
        opportunity["text"]
        + " "
        + profile["text"],
    )

    if missing:
        failures.append(
            "Research fit is incomplete; "
            "missing topic groups: "
            + ", ".join(missing)
        )

    deadlines = []

    try:
        deadlines = ensure_deadline_open(
            (
                intake,
                opportunity,
            )
        )

    except ValueError as error:
        failures.append(
            str(error)
        )

    intake_fragments = evidence_fragments(
        intake["text"],
        required_year=TARGET_YEAR,
    )

    opportunity_fragments = (
        evidence_fragments(
            opportunity["text"],
            professor_name=name,
        )
    )

    intake_fragments = [
        fragment
        for fragment in intake_fragments
        if (
            has_2027_intake_evidence(
                fragment + " PhD"
            )
            or (
                TARGET_YEAR
                in norm(fragment)
                and any(
                    term in norm(fragment)
                    for term in (
                        "admission",
                        "application",
                        "deadline",
                        "scholarship",
                        "commence",
                    )
                )
            )
        )
    ]

    opportunity_fragments = [
        fragment
        for fragment
        in opportunity_fragments
        if has_professor_opportunity_evidence(
            fragment
        )
    ]

    if not intake_fragments:
        failures.append(
            "An exact 2027 intake quotation "
            "could not be isolated"
        )

    if not opportunity_fragments:
        failures.append(
            "A professor-specific PhD opportunity "
            "quotation could not be isolated"
        )

    if failures:
        raise ValueError(
            "; ".join(failures)
        )

    intake_quote = choose_fragment(
        intake_fragments,
        "2027 intake",
    )

    opportunity_quote = choose_fragment(
        opportunity_fragments,
        "professor-specific PhD opportunity",
    )

    print()
    print(
        "EVIDENCE SUMMARY"
    )
    print("-" * 68)
    print(
        f"Professor: {name}"
    )
    print(
        f"Institution: {institution}"
    )
    print(
        f"Country: {country}"
    )
    print(
        "Matched research groups: "
        + ", ".join(matched)
    )
    print(
        f"2027 source: {intake['url']}"
    )
    print(
        "Opportunity source: "
        f"{opportunity['url']}"
    )
    print(
        f"Profile source: {profile['url']}"
    )

    if deadlines:
        print(
            "Detected application deadlines: "
            + ", ".join(
                value.isoformat()
                for value in deadlines
            )
        )

    else:
        print(
            "Detected application deadlines: "
            "none stated"
        )

    print()
    print(
        "The app has not checked publication "
        "authorship or email yet."
    )
    print(
        "Those checks occur in Strict "
        "Professor Verification."
    )

    approval = input(
        "\nType APPROVE only if all displayed "
        "evidence belongs to the same current "
        "opportunity: "
    ).strip().upper()

    if approval != "APPROVE":
        raise ValueError(
            "User did not approve the linked "
            "official evidence"
        )

    checked_date = (
        datetime.now(
            timezone.utc
        ).date().isoformat()
    )

    if deadlines:
        deadline_note = (
            "Detected deadline(s): "
            + ", ".join(
                value.isoformat()
                for value in deadlines
            )
        )

    else:
        deadline_note = (
            "No explicit deadline was detected; "
            "recheck before contact."
        )

    candidate = {
        "candidate_id": "C001",
        "name": name,
        "institution": institution,
        "country": country,
        "research_topic": topic,
        "research_area": topic,
        "official_profile_url": (
            profile["url"]
        ),
        "recruitment_url": (
            intake["url"]
        ),
        "recruitment_quote": (
            intake_quote
        ),
        "opportunity_url": (
            opportunity["url"]
        ),
        "opportunity_quote": (
            opportunity_quote
        ),
        "target_start": TARGET_YEAR,
        "recruitment_status": (
            "CONFIRMED_2027_EVIDENCE"
        ),
        "profile_verified": "Yes",
        "quote_verified": "Yes",
        "checked_date": checked_date,
        "research_overlap": (
            ", ".join(matched)
        ),
        "verification_notes": (
            "Three-source check passed: exact "
            "2027 intake, named professor-specific "
            "PhD opportunity, and current official "
            f"profile. {deadline_note}"
        ),
        "recent_paper": "",
        "year": "",
        "citations": "",
        "doi": "",
        "openalex_author_url": "",
        "verified_email": "",
        "status": (
            "2027 recruitment evidence confirmed; "
            "strict email and publication verification "
            "is still required"
        ),
    }

    lead = {
        **candidate,
        "candidate_id": "L001",
        "recruitment_status": (
            "OFFICIAL_2027_AND_"
            "NAMED_OPPORTUNITY_CONFIRMED"
        ),
        "status": (
            "Passed initial three-source "
            "evidence check"
        ),
    }

    return lead, candidate


def archive_old_files():
    existing = [
        path
        for path in (
            CONFIRMED_FILE,
            LEADS_FILE,
            REPORT_FILE,
        )
        if path.exists()
    ]

    if not existing:
        return None

    ARCHIVE_FOLDER.mkdir(
        exist_ok=True
    )

    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    folder = (
        ARCHIVE_FOLDER / stamp
    )

    folder.mkdir(
        exist_ok=False
    )

    for path in existing:
        shutil.copy2(
            path,
            folder / path.name,
        )

    return folder


def write_csv(path, rows):
    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    with temporary.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS,
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(rows)

    temporary.replace(path)


def write_report(
    topic,
    country,
    leads,
    confirmed,
    failures,
):
    lines = [
        (
            "RESEARCH APPLICATION ASSISTANT - "
            "THREE-SOURCE 2027 EVIDENCE REPORT"
        ),
        "=" * 72,
        (
            "Checked: "
            f"{datetime.now(timezone.utc).isoformat()}"
        ),
        (
            "Mode: MANUAL "
            "OFFICIAL-EVIDENCE IMPORT"
        ),
        f"Topic: {topic}",
        f"Country: {country}",
        (
            "Official-page leads: "
            f"{len(leads)}"
        ),
        (
            "Confirmed candidates: "
            f"{len(confirmed)}"
        ),
        "",
        (
            "A candidate passes only when "
            "three official sources agree:"
        ),
        (
            "1. Exact 2027 PhD intake "
            "or scholarship evidence"
        ),
        (
            "2. A named professor-specific "
            "PhD opportunity"
        ),
        (
            "3. A current official professor "
            "profile with complete research fit"
        ),
        "",
        (
            "Publication authorship and "
            "institutional email are checked later."
        ),
        "",
        "CONFIRMED CANDIDATES",
        "-" * 72,
    ]

    if not confirmed:
        lines.append(
            "No professor passed the complete "
            "three-source check."
        )

    for candidate in confirmed:
        lines.extend(
            [
                "",
                (
                    "ID: "
                    f"{candidate['candidate_id']}"
                ),
                (
                    "NAME: "
                    f"{candidate['name']}"
                ),
                (
                    "INSTITUTION: "
                    f"{candidate['institution']}"
                ),
                (
                    "COUNTRY: "
                    f"{candidate['country']}"
                ),
                (
                    "RESEARCH MATCH: "
                    f"{candidate['research_overlap']}"
                ),
                (
                    "2027 INTAKE URL: "
                    f"{candidate['recruitment_url']}"
                ),
                (
                    "2027 QUOTE: "
                    f"{candidate['recruitment_quote']}"
                ),
                (
                    "OPPORTUNITY URL: "
                    f"{candidate['opportunity_url']}"
                ),
                (
                    "OPPORTUNITY QUOTE: "
                    f"{candidate['opportunity_quote']}"
                ),
                (
                    "PROFILE URL: "
                    f"{candidate['official_profile_url']}"
                ),
                (
                    "STATUS: "
                    f"{candidate['recruitment_status']}"
                ),
                (
                    "NOTES: "
                    f"{candidate['verification_notes']}"
                ),
            ]
        )

    lines.extend(
        [
            "",
            "CHECK NOTES",
            "-" * 72,
        ]
    )

    if failures:
        for failure in failures:
            lines.append(
                f"- {failure}"
            )

    else:
        lines.append(
            "No evidence-check errors "
            "were recorded."
        )

    temporary = REPORT_FILE.with_suffix(
        ".txt.tmp"
    )

    temporary.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    temporary.replace(
        REPORT_FILE
    )


def main():
    print("=" * 72)
    print(
        "RESEARCH APPLICATION ASSISTANT - "
        "STRICT 2027 OFFICIAL-EVIDENCE IMPORT"
    )
    print("=" * 72)

    print()
    print(
        "This process does not use Gemini "
        "or consume API quota."
    )
    print(
        "It does not search noisy "
        "public indexes."
    )
    print(
        "It verifies linked official "
        "evidence supplied by the user."
    )

    topic = "Not entered"
    country = "Not entered"
    leads = []
    confirmed = []
    failures = []

    try:
        read_student_evidence()

        (
            topic,
            country,
        ) = ask_basic_details()

        print()
        print(
            f"Topic: {topic}"
        )
        print(
            f"Country: {country}"
        )
        print(
            "Target start: 2027"
        )

        confirmation = input(
            "\nType YES to begin "
            "evidence checks: "
        ).strip().upper()

        if confirmation != "YES":
            print(
                "Cancelled. No files "
                "were changed."
            )

            input(
                "\nPress Enter to close..."
            )
            return

        (
            lead,
            candidate,
        ) = collect_and_validate(
            topic,
            country,
        )

        leads = [lead]
        confirmed = [candidate]

    except Exception as error:
        failures.append(
            str(error)
        )

        print()
        print(
            "Evidence could not be confirmed: "
            f"{error}"
        )

    print()
    print(
        "Saving the evidence report..."
    )

    archive = archive_old_files()

    write_csv(
        LEADS_FILE,
        leads,
    )

    write_csv(
        CONFIRMED_FILE,
        confirmed,
    )

    write_report(
        topic,
        country,
        leads,
        confirmed,
        failures,
    )

    print()
    print(
        "Evidence session finished."
    )
    print(
        "Confirmed professors: "
        f"{len(confirmed)}"
    )
    print(
        f"Report: {REPORT_FILE.name}"
    )
    print(
        f"Candidates: {CONFIRMED_FILE.name}"
    )

    if archive:
        print(
            "Previous evidence backup: "
            f"{archive}"
        )

    if confirmed:
        print()
        print(
            "Return to the app and "
            "click Refresh Status."
        )
        print(
            "Then run Strict "
            "Professor Verification."
        )

    else:
        print()
        print(
            "No professor was approved. "
            "Review the report."
        )
        print(
            "Do not contact anyone "
            "from this run."
        )

    input(
        "\nPress Enter to close this window..."
    )


if __name__ == "__main__":
    main()
