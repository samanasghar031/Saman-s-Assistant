import csv
import io
import json
import re
import shutil
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import (
    quote,
    unquote,
    urljoin,
    urlparse,
)

import requests
from bs4 import BeautifulSoup


BASE_FOLDER = Path(__file__).resolve().parent
CANDIDATES_FILE = BASE_FOLDER / "professor_candidates.csv"
EVIDENCE_FILE = BASE_FOLDER / "student_research_evidence.json"
OUTPUT_JSON = BASE_FOLDER / "verified_professor.json"
OUTPUT_TEXT = BASE_FOLDER / "verified_professor.txt"
ARCHIVE_FOLDER = BASE_FOLDER / "verification_archive"

TARGET_YEAR = "2027"
WEB_TIMEOUT = 30
MAX_DOIS = 40
MAX_PUBLICATIONS_IN_REPORT = 10

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AcademicResearchAssistant/4.0"
)

FREE_EMAIL_HOSTS = {
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "yahoo.com",
}

FORMER_POSITION_TERMS = (
    "deceased",
    "emerita",
    "emeritus",
    "former professor",
    "in memoriam",
    "retired",
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
    "senior lecturer",
)

TOPIC_GROUPS = {
    "addiction/substance use": (
        "addiction",
        "addictive",
        "alcohol",
        "alcohol use",
        "cannabis",
        "drug dependence",
        "nicotine",
        "opioid",
        "smoking",
        "substance abuse",
        "substance use",
        "tobacco",
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


def norm(value):
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\u2018", "'").replace("\u2019", "'")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", value).strip().lower()


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def host_of(url):
    return (
        urlparse(url)
        .netloc.lower()
        .split(":")[0]
        .removeprefix("www.")
    )


MULTI_LABEL_PUBLIC_SUFFIXES = {
    "ac.jp",
    "ac.nz",
    "ac.uk",
    "asn.au",
    "co.jp",
    "co.nz",
    "co.uk",
    "com.au",
    "edu.au",
    "edu.cn",
    "edu.hk",
    "edu.sg",
    "gov.au",
    "gov.uk",
    "org.au",
    "org.uk",
}


def institutional_root(url):
    """Return a conservative registrable-domain approximation.

    This intentionally treats departmental university subdomains such as
    ims.utoronto.ca and dfcm.utoronto.ca as the same institution while still
    keeping unrelated domains separate.
    """
    host = host_of(url)
    labels = [part for part in host.split(".") if part]
    if len(labels) < 2:
        return host

    last_two = ".".join(labels[-2:])
    if last_two in MULTI_LABEL_PUBLIC_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def related_hosts(first_url, second_url):
    first = host_of(first_url)
    second = host_of(second_url)
    if not first or not second:
        return False
    return (
        first == second
        or first.endswith("." + second)
        or second.endswith("." + first)
        or institutional_root(first_url) == institutional_root(second_url)
    )


def name_parts(name):
    parts = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+", norm(name))
    return parts


def name_in_text(name, text):
    parts = name_parts(name)
    if len(parts) < 2:
        return False
    lowered = norm(text)
    return parts[0] in lowered and parts[-1] in lowered


def surname(name):
    parts = name_parts(name)
    return parts[-1] if parts else ""


def family_name_variants(name):
    parts = name_parts(name)
    if not parts:
        return set()

    variants = {parts[-1].replace("-", "").replace(" ", "")}
    particles = {
        "al", "da", "de", "del", "der", "di", "du", "la", "le",
        "van", "von",
    }
    if len(parts) >= 2 and parts[-2] in particles:
        variants.add((parts[-2] + parts[-1]).replace("-", ""))
    return variants


def first_initial(name):
    parts = name_parts(name)
    return parts[0][0] if parts and parts[0] else ""


def person_contexts(name, text, radius=700):
    lowered = norm(text)
    family = surname(name)
    if not family:
        return []

    contexts = []
    for match in re.finditer(r"\b" + re.escape(family) + r"\b", lowered):
        start = max(0, match.start() - radius)
        end = min(len(lowered), match.end() + radius)
        contexts.append(lowered[start:end])
    return contexts


def position_contexts(name, profile_text):
    return person_contexts(name, profile_text, radius=700)


def current_position_status(name, profile_text):
    contexts = position_contexts(name, profile_text)
    if not contexts:
        return False

    for context in contexts:
        position_matches = [
            match
            for term in CURRENT_POSITION_TERMS
            for match in re.finditer(r"\b" + re.escape(term) + r"\b", context)
        ]
        if not position_matches:
            continue

        # A retirement label blocks only the local title statement.  A broad
        # biography may legitimately mention a former role elsewhere.
        for match in position_matches:
            nearby = context[
                max(0, match.start() - 100):min(len(context), match.end() + 140)
            ]
            if not any(term in nearby for term in FORMER_POSITION_TERMS):
                return True
    return False


def extract_position(name, profile_text):
    pattern = re.compile(
        r"\b(?:assistant professor|associate professor|full professor|"
        r"professor|principal investigator|group leader|investigator|"
        r"research officer|senior lecturer|lecturer|researcher)\b",
        re.IGNORECASE,
    )
    for context in position_contexts(name, profile_text):
        for match in pattern.finditer(context):
            nearby = context[
                max(0, match.start() - 100):min(len(context), match.end() + 160)
            ]
            if not any(term in nearby for term in FORMER_POSITION_TERMS):
                return clean(nearby)
    return "Not found"


def institution_matches(institution, profile_text):
    words = [
        word
        for word in re.findall(r"[a-z][a-z0-9-]+", norm(institution))
        if len(word) >= 4
        and word not in {"college", "institute", "university"}
    ]
    lowered = norm(profile_text)
    return bool(words and any(word in lowered for word in words))


def read_confirmed_candidates():
    if not CANDIDATES_FILE.exists():
        raise FileNotFoundError("professor_candidates.csv was not found.")

    with CANDIDATES_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)
        fields = set(reader.fieldnames or [])
        required = {
            "recruitment_status",
            "recruitment_url",
            "recruitment_quote",
            "opportunity_url",
            "opportunity_quote",
            "official_profile_url",
        }
        missing = sorted(required - fields)
        if missing:
            raise ValueError(
                "The candidate file uses the old format. Missing fields: "
                + ", ".join(missing)
            )

        return [
            row
            for row in reader
            if row.get("recruitment_status") == "CONFIRMED_2027_EVIDENCE"
        ]


def read_student_evidence():
    if not EVIDENCE_FILE.exists():
        raise FileNotFoundError("student_research_evidence.json was not found.")

    evidence = json.loads(EVIDENCE_FILE.read_text(encoding="utf-8"))
    if evidence.get("approved_by_user") is not True:
        raise ValueError("The student evidence has not been approved.")

    text = clean(evidence.get("approved_search_evidence", ""))
    if len(text) < 200:
        raise ValueError("The approved student evidence is incomplete.")

    return evidence, text


def choose_candidate(candidates):
    if not candidates:
        raise ValueError("No candidate has confirmed 2027 recruitment evidence.")

    print()
    print("Confirmed 2027 candidates:")
    print()
    for row in candidates:
        print(
            f"{row.get('candidate_id', '')}: "
            f"{row.get('name', '')} — {row.get('institution', '')}"
        )

    selected_id = input("\nCandidate ID to verify: ").strip().upper()
    for row in candidates:
        if row.get("candidate_id", "").upper() == selected_id:
            return row
    raise ValueError("That confirmed candidate ID was not found.")


def fetch_document(url):
    if urlparse(url).scheme not in {"http", "https"}:
        raise ValueError("An official http or https URL is required.")

    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=WEB_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()

    final_url = response.url
    content_type = response.headers.get("Content-Type", "").lower()
    is_pdf = (
        "pdf" in content_type
        or final_url.lower().split("?", 1)[0].endswith(".pdf")
    )

    if is_pdf:
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise RuntimeError(
                "PDF evidence needs pypdf. Run: python -m pip install pypdf"
            ) from error

        reader = PdfReader(io.BytesIO(response.content))
        text = clean("\n".join(page.extract_text() or "" for page in reader.pages))
        html = ""
        document_type = "PDF"
    else:
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "svg", "noscript"]):
            tag.decompose()
        text = clean(soup.get_text(" ", strip=True))
        html = response.text
        document_type = "HTML"

    if len(text) < 100:
        raise ValueError("The official document contains too little readable text.")

    return {
        "url": final_url,
        "text": text[:200000],
        "html": html,
        "type": document_type,
    }


def exact_quote_present(quoted_text, page_text):
    quote_text = norm(quoted_text).strip(" .\"'")
    return len(quote_text) >= 30 and quote_text in norm(page_text)


def evidence_quote_supported(quoted_text, page_text):
    """Tolerate harmless formatting changes while preserving evidence checks."""
    if exact_quote_present(quoted_text, page_text):
        return True

    quoted = norm(quoted_text).strip(" .\"'")
    page = norm(page_text)
    quote_tokens = re.findall(r"[a-z0-9]+", quoted)
    page_tokens = re.findall(r"[a-z0-9]+", page)
    if len(quote_tokens) < 12 or len(page_tokens) < 12:
        return False

    quoted_counts = Counter(quote_tokens)
    page_counts = Counter(page_tokens)
    matched = sum(
        min(count, page_counts.get(token, 0))
        for token, count in quoted_counts.items()
    )
    coverage = matched / max(1, sum(quoted_counts.values()))

    # Every four-digit year in the saved evidence must remain on the page.
    years = set(re.findall(r"\b20\d{2}\b", quoted))
    return coverage >= 0.88 and years.issubset(set(re.findall(r"\b20\d{2}\b", page)))


def contains_phd(text):
    return bool(re.search(r"\b(?:ph\.?d|doctoral|doctorate)\b", norm(text)))


def has_2027_intake_evidence(text):
    lowered = norm(text)
    if TARGET_YEAR not in lowered or not contains_phd(lowered):
        return False

    terms = (
        "admission",
        "application",
        "apply",
        "commence",
        "enrolment",
        "enrollment",
        "intake",
        "recruitment",
        "scholarship",
        "start",
    )
    for match in re.finditer(TARGET_YEAR, lowered):
        start = max(0, match.start() - 450)
        end = min(len(lowered), match.end() + 650)
        if any(term in lowered[start:end] for term in terms):
            return True
    return False


def has_professor_opportunity_evidence(text):
    lowered = norm(text)
    patterns = (
        r"(?:accepting|recruiting|seeking|looking for)\b.{0,220}\b(?:ph\.?d|doctoral|student|candidate)",
        r"\b(?:ph\.?d|doctoral)\b.{0,220}\b(?:accepting|recruiting|seeking|looking for|suitable|apply|contact)",
        r"\bsuitable for\b.{0,120}\b(?:ph\.?d|doctoral)\b",
        r"\b(?:ph\.?d|doctoral)\b.{0,160}\b(?:project|position|studentship)\b",
        r"\bcontact (?:the )?supervisors?\b",
    )
    return contains_phd(lowered) and any(
        re.search(pattern, lowered) for pattern in patterns
    )


def official_publication_links(*documents):
    """Collect trusted bibliography links explicitly linked by official pages."""
    links = []
    seen = set()
    trusted_hosts = {
        "pubmed.ncbi.nlm.nih.gov",
    }

    for document in documents:
        html = document.get("html", "")
        base_url = document.get("url", "")
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = urljoin(base_url, anchor.get("href", "").strip())
            host = host_of(href)
            label = norm(anchor.get_text(" ", strip=True))
            if host not in trusted_hosts:
                continue
            if "publication" not in label and "pubmed" not in href.lower():
                continue
            if href not in seen:
                seen.add(href)
                links.append(href)
    return links


def pubmed_author_query(professor_name):
    """Build both PubMed's indexed surname/initial and full-name forms."""
    parts = name_parts(professor_name)
    if len(parts) < 2:
        raise ValueError("A professor's full name is required for PubMed lookup.")

    particles = {
        "al", "da", "de", "del", "der", "di", "du", "la", "le",
        "van", "von",
    }
    family_parts = parts[-2:] if parts[-2] in particles else parts[-1:]
    indexed_name = " ".join(family_parts + [parts[0][0]])
    full_name = " ".join(parts)
    return f'("{indexed_name}"[Author] OR "{full_name}"[Author])'


def pubmed_api_dois(professor_name):
    """Return recent DOIs through NCBI E-utilities, not PubMed HTML."""
    search_response = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={
            "db": "pubmed",
            "term": pubmed_author_query(professor_name),
            "retmode": "json",
            "retmax": str(MAX_DOIS),
            "sort": "pub date",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=WEB_TIMEOUT,
    )
    search_response.raise_for_status()
    identifiers = (
        search_response.json()
        .get("esearchresult", {})
        .get("idlist", [])
    )
    if not identifiers:
        return []

    fetch_response = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        params={
            "db": "pubmed",
            "id": ",".join(identifiers),
            "retmode": "xml",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=WEB_TIMEOUT,
    )
    fetch_response.raise_for_status()
    root = ET.fromstring(fetch_response.content)

    dois = []
    seen = set()
    for article_id in root.findall(".//ArticleId"):
        if article_id.attrib.get("IdType", "").casefold() != "doi":
            continue
        doi = clean(article_id.text or "").casefold()
        if doi and doi not in seen:
            seen.add(doi)
            dois.append(doi)
    return dois[:MAX_DOIS]


def dois_from_official_publication_links(professor_name, *documents):
    links = official_publication_links(*documents)
    dois = []
    seen = set()
    notes = []

    if not links:
        return dois, links, notes

    try:
        for doi in pubmed_api_dois(professor_name):
            if doi not in seen:
                seen.add(doi)
                dois.append(doi)
    except Exception as error:
        notes.append(f"PubMed E-utilities lookup failed ({error})")

    return dois, links, notes


def active_topic_groups(topic):
    lowered = norm(topic)
    return [
        group
        for group, aliases in TOPIC_GROUPS.items()
        if any(alias in lowered for alias in aliases)
    ]


def matched_topic_groups(topic, evidence_text):
    active = active_topic_groups(topic)
    lowered = norm(evidence_text)
    matched = [
        group
        for group in active
        if any(alias in lowered for alias in TOPIC_GROUPS[group])
    ]
    return active, matched, [group for group in active if group not in matched]


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
    lowered = norm(clean(text))
    results = []
    patterns = (
        r"(?P<day>\d{1,2})\s+(?P<month>" + "|".join(MONTHS) + r")\s+(?P<year>20\d{2})",
        r"(?P<month>" + "|".join(MONTHS) + r")\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?[,]?\s+(?P<year>20\d{2})",
        r"(?P<year>20\d{2})-(?P<month_num>\d{2})-(?P<day>\d{2})",
    )
    deadline_terms = (
        "application deadline",
        "applications close",
        "closing date",
        "deadline",
        "submit by",
    )

    for pattern in patterns:
        for match in re.finditer(pattern, lowered):
            context = lowered[max(0, match.start() - 180):match.end() + 40]
            if not any(term in context for term in deadline_terms):
                continue
            year = int(match.group("year"))
            day = int(match.group("day"))
            if match.groupdict().get("month_num"):
                month = int(match.group("month_num"))
            else:
                month = MONTHS[match.group("month")]
            try:
                value = date(year, month, day)
            except ValueError:
                continue
            if value not in results:
                results.append(value)
    return sorted(results)


def extract_email(*page_texts):
    for page_text in page_texts:
        emails = re.findall(
            r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
            page_text or "",
            re.IGNORECASE,
        )
        for email in emails:
            if email.rsplit("@", 1)[-1].lower() not in FREE_EMAIL_HOSTS:
                return email
    return "Not found"


def extract_dois(*sources):
    combined = unquote("\n".join(source or "" for source in sources))
    matches = re.findall(
        r"10\.\d{4,9}/[-._;()/:A-Z0-9]+",
        combined,
        re.IGNORECASE,
    )
    results = []
    seen = set()
    for value in matches:
        doi = value.rstrip(".,;:)'\"]}").lower()
        if doi not in seen:
            seen.add(doi)
            results.append(doi)
        if len(results) >= MAX_DOIS:
            break
    return results


def crossref_work(doi):
    response = requests.get(
        "https://api.crossref.org/works/" + quote(doi, safe=""),
        headers={"User-Agent": USER_AGENT},
        timeout=WEB_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("message", {})


def crossref_year(metadata):
    for key in ("published-print", "published-online", "published", "created"):
        parts = metadata.get(key, {}).get("date-parts", [])
        if parts and parts[0]:
            return str(parts[0][0])
    return "Not found"


def author_matches(metadata, professor_name):
    target_families = family_name_variants(professor_name)
    target_initial = first_initial(professor_name)

    for author in metadata.get("author", []):
        family = (
            norm(author.get("family", ""))
            .replace("-", "")
            .replace(" ", "")
        )
        given = norm(author.get("given", ""))
        family_ok = family in target_families
        initial_ok = not target_initial or not given or given[0] == target_initial
        if family_ok and initial_ok:
            return True
    return False


def author_display(metadata):
    names = []
    for author in metadata.get("author", []):
        name = clean(f"{author.get('given', '')} {author.get('family', '')}")
        if name:
            names.append(name)
    return names


def verify_publications(dois, professor_name, topic):
    verified = []
    failures = []

    for doi in dois:
        try:
            metadata = crossref_work(doi)
        except Exception as error:
            failures.append(f"{doi}: Crossref lookup failed ({error})")
            continue

        if not author_matches(metadata, professor_name):
            failures.append(f"{doi}: professor not found in Crossref authors")
            continue

        titles = metadata.get("title", [])
        title = clean(titles[0] if titles else "Untitled")
        abstract = clean(metadata.get("abstract", ""))
        _, groups, _ = matched_topic_groups(topic, title + " " + abstract)

        verified.append(
            {
                "title": title,
                "doi": doi,
                "doi_url": "https://doi.org/" + doi,
                "year": crossref_year(metadata),
                "authors": author_display(metadata),
                "professor_authorship_verified": True,
                "matched_research_groups": groups,
                "matched_research_terms": groups,
                "relevance_score": len(groups),
                "doi_found_on_official_source": True,
                "doi_found_on_official_profile": True,
            }
        )

        relevant_count = sum(
            item["relevance_score"] >= 1 for item in verified
        )
        if relevant_count >= MAX_PUBLICATIONS_IN_REPORT:
            break

    verified.sort(
        key=lambda item: (item["relevance_score"], item["year"]),
        reverse=True,
    )
    return verified[:MAX_PUBLICATIONS_IN_REPORT], failures


def archive_old_reports():
    existing = [path for path in (OUTPUT_JSON, OUTPUT_TEXT) if path.exists()]
    if not existing:
        return None

    ARCHIVE_FOLDER.mkdir(exist_ok=True)
    folder = ARCHIVE_FOLDER / datetime.now().strftime("%Y%m%d_%H%M%S")
    folder.mkdir(exist_ok=False)
    for path in existing:
        shutil.copy2(path, folder / path.name)
    return folder


def save_reports(report):
    temporary_json = OUTPUT_JSON.with_suffix(".json.tmp")
    temporary_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_json.replace(OUTPUT_JSON)

    lines = [
        "EVIDENCE-FIRST PROFESSOR VERIFICATION",
        "=" * 72,
        f"NAME: {report['name']}",
        f"INSTITUTION: {report['institution']}",
        f"CANDIDATE ID: {report['candidate_id']}",
        f"CHECKED: {report['checked_at_utc']}",
        "",
        f"CURRENT POSITION VERIFIED: {report['current_position_verified']}",
        f"POSITION EVIDENCE: {report['position_evidence']}",
        f"INSTITUTIONAL EMAIL: {report['institutional_email']}",
        f"2027 INTAKE REVERIFIED: {report['intake_reverified']}",
        f"NAMED PHD OPPORTUNITY REVERIFIED: {report['opportunity_reverified']}",
        f"2027 INTAKE QUOTE: {report['recruitment_quote']}",
        f"OPPORTUNITY QUOTE: {report['opportunity_quote']}",
        f"2027 INTAKE URL: {report['recruitment_url']}",
        f"OPPORTUNITY URL: {report['opportunity_url']}",
        f"PROFILE URL: {report['official_profile_url']}",
        "",
        f"RESEARCH TOPIC: {report['research_topic']}",
        "STUDENT RESEARCH GROUPS: "
        + (", ".join(report["student_research_groups"]) or "None"),
        "PROFESSOR RESEARCH GROUPS: "
        + (", ".join(report["professor_research_groups"]) or "None"),
        "VERIFIED OVERLAP GROUPS: "
        + (", ".join(report["verified_overlap_groups"]) or "None"),
        f"RESEARCH FIT EVIDENCE PASSED: {report['research_fit_passed']}",
        "",
        "VERIFIED PROFESSOR PUBLICATIONS",
        "-" * 72,
    ]

    if not report["verified_publications"]:
        lines.append("No relevant professor-authored DOI was verified.")

    for index, publication in enumerate(report["verified_publications"], start=1):
        lines.extend(
            [
                "",
                f"PUBLICATION {index}",
                f"TITLE: {publication['title']}",
                f"YEAR: {publication['year']}",
                f"DOI: {publication['doi']}",
                f"AUTHORS: {', '.join(publication['authors'])}",
                "MATCHED RESEARCH GROUPS: "
                + (", ".join(publication["matched_research_groups"]) or "None"),
                "AUTHORSHIP CHECK: Professor found in Crossref author metadata",
                "SOURCE CHECK: DOI found directly or through the official "
                "profile's PubMed Publications link",
            ]
        )

    lines.extend(
        [
            "",
            "VERIFICATION DECISION",
            "-" * 72,
            f"READY FOR CONTACT: {report['ready_for_contact']}",
            "BLOCKERS: " + ("; ".join(report["blockers"]) or "None"),
            "",
            "No CV or email should be created unless READY FOR CONTACT is YES.",
            "",
        ]
    )

    temporary_text = OUTPUT_TEXT.with_suffix(".txt.tmp")
    temporary_text.write_text("\n".join(lines), encoding="utf-8")
    temporary_text.replace(OUTPUT_TEXT)


def main():
    print("=" * 72)
    print("RESEARCH APPLICATION ASSISTANT — STRICT PROFESSOR VERIFICATION")
    print("=" * 72)
    print()
    print("This process does not use Gemini or consume API quota.")
    print("It accepts only candidates with linked official 2027 evidence.")

    try:
        candidates = read_confirmed_candidates()
        student_record, student_text = read_student_evidence()
        candidate = choose_candidate(candidates)
    except Exception as error:
        print()
        print(f"Could not start verification: {error}")
        input("\nPress Enter to close...")
        return

    name = candidate.get("name", "")
    institution = candidate.get("institution", "")
    topic = candidate.get("research_topic", "")
    intake_quote = candidate.get("recruitment_quote", "")
    opportunity_quote = candidate.get("opportunity_quote", "")
    profile_url = candidate.get("official_profile_url", "")
    intake_url = candidate.get("recruitment_url", "")
    opportunity_url = candidate.get("opportunity_url", "")

    print()
    print(f"Verifying: {name}")
    print("Step 1 of 4: Rechecking all three official sources...")

    try:
        intake = fetch_document(intake_url)
        opportunity = fetch_document(opportunity_url)
        profile = fetch_document(profile_url)
    except Exception as error:
        print()
        print(f"Official-source verification failed: {error}")
        print("The previous verification report was not changed.")
        input("\nPress Enter to close...")
        return

    profile_name_ok = name_in_text(name, profile["text"])
    opportunity_name_ok = name_in_text(name, opportunity["text"])
    position_ok = current_position_status(name, profile["text"])
    institution_ok = institution_matches(institution, profile["text"])
    domains_ok = (
        related_hosts(intake["url"], opportunity["url"])
        and related_hosts(opportunity["url"], profile["url"])
    )

    intake_ok = all(
        (
            has_2027_intake_evidence(intake["text"]),
            evidence_quote_supported(intake_quote, intake["text"]),
            domains_ok,
        )
    )

    opportunity_ok = all(
        (
            opportunity_name_ok,
            has_professor_opportunity_evidence(opportunity["text"]),
            evidence_quote_supported(opportunity_quote, opportunity["text"]),
            domains_ok,
        )
    )

    deadlines = sorted(
        set(
            detected_deadlines(intake["text"])
            + detected_deadlines(opportunity["text"])
        )
    )
    deadline_open = not deadlines or max(deadlines) >= datetime.now(timezone.utc).date()

    print("Step 2 of 4: Comparing research evidence...")
    active_groups = active_topic_groups(topic)
    _, student_groups, student_missing = matched_topic_groups(topic, student_text)
    _, professor_groups, professor_missing = matched_topic_groups(
        topic,
        opportunity["text"] + " " + profile["text"],
    )
    overlap_groups = sorted(set(student_groups) & set(professor_groups))
    research_fit_ok = bool(active_groups) and not student_missing and not professor_missing

    print("Step 3 of 4: Verifying publications and institutional email...")
    direct_dois = extract_dois(
        profile["html"],
        profile["text"],
        opportunity["html"],
        opportunity["text"],
    )
    linked_dois, publication_source_urls, publication_link_notes = (
        dois_from_official_publication_links(name, profile, opportunity)
    )
    official_dois = list(dict.fromkeys(direct_dois + linked_dois))[:MAX_DOIS]
    publications, publication_failures = verify_publications(
        official_dois,
        name,
        topic,
    )
    relevant_publications = [
        item for item in publications if item["relevance_score"] >= 1
    ]

    email = extract_email(
        profile["text"],
        opportunity["text"],
        intake["text"],
    )

    checks = {
        "Name not confirmed on official professor profile": profile_name_ok,
        "Current academic or research position not confirmed": position_ok,
        "Institution not confirmed on official professor profile": institution_ok,
        "The three official sources are not from the same institution": domains_ok,
        "2027 intake evidence did not pass recheck": intake_ok,
        "Named professor-specific PhD opportunity did not pass recheck": opportunity_ok,
        "The stated application deadline has expired": deadline_open,
        "Student evidence does not support every selected research group": not student_missing,
        "Professor evidence does not support every selected research group": not professor_missing,
        "Research overlap did not pass the strict concept check": research_fit_ok,
        "No relevant professor-authored DOI was verified": bool(relevant_publications),
        "Institutional email was not found on an official source": email != "Not found",
    }
    blockers = [message for message, passed in checks.items() if not passed]
    ready = not blockers

    report = {
        "schema_version": 3,
        "candidate_id": candidate.get("candidate_id", ""),
        "name": name,
        "institution": institution,
        "country": candidate.get("country", ""),
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "student_evidence_applicant": student_record.get("applicant_name", ""),
        "official_profile_url": profile["url"],
        "recruitment_url": intake["url"],
        "opportunity_url": opportunity["url"],
        "profile_name_verified": profile_name_ok,
        "opportunity_name_verified": opportunity_name_ok,
        "current_position_verified": position_ok,
        "position_evidence": extract_position(name, profile["text"]),
        "institution_verified": institution_ok,
        "institutional_email": email,
        "intake_reverified": intake_ok,
        "opportunity_reverified": opportunity_ok,
        "recruitment_reverified": intake_ok and opportunity_ok,
        "recruitment_quote": intake_quote,
        "opportunity_quote": opportunity_quote,
        "detected_deadlines": [value.isoformat() for value in deadlines],
        "deadline_open": deadline_open,
        "research_topic": topic,
        "active_research_groups": active_groups,
        "student_research_groups": student_groups,
        "professor_research_groups": professor_groups,
        "verified_overlap_groups": overlap_groups,
        "student_topic_terms": student_groups,
        "profile_topic_terms": professor_groups,
        "verified_overlap_terms": overlap_groups,
        "research_fit_passed": research_fit_ok,
        "official_dois_found": official_dois,
        "profile_dois_found": official_dois,
        "official_publication_source_urls": publication_source_urls,
        "verified_publications": relevant_publications,
        "publication_lookup_notes": publication_link_notes + publication_failures,
        "ready_for_contact": "YES" if ready else "NO",
        "blockers": blockers,
    }

    print("Step 4 of 4: Saving the evidence report...")
    archive = archive_old_reports()
    save_reports(report)

    print()
    print("Verification finished.")
    print(f"READY FOR CONTACT: {report['ready_for_contact']}")
    print(f"Verified relevant publications: {len(relevant_publications)}")
    print(f"Report: {OUTPUT_TEXT.name}")

    if archive:
        print(f"Previous report backup: {archive}")

    if blockers:
        print()
        print("Blockers:")
        for blocker in blockers:
            print(f"- {blocker}")

    print()
    print("Review the report before any CV or email is created.")
    input("\nPress Enter to close this window...")


if __name__ == "__main__":
    main()
