import base64
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path


BASE_FOLDER = Path(__file__).resolve().parent

VERIFICATION_FILE = (
    BASE_FOLDER / "verified_professor.json"
)

EVIDENCE_FILE = (
    BASE_FOLDER / "student_research_evidence.json"
)

CONTACT_FILE = (
    BASE_FOLDER / "applicant_contact.json"
)

MASTER_CV = (
    BASE_FOLDER / "Master_CV.docx"
)

CV_MANIFEST_FILE = (
    BASE_FOLDER
    / "tailored_cvs"
    / "latest_tailored_cv_manifest.json"
)

OUTPUT_TEXT = (
    BASE_FOLDER / "email_draft.txt"
)

OUTPUT_JSON = (
    BASE_FOLDER / "email_draft.json"
)

ARCHIVE_FOLDER = (
    BASE_FOLDER / "email_archive"
)

CLIENT_SECRET_FILE = (
    BASE_FOLDER / "credentials.json"
)

TOKEN_FILE = (
    BASE_FOLDER / "token.json"
)

VERIFICATION_MAX_AGE_DAYS = 14

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose"
]

FREE_EMAIL_HOSTS = {
    "aol.com",
    "gmail.com",
    "hotmail.com",
    "icloud.com",
    "live.com",
    "outlook.com",
    "proton.me",
    "protonmail.com",
    "yahoo.com",
}

AI_STYLE_PHRASES = (
    "closely aligns",
    "cutting-edge",
    "esteemed",
    "groundbreaking",
    "i am writing to express my strong interest",
    "i would welcome the opportunity",
    "leverage my skills",
    "particularly fascinating",
    "strong interest in pursuing",
)

GENETICS_TOPIC_TERMS = {
    "addiction",
    "genetic",
    "genetics",
    "genomic",
    "genomics",
    "molecular",
    "neurogenetic",
    "neurogenetics",
    "pharmacogenetic",
    "pharmacogenetics",
    "rasgrf2",
    "sequencing",
    "variant",
    "variants",
}

COMPUTATIONAL_TOPIC_TERMS = {
    "acetylcholinesterase",
    "admet",
    "alzheimer",
    "alzheimer's",
    "computational",
    "docking",
    "drug",
    "dynamics",
    "neurodegeneration",
    "neurodegenerative",
    "phytochemical",
    "phytochemicals",
}


def load_json(
    path,
    description,
):
    if not path.exists():
        raise FileNotFoundError(
            f"{description} was not found: "
            f"{path.name}"
        )

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except json.JSONDecodeError as error:
        raise ValueError(
            f"{description} is not valid JSON."
        ) from error


def sha256_file(path):
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def words(value):
    return set(
        re.findall(
            r"[a-z][a-z0-9'-]+",
            clean(value).casefold(),
        )
    )


def parse_utc(
    value,
    description,
):
    try:
        parsed = datetime.fromisoformat(
            str(value).replace(
                "Z",
                "+00:00",
            )
        )

    except (
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{description} has an invalid date."
        ) from error

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    )


def require_recent_verification(
    verification,
):
    checked = parse_utc(
        verification.get(
            "checked_at_utc",
            "",
        ),
        "verified_professor.json",
    )

    age = (
        datetime.now(timezone.utc)
        - checked
    )

    if age.total_seconds() < 0:
        raise ValueError(
            "The professor verification "
            "date is in the future."
        )

    if (
        age.days
        > VERIFICATION_MAX_AGE_DAYS
    ):
        raise ValueError(
            "The professor verification is "
            f"more than "
            f"{VERIFICATION_MAX_AGE_DAYS} "
            "days old. Verify the professor "
            "again."
        )


def valid_email(value):
    return (
        re.fullmatch(
            r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"[A-Za-z0-9-]+"
            r"(?:\.[A-Za-z0-9-]+)+",
            str(value or ""),
        )
        is not None
    )


def require_institutional_email(
    value,
):
    email = clean(value).lower()

    if not valid_email(email):
        raise ValueError(
            "A valid verified professor "
            "email was not found."
        )

    host = email.rsplit(
        "@",
        1,
    )[1]

    if host in FREE_EMAIL_HOSTS:
        raise ValueError(
            "The professor email uses a "
            "public provider instead of an "
            "institutional domain."
        )

    return email


def check_verification(
    verification,
    evidence,
):
    if (
        verification.get(
            "schema_version",
            0,
        )
        < 3
    ):
        raise ValueError(
            "The professor report came from "
            "the old verification workflow."
        )

    if (
        verification.get(
            "ready_for_contact"
        )
        != "YES"
    ):
        blockers = verification.get(
            "blockers",
            [],
        )

        detail = (
            "; ".join(blockers)
            if blockers
            else "Verification failed."
        )

        raise ValueError(
            "This professor is not approved "
            "for contact. "
            + detail
        )

    if (
        verification.get(
            "recruitment_reverified"
        )
        is not True
    ):
        raise ValueError(
            "The 2027 recruitment evidence "
            "was not reverified."
        )

    if (
        verification.get(
            "research_fit_passed"
        )
        is not True
    ):
        raise ValueError(
            "The verified research-fit "
            "check did not pass."
        )

    if (
        evidence.get(
            "approved_by_user"
        )
        is not True
    ):
        raise ValueError(
            "The student research evidence "
            "is not approved."
        )

    applicant = clean(
        evidence.get(
            "applicant_name",
            "",
        )
    )

    report_applicant = clean(
        verification.get(
            "student_evidence_applicant",
            "",
        )
    )

    if (
        not applicant
        or applicant.casefold()
        != report_applicant.casefold()
    ):
        raise ValueError(
            "The professor report and "
            "student evidence belong to "
            "different applicants."
        )

    required_fields = (
        (
            "candidate_id",
            "candidate ID",
        ),
        (
            "name",
            "professor name",
        ),
        (
            "institution",
            "institution",
        ),
        (
            "research_topic",
            "research topic",
        ),
    )

    for (
        field,
        description,
    ) in required_fields:
        if not clean(
            verification.get(
                field,
                "",
            )
        ):
            raise ValueError(
                "The verified "
                f"{description} is missing."
            )

    require_recent_verification(
        verification
    )

    recipient = (
        require_institutional_email(
            verification.get(
                "institutional_email",
                "",
            )
        )
    )

    return applicant, recipient


def number_value(value):
    try:
        return int(
            value or 0
        )

    except (
        TypeError,
        ValueError,
    ):
        return 0


def choose_verified_publication(
    verification,
):
    accepted = []

    for publication in verification.get(
        "verified_publications",
        [],
    ):
        if (
            publication.get(
                "professor_authorship_verified"
            )
            is not True
        ):
            continue

        if (
            publication.get(
                "doi_found_on_official_profile"
            )
            is not True
        ):
            continue

        if not publication.get(
            "matched_research_terms"
        ):
            continue

        if not clean(
            publication.get(
                "title",
                "",
            )
        ):
            continue

        if not clean(
            publication.get(
                "doi",
                "",
            )
        ):
            continue

        accepted.append(
            publication
        )

    if not accepted:
        raise ValueError(
            "No relevant professor-authored "
            "publication passed all checks."
        )

    accepted.sort(
        key=lambda item: (
            number_value(
                item.get(
                    "relevance_score"
                )
            ),
            number_value(
                item.get(
                    "year"
                )
            ),
        ),
        reverse=True,
    )

    return accepted[0]


def safe_relative_file(
    relative_value,
    required_parent,
):
    relative_path = Path(
        str(relative_value or "")
    )

    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
    ):
        raise ValueError(
            "The CV manifest contains "
            "an unsafe output path."
        )

    resolved = (
        BASE_FOLDER
        / relative_path
    ).resolve()

    parent = (
        required_parent.resolve()
    )

    if parent not in resolved.parents:
        raise ValueError(
            "The CV file is outside the "
            "tailored_cvs folder."
        )

    return resolved


def check_cv_manifest(
    manifest,
    verification,
    evidence,
):
    if (
        manifest.get(
            "schema_version",
            0,
        )
        < 1
    ):
        raise ValueError(
            "The tailored CV manifest "
            "is not supported."
        )

    if (
        manifest.get(
            "master_cv_unchanged"
        )
        is not True
    ):
        raise ValueError(
            "The CV manifest did not "
            "confirm the master CV as safe."
        )

    exact_checks = (
        (
            "applicant_name",
            evidence.get(
                "applicant_name",
                "",
            ),
        ),
        (
            "professor_name",
            verification.get(
                "name",
                "",
            ),
        ),
        (
            "candidate_id",
            verification.get(
                "candidate_id",
                "",
            ),
        ),
        (
            "research_topic",
            verification.get(
                "research_topic",
                "",
            ),
        ),
    )

    for (
        field,
        expected,
    ) in exact_checks:
        actual = clean(
            manifest.get(
                field,
                "",
            )
        )

        if (
            actual.casefold()
            != clean(expected).casefold()
        ):
            raise ValueError(
                "The tailored CV does not "
                "match the currently verified "
                f"professor ({field} mismatch)."
            )

    if not MASTER_CV.exists():
        raise FileNotFoundError(
            "Master_CV.docx was not found."
        )

    if (
        sha256_file(MASTER_CV)
        != manifest.get(
            "source_master_sha256"
        )
    ):
        raise ValueError(
            "Master_CV.docx changed after "
            "the tailored CV was created. "
            "Create the tailored CV again."
        )

    cv_path = safe_relative_file(
        manifest.get(
            "output_file",
            "",
        ),
        BASE_FOLDER / "tailored_cvs",
    )

    if not cv_path.exists():
        raise FileNotFoundError(
            "The tailored CV named in the "
            "manifest is missing."
        )

    if (
        sha256_file(cv_path)
        != manifest.get(
            "output_sha256"
        )
    ):
        raise ValueError(
            "The tailored CV changed after "
            "approval. Inspect it and create "
            "it again."
        )

    return cv_path


def create_contact_file(
    applicant_name,
):
    print()
    print(
        "Applicant contact details have "
        "not been saved yet."
    )
    print(
        "Enter them once. They can be "
        "edited later in "
        "applicant_contact.json."
    )

    degree = input(
        "Degree (for example, "
        "MPhil in Forensic Science): "
    ).strip()

    institution = input(
        "Degree institution: "
    ).strip()

    email = input(
        "Applicant Gmail address: "
    ).strip().lower()

    phone = input(
        "Phone number (optional): "
    ).strip()

    orcid = input(
        "ORCID URL (optional): "
    ).strip()

    if (
        not degree
        or not institution
        or not valid_email(email)
    ):
        raise ValueError(
            "Degree, institution, and a "
            "valid applicant email are "
            "required."
        )

    if (
        orcid
        and not re.fullmatch(
            r"https://orcid\.org/"
            r"\d{4}-\d{4}-\d{4}-"
            r"\d{3}[\dX]",
            orcid,
            re.IGNORECASE,
        )
    ):
        raise ValueError(
            "The ORCID URL is not valid."
        )

    record = {
        "schema_version": 1,
        "applicant_name": (
            applicant_name
        ),
        "degree": clean(
            degree
        ),
        "degree_institution": clean(
            institution
        ),
        "email": email,
        "phone": clean(
            phone
        ),
        "orcid": clean(
            orcid
        ),
    }

    print()
    print(
        "Please check these details:"
    )

    for key, value in record.items():
        if key == "schema_version":
            continue

        label = key.replace(
            "_",
            " ",
        ).title()

        print(
            f"{label}: "
            f"{value or 'Not supplied'}"
        )

    confirmation = input(
        "\nType YES to save these "
        "applicant details: "
    ).strip().upper()

    if confirmation != "YES":
        raise ValueError(
            "Applicant contact setup "
            "was cancelled."
        )

    temporary = (
        CONTACT_FILE.with_suffix(
            ".json.tmp"
        )
    )

    temporary.write_text(
        json.dumps(
            record,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary.replace(
        CONTACT_FILE
    )

    return record


def read_contact(
    applicant_name,
):
    if not CONTACT_FILE.exists():
        return create_contact_file(
            applicant_name
        )

    contact = load_json(
        CONTACT_FILE,
        "applicant_contact.json",
    )

    if (
        contact.get(
            "schema_version",
            0,
        )
        < 1
    ):
        raise ValueError(
            "applicant_contact.json "
            "is not supported."
        )

    saved_name = clean(
        contact.get(
            "applicant_name",
            "",
        )
    )

    if (
        saved_name.casefold()
        != applicant_name.casefold()
    ):
        raise ValueError(
            "applicant_contact.json "
            "belongs to a different "
            "applicant."
        )

    if not clean(
        contact.get(
            "degree",
            "",
        )
    ):
        raise ValueError(
            "The applicant degree is missing."
        )

    if not clean(
        contact.get(
            "degree_institution",
            "",
        )
    ):
        raise ValueError(
            "The degree institution is missing."
        )

    if not valid_email(
        clean(
            contact.get(
                "email",
                "",
            )
        )
    ):
        raise ValueError(
            "The applicant email is invalid."
        )

    return contact


def evidence_contains(
    evidence_text,
    required_terms,
):
    lowered = (
        str(evidence_text).casefold()
    )

    missing = [
        term
        for term in required_terms
        if term.casefold()
        not in lowered
    ]

    if missing:
        raise ValueError(
            "Approved student evidence is "
            "missing support for: "
            + ", ".join(missing)
        )


def select_student_paragraph(
    verification,
    evidence,
):
    topic_text = clean(
        str(
            verification.get(
                "research_topic",
                "",
            )
        )
        + " "
        + " ".join(
            verification.get(
                "verified_overlap_terms",
                [],
            )
        )
    )

    topic_words = words(
        topic_text
    )

    genetics_score = len(
        topic_words
        & GENETICS_TOPIC_TERMS
    )

    computational_score = len(
        topic_words
        & COMPUTATIONAL_TOPIC_TERMS
    )

    if (
        genetics_score
        == computational_score
    ):
        raise ValueError(
            "The verified topic does not "
            "identify one clear student "
            "research track. Review the "
            "verification report instead "
            "of blending projects."
        )

    evidence_text = evidence.get(
        "approved_search_evidence",
        "",
    )

    if (
        genetics_score
        > computational_score
    ):
        evidence_contains(
            evidence_text,
            (
                "RASGRF2",
                "exon 15",
                "PCR",
                "Sanger sequencing",
            ),
        )

        return (
            "My MPhil research examined "
            "variants in exon 15 of the "
            "RASGRF2 gene in relation to "
            "drug addiction vulnerability. "
            "The work involved DNA extraction, "
            "PCR, gel electrophoresis, Sanger "
            "sequencing, and variant analysis."
        ), "addiction_genetics"

    evidence_contains(
        evidence_text,
        (
            "Astragalus zederbaueri",
            "acetylcholinesterase",
            "molecular docking",
            "molecular dynamics",
        ),
    )

    return (
        "My recent publication examined "
        "phytochemicals from Astragalus "
        "zederbaueri as acetylcholinesterase "
        "inhibitors. The work used molecular "
        "docking, protein modelling, molecular "
        "dynamics, and ADMET and toxicity "
        "analysis."
    ), "computational_neurodegeneration"


def professor_surname(name):
    parts = re.findall(
        r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+",
        str(name or ""),
    )

    if not parts:
        raise ValueError(
            "The verified professor name "
            "is invalid."
        )

    return parts[-1]


def subject_topic(value):
    topic = clean(value).strip(
        " .,:;-"
    )

    if not topic:
        raise ValueError(
            "The verified research topic "
            "is missing."
        )

    if len(topic) > 80:
        raise ValueError(
            "The verified research topic is "
            "too long for a safe subject line."
        )

    if re.search(
        r"[\r\n]|https?://",
        topic,
        re.IGNORECASE,
    ):
        raise ValueError(
            "The verified research topic "
            "is unsafe."
        )

    return topic


def degree_with_article(value):
    degree = clean(value)

    if re.match(
        r"^(?:a|an|the)\s+",
        degree,
        re.IGNORECASE,
    ):
        return degree

    first_word = (
        degree.split()[0].casefold()
        if degree
        else ""
    )

    use_an = first_word.startswith(
        (
            "mphil",
            "msc",
            "ma",
            "mres",
        )
    )

    article = (
        "an"
        if use_an
        else "a"
    )

    return (
        f"{article} {degree}"
    )


def build_signature(contact):
    lines = [
        "Best regards,",
        clean(
            contact.get(
                "applicant_name",
                "",
            )
        ),
        clean(
            contact.get(
                "degree",
                "",
            )
        ),
        clean(
            contact.get(
                "degree_institution",
                "",
            )
        ),
        clean(
            contact.get(
                "email",
                "",
            )
        ),
    ]

    if clean(
        contact.get(
            "phone",
            "",
        )
    ):
        lines.append(
            clean(
                contact["phone"]
            )
        )

    if clean(
        contact.get(
            "orcid",
            "",
        )
    ):
        lines.append(
            clean(
                contact["orcid"]
            )
        )

    return "\n".join(
        lines
    )


def build_draft(
    verification,
    contact,
    publication,
    student_paragraph,
):
    professor_name = clean(
        verification.get(
            "name",
            "",
        )
    )

    topic = subject_topic(
        verification.get(
            "research_topic",
            "",
        )
    )

    surname = professor_surname(
        professor_name
    )

    title = clean(
        publication.get(
            "title",
            "",
        )
    )

    doi = clean(
        publication.get(
            "doi",
            "",
        )
    )

    subject = (
        f"PhD inquiry: {topic}"
    )

    body = (
        f"Dear Professor {surname},\n\n"
        f"My name is "
        f"{contact['applicant_name']}. "
        f"I recently completed "
        f"{degree_with_article(contact['degree'])} "
        f"at "
        f"{contact['degree_institution']}. "
        "I am contacting you about the "
        "advertised 2027 PhD opportunity "
        "connected with your work in "
        f"{topic}.\n\n"
        f'I noticed your publication "{title}" '
        f"(DOI: {doi}) while reviewing your "
        "recent work.\n\n"
        f"{student_paragraph}\n\n"
        "The project's focus on "
        f"{topic} is relevant to this "
        "background. Could you let me know "
        "whether you would consider my "
        "experience suitable and whether "
        "there are any additional materials "
        "I should send? My CV is attached."
        "\n\n"
        "Thank you for your time."
        "\n\n"
        f"{build_signature(contact)}"
    )

    return subject, body


def validate_draft(
    subject,
    body,
    verification,
    publication,
):
    if (
        "2027" in subject
        or re.search(
            r"\bfall\b",
            subject,
            re.IGNORECASE,
        )
    ):
        raise ValueError(
            "The subject must not contain "
            "an intake season or 2027."
        )

    if (
        "\n" in subject
        or "\r" in subject
    ):
        raise ValueError(
            "The subject contains "
            "a line break."
        )

    publication_title = clean(
        publication.get(
            "title",
            "",
        )
    )

    publication_doi = clean(
        publication.get(
            "doi",
            "",
        )
    )

    if (
        publication_title
        not in body
    ):
        raise ValueError(
            "The verified publication "
            "title is missing."
        )

    if publication_doi not in body:
        raise ValueError(
            "The verified publication "
            "DOI is missing."
        )

    if (
        "advertised 2027 PhD opportunity"
        not in body
    ):
        raise ValueError(
            "The body does not identify "
            "the verified 2027 opportunity."
        )

    research_topic = clean(
        verification.get(
            "research_topic",
            "",
        )
    )

    if research_topic not in body:
        raise ValueError(
            "The verified research topic "
            "is missing."
        )

    lowered = body.casefold()

    for phrase in AI_STYLE_PHRASES:
        if phrase in lowered:
            raise ValueError(
                "The draft contains the "
                "AI-style phrase "
                f'"{phrase}".'
            )

    word_count = len(
        body.split()
    )

    if not (
        120
        <= word_count
        <= 240
    ):
        raise ValueError(
            "The email has "
            f"{word_count} words; the "
            "allowed range is 120-240."
        )


def archive_previous_drafts():
    existing = [
        path
        for path in (
            OUTPUT_TEXT,
            OUTPUT_JSON,
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


def save_local_draft(record):
    archive = (
        archive_previous_drafts()
    )

    text = (
        f"TO: {record['to']}\n"
        f"SUBJECT: {record['subject']}"
        "\n\n"
        f"{record['body']}\n"
    )

    temporary_text = (
        OUTPUT_TEXT.with_suffix(
            ".txt.tmp"
        )
    )

    temporary_json = (
        OUTPUT_JSON.with_suffix(
            ".json.tmp"
        )
    )

    temporary_text.write_text(
        text,
        encoding="utf-8",
    )

    temporary_json.write_text(
        json.dumps(
            record,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary_text.replace(
        OUTPUT_TEXT
    )

    temporary_json.replace(
        OUTPUT_JSON
    )

    return archive


def gmail_service():
    try:
        from google.auth.transport.requests import (
            Request,
        )
        from google.oauth2.credentials import (
            Credentials,
        )
        from google_auth_oauthlib.flow import (
            InstalledAppFlow,
        )
        from googleapiclient.discovery import (
            build,
        )

    except ImportError as error:
        raise RuntimeError(
            "Gmail libraries are missing. "
            "Install google-api-python-client, "
            "google-auth-oauthlib, and "
            "google-auth-httplib2."
        ) from error

    credentials = None

    if TOKEN_FILE.exists():
        try:
            credentials = (
                Credentials
                .from_authorized_user_file(
                    str(TOKEN_FILE),
                    SCOPES,
                )
            )

        except Exception as error:
            raise RuntimeError(
                "token.json could not be read "
                "safely. Keep a backup and "
                "reauthorize Gmail."
            ) from error

    if (
        credentials
        and not credentials.has_scopes(
            SCOPES
        )
    ):
        raise RuntimeError(
            "token.json does not include "
            "Gmail draft permission. Keep a "
            "backup, remove it manually, and "
            "authorize again."
        )

    if (
        credentials
        and credentials.expired
        and credentials.refresh_token
    ):
        credentials.refresh(
            Request()
        )

        TOKEN_FILE.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

    if (
        not credentials
        or not credentials.valid
    ):
        if not CLIENT_SECRET_FILE.exists():
            raise FileNotFoundError(
                "credentials.json was "
                "not found."
            )

        flow = (
            InstalledAppFlow
            .from_client_secrets_file(
                str(CLIENT_SECRET_FILE),
                SCOPES,
            )
        )

        credentials = (
            flow.run_local_server(
                port=0
            )
        )

        TOKEN_FILE.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

    return build(
        "gmail",
        "v1",
        credentials=credentials,
    )


def create_gmail_draft(
    record,
    cv_path,
    contact,
):
    service = gmail_service()

    gmail_profile = (
        service.users()
        .getProfile(
            userId="me"
        )
        .execute()
    )

    gmail_address = clean(
        gmail_profile.get(
            "emailAddress",
            "",
        )
    ).lower()

    applicant_email = clean(
        contact.get(
            "email",
            "",
        )
    ).lower()

    if (
        gmail_address
        != applicant_email
    ):
        raise ValueError(
            "The signed-in Gmail account "
            "does not match "
            "applicant_contact.json. "
            f"Signed in: "
            f"{gmail_address or 'unknown'}; "
            f"expected: {applicant_email}."
        )

    message = EmailMessage()

    message["To"] = record["to"]
    message["From"] = gmail_address
    message["Subject"] = (
        record["subject"]
    )

    message.set_content(
        record["body"]
    )

    message.add_attachment(
        cv_path.read_bytes(),
        maintype="application",
        subtype=(
            "vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        filename=cv_path.name,
    )

    raw = base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode(
        "ascii"
    )

    result = (
        service.users()
        .drafts()
        .create(
            userId="me",
            body={
                "message": {
                    "raw": raw
                }
            },
        )
        .execute()
    )

    return result.get(
        "id",
        "",
    )


def main():
    print("=" * 68)
    print(
        "RESEARCH APPLICATION ASSISTANT — "
        "EVIDENCE-ONLY EMAIL DRAFT"
    )
    print("=" * 68)

    print()
    print(
        "This workflow does not use AI "
        "or consume API quota."
    )
    print(
        "It creates a Gmail draft only. "
        "It never sends an email."
    )

    try:
        verification = load_json(
            VERIFICATION_FILE,
            "verified_professor.json",
        )

        evidence = load_json(
            EVIDENCE_FILE,
            "student_research_evidence.json",
        )

        (
            applicant_name,
            recipient,
        ) = check_verification(
            verification,
            evidence,
        )

        publication = (
            choose_verified_publication(
                verification
            )
        )

        manifest = load_json(
            CV_MANIFEST_FILE,
            "latest_tailored_cv_manifest.json",
        )

        cv_path = check_cv_manifest(
            manifest,
            verification,
            evidence,
        )

        contact = read_contact(
            applicant_name
        )

        (
            student_paragraph,
            research_track,
        ) = select_student_paragraph(
            verification,
            evidence,
        )

        (
            subject,
            body,
        ) = build_draft(
            verification,
            contact,
            publication,
            student_paragraph,
        )

        validate_draft(
            subject,
            body,
            verification,
            publication,
        )

    except Exception as error:
        print()
        print(
            "Email drafting could not "
            f"start: {error}"
        )
        print(
            "No local or Gmail draft "
            "was created."
        )
        input(
            "\nPress Enter to close..."
        )
        return

    print()
    print(
        "Verified recipient: "
        f"{verification.get('name', '')}"
    )
    print(
        "Institution: "
        f"{verification.get('institution', '')}"
    )
    print(
        f"Institutional email: "
        f"{recipient}"
    )
    print(
        f"Research track: "
        f"{research_track}"
    )
    print(
        f"Attached CV: "
        f"{cv_path.name}"
    )

    print(
        "\n" + "-" * 68
    )

    print(
        f"SUBJECT: {subject}\n"
    )

    print(body)

    print(
        "-" * 68
    )

    print(
        "\nWord count: "
        f"{len(body.split())}"
    )

    approval = input(
        "\nRead every line. Type YES "
        "to save this local draft: "
    ).strip().upper()

    if approval != "YES":
        print(
            "Cancelled. No draft was "
            "saved or created in Gmail."
        )
        input(
            "\nPress Enter to close..."
        )
        return

    record = {
        "schema_version": 1,
        "created_at_utc": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "candidate_id": (
            verification.get(
                "candidate_id",
                "",
            )
        ),
        "professor_name": (
            verification.get(
                "name",
                "",
            )
        ),
        "institution": (
            verification.get(
                "institution",
                "",
            )
        ),
        "to": recipient,
        "subject": subject,
        "body": body,
        "verified_publication_title": (
            publication.get(
                "title",
                "",
            )
        ),
        "verified_publication_doi": (
            publication.get(
                "doi",
                "",
            )
        ),
        "research_track": (
            research_track
        ),
        "cv_file": str(
            cv_path.relative_to(
                BASE_FOLDER
            )
        ),
        "cv_sha256": (
            sha256_file(
                cv_path
            )
        ),
        "gmail_draft_created": False,
    }

    archive = save_local_draft(
        record
    )

    print()
    print(
        "Local draft saved to: "
        f"{OUTPUT_TEXT.name}"
    )

    if archive:
        print(
            "Previous draft backup: "
            f"{archive}"
        )

    typed_recipient = input(
        "\nTo unlock Gmail, type the "
        "institutional email exactly\n"
        f"({recipient}): "
    ).strip().lower()

    if typed_recipient != recipient:
        print(
            "Email did not match. Gmail "
            "draft creation was cancelled."
        )
        print(
            "The local draft remains "
            "saved for review."
        )
        input(
            "\nPress Enter to close..."
        )
        return

    gmail_confirmation = input(
        "Type GMAIL to create the "
        "unsent Gmail draft: "
    ).strip().upper()

    if gmail_confirmation != "GMAIL":
        print(
            "Gmail draft creation cancelled. "
            "The local draft remains saved."
        )
        input(
            "\nPress Enter to close..."
        )
        return

    try:
        draft_id = create_gmail_draft(
            record,
            cv_path,
            contact,
        )

        record[
            "gmail_draft_created"
        ] = True

        record[
            "gmail_draft_id"
        ] = draft_id

        OUTPUT_JSON.write_text(
            json.dumps(
                record,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    except Exception as error:
        print()
        print(
            "Gmail draft could not be "
            f"created: {error}"
        )
        print(
            "The local draft remains saved. "
            "No email was sent."
        )
        input(
            "\nPress Enter to close..."
        )
        return

    print()
    print(
        "Unsent Gmail draft created "
        "successfully."
    )
    print(
        "Open Gmail Drafts and inspect "
        "the recipient, text, and attachment."
    )
    print(
        "The app did not send the email."
    )

    input(
        "\nPress Enter to close this window..."
    )


if __name__ == "__main__":
    main()
