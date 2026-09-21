import csv
import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox


BASE_FOLDER = Path(__file__).resolve().parent

IMPORT_SCRIPT = BASE_FOLDER / "import_research_documents.py"
FIND_SCRIPT = BASE_FOLDER / "find_professors.py"
VERIFY_SCRIPT = BASE_FOLDER / "verify_professor.py"
TAILOR_SCRIPT = BASE_FOLDER / "tailor_cv.py"
EMAIL_SCRIPT = BASE_FOLDER / "email_workflow.py"

EVIDENCE_FILE = BASE_FOLDER / "student_research_evidence.json"
EVIDENCE_REVIEW_FILE = (
    BASE_FOLDER / "student_research_evidence_review.txt"
)

RECRUITMENT_REPORT_FILE = (
    BASE_FOLDER / "recruitment_search_report.txt"
)

LEADS_FILE = BASE_FOLDER / "recruitment_leads.csv"
CONFIRMED_FILE = BASE_FOLDER / "professor_candidates.csv"

VERIFIED_JSON = BASE_FOLDER / "verified_professor.json"
VERIFIED_TEXT = BASE_FOLDER / "verified_professor.txt"

CV_MANIFEST = (
    BASE_FOLDER
    / "tailored_cvs"
    / "latest_tailored_cv_manifest.json"
)

EMAIL_DRAFT_FILE = BASE_FOLDER / "email_draft.txt"
EMAIL_DRAFT_JSON = BASE_FOLDER / "email_draft.json"
TRACKER_FILE = BASE_FOLDER / "application_tracker.csv"
LOGO_FILE = BASE_FOLDER / "app_logo.png"

BACKGROUND = "#F4F7FB"
HEADER = "#163A5F"
PRIMARY = "#2F6FED"
PRIMARY_ACTIVE = "#2459BE"
ACCENT = "#1F7A8C"
ACCENT_ACTIVE = "#185F6D"
SUCCESS = "#2E7D32"
WARNING = "#B45309"
TEXT = "#1F2937"
MUTED = "#64748B"
CARD = "#FFFFFF"
BORDER = "#D8E2EC"
DISABLED_TEXT = "#94A3B8"

NEW_CANDIDATE_FIELDS = {
    "candidate_id",
    "name",
    "institution",
    "country",
    "recruitment_status",
    "recruitment_url",
    "recruitment_quote",
    "opportunity_url",
    "opportunity_quote",
    "official_profile_url",
}


def console_python():
    executable = Path(sys.executable)

    if executable.name.lower() == "pythonw.exe":
        python_exe = executable.with_name("python.exe")

        if python_exe.exists():
            return str(python_exe)

    return str(executable)


def load_json(path):
    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )

    except (
        OSError,
        json.JSONDecodeError,
    ):
        return None


def open_file(path, description):
    if not path.exists():
        messagebox.showwarning(
            "File not available",
            f"{description} has not been created yet."
            f"\n\n{path.name}",
        )
        return

    try:
        os.startfile(str(path))

        status_text.set(
            f"Opened {description}."
        )

    except OSError as error:
        messagebox.showerror(
            "Could not open file",
            f"Windows could not open "
            f"{description}.\n\n{error}",
        )


def run_script(path, description):
    if not path.exists():
        messagebox.showerror(
            "Script not found",
            f"{description} was not found."
            f"\n\n{path}",
        )
        return

    try:
        subprocess.Popen(
            [
                console_python(),
                str(path),
            ],
            cwd=str(BASE_FOLDER),
            creationflags=getattr(
                subprocess,
                "CREATE_NEW_CONSOLE",
                0,
            ),
        )

        status_text.set(
            f"{description} started "
            "in a terminal window."
        )

        messagebox.showinfo(
            description,
            "A terminal window has opened.\n\n"
            "Follow its instructions and keep it "
            "open until it finishes. Then return "
            "here and click Refresh Status.",
        )

    except Exception as error:
        messagebox.showerror(
            "Could not start process",
            f"{description} could not be "
            f"started.\n\n{error}",
        )


def approved_evidence():
    if not EVIDENCE_FILE.exists():
        return False

    record = load_json(
        EVIDENCE_FILE
    )

    return bool(
        record
        and record.get(
            "approved_by_user"
        ) is True
    )


def count_confirmed_candidates():
    if not CONFIRMED_FILE.exists():
        return 0, False

    try:
        with CONFIRMED_FILE.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file)

            fields = set(
                reader.fieldnames
                or []
            )

            if not NEW_CANDIDATE_FIELDS.issubset(
                fields
            ):
                return 0, False

            count = 0

            for row in reader:
                if (
                    row.get(
                        "recruitment_status"
                    )
                    != "CONFIRMED_2027_EVIDENCE"
                ):
                    continue

                required_values = (
                    "candidate_id",
                    "name",
                    "recruitment_url",
                    "recruitment_quote",
                    "opportunity_url",
                    "opportunity_quote",
                    "official_profile_url",
                )

                if not all(
                    str(
                        row.get(
                            field,
                            "",
                        )
                    ).strip()
                    for field in required_values
                ):
                    continue

                count += 1

            return count, True

    except (
        OSError,
        csv.Error,
    ):
        return 0, False


def approved_verification():
    if not VERIFIED_JSON.exists():
        return None

    record = load_json(
        VERIFIED_JSON
    )

    if not record:
        return None

    if record.get(
        "schema_version",
        0,
    ) < 3:
        return None

    if record.get(
        "ready_for_contact"
    ) != "YES":
        return None

    if record.get(
        "recruitment_reverified"
    ) is not True:
        return None

    if record.get(
        "research_fit_passed"
    ) is not True:
        return None

    if not record.get(
        "verified_publications"
    ):
        return None

    if not str(
        record.get(
            "candidate_id",
            "",
        )
    ).strip():
        return None

    if not str(
        record.get(
            "name",
            "",
        )
    ).strip():
        return None

    return record


def current_tailored_cv(
    verification,
):
    if (
        not verification
        or not CV_MANIFEST.exists()
    ):
        return None

    manifest = load_json(
        CV_MANIFEST
    )

    if (
        not manifest
        or manifest.get(
            "schema_version",
            0,
        ) < 1
    ):
        return None

    if manifest.get(
        "master_cv_unchanged"
    ) is not True:
        return None

    manifest_candidate = str(
        manifest.get(
            "candidate_id",
            "",
        )
    ).casefold()

    verified_candidate = str(
        verification.get(
            "candidate_id",
            "",
        )
    ).casefold()

    if (
        manifest_candidate
        != verified_candidate
    ):
        return None

    manifest_professor = str(
        manifest.get(
            "professor_name",
            "",
        )
    ).casefold()

    verified_professor = str(
        verification.get(
            "name",
            "",
        )
    ).casefold()

    if (
        manifest_professor
        != verified_professor
    ):
        return None

    relative = Path(
        str(
            manifest.get(
                "output_file",
                "",
            )
        )
    )

    if (
        relative.is_absolute()
        or ".." in relative.parts
    ):
        return None

    path = (
        BASE_FOLDER / relative
    ).resolve()

    tailored_folder = (
        BASE_FOLDER
        / "tailored_cvs"
    ).resolve()

    if (
        tailored_folder
        not in path.parents
        or not path.exists()
    ):
        return None

    return path


def current_email_draft(
    verification,
    cv_path,
):
    if (
        not verification
        or not cv_path
        or not EMAIL_DRAFT_FILE.exists()
        or not EMAIL_DRAFT_JSON.exists()
    ):
        return False

    record = load_json(
        EMAIL_DRAFT_JSON
    )

    if (
        not record
        or record.get(
            "schema_version",
            0,
        ) < 1
    ):
        return False

    draft_candidate = str(
        record.get(
            "candidate_id",
            "",
        )
    ).casefold()

    verified_candidate = str(
        verification.get(
            "candidate_id",
            "",
        )
    ).casefold()

    if (
        draft_candidate
        != verified_candidate
    ):
        return False

    draft_professor = str(
        record.get(
            "professor_name",
            "",
        )
    ).casefold()

    verified_professor = str(
        verification.get(
            "name",
            "",
        )
    ).casefold()

    if (
        draft_professor
        != verified_professor
    ):
        return False

    try:
        saved_value = Path(
            str(
                record.get(
                    "cv_file",
                    "",
                )
            )
        )

        if saved_value.is_absolute():
            saved_cv = saved_value.resolve()
        else:
            saved_cv = (
                BASE_FOLDER
                / saved_value
            ).resolve()

    except (
        OSError,
        TypeError,
    ):
        return False

    return (
        saved_cv
        == cv_path.resolve()
    )


def set_button_state(
    button,
    enabled,
):
    button.config(
        state=(
            "normal"
            if enabled
            else "disabled"
        ),
        cursor=(
            "hand2"
            if enabled
            else "arrow"
        ),
    )


def refresh_status():
    evidence_ready = (
        approved_evidence()
    )

    (
        confirmed_count,
        new_format,
    ) = count_confirmed_candidates()

    verification = (
        approved_verification()
    )

    cv_path = current_tailored_cv(
        verification
    )

    email_ready = current_email_draft(
        verification,
        cv_path,
    )

    evidence_value.config(
        text=(
            "Approved"
            if evidence_ready
            else "Not imported or not approved"
        ),
        fg=(
            SUCCESS
            if evidence_ready
            else MUTED
        ),
    )

    if new_format:
        recruitment_text = (
            f"{confirmed_count} "
            "confirmed for 2027"
        )

        recruitment_color = (
            SUCCESS
            if confirmed_count
            else MUTED
        )

    elif CONFIRMED_FILE.exists():
        recruitment_text = (
            "Old or incomplete list "
            "— not accepted"
        )
        recruitment_color = WARNING

    else:
        recruitment_text = (
            "No current three-source check"
        )
        recruitment_color = MUTED

    recruitment_value.config(
        text=recruitment_text,
        fg=recruitment_color,
    )

    if verification:
        verification_text = (
            "Approved: "
            f"{verification.get('name', '')}"
        )
        verification_color = SUCCESS

    elif VERIFIED_JSON.exists():
        verification_text = (
            "Not approved for contact"
        )
        verification_color = WARNING

    elif VERIFIED_TEXT.exists():
        verification_text = (
            "Old report — not accepted"
        )
        verification_color = WARNING

    else:
        verification_text = (
            "No approved professor"
        )
        verification_color = MUTED

    verification_value.config(
        text=verification_text,
        fg=verification_color,
    )

    cv_value.config(
        text=(
            cv_path.name
            if cv_path
            else "No matching safe CV"
        ),
        fg=(
            SUCCESS
            if cv_path
            else MUTED
        ),
    )

    email_value.config(
        text=(
            "Matching draft ready"
            if email_ready
            else "No matching draft"
        ),
        fg=(
            SUCCESS
            if email_ready
            else MUTED
        ),
    )

    set_button_state(
        find_button,
        evidence_ready,
    )

    set_button_state(
        review_evidence_button,
        EVIDENCE_REVIEW_FILE.exists(),
    )

    set_button_state(
        review_report_button,
        RECRUITMENT_REPORT_FILE.exists(),
    )

    set_button_state(
        review_leads_button,
        LEADS_FILE.exists(),
    )

    set_button_state(
        review_candidates_button,
        new_format
        and confirmed_count > 0,
    )

    set_button_state(
        verify_button,
        evidence_ready
        and new_format
        and confirmed_count > 0,
    )

    set_button_state(
        review_verification_button,
        VERIFIED_TEXT.exists(),
    )

    set_button_state(
        tailor_button,
        verification is not None,
    )

    set_button_state(
        review_cv_button,
        cv_path is not None,
    )

    set_button_state(
        email_button,
        verification is not None
        and cv_path is not None,
    )

    set_button_state(
        review_email_button,
        email_ready,
    )

    status_text.set(
        "Application status refreshed."
    )


def import_evidence():
    run_script(
        IMPORT_SCRIPT,
        "Research evidence import",
    )


def review_evidence():
    open_file(
        EVIDENCE_REVIEW_FILE,
        "research evidence review",
    )


def check_2027_opportunity():
    if not approved_evidence():
        messagebox.showwarning(
            "Approved evidence required",
            "Import and approve the student's "
            "publication and research summary "
            "before checking a professor.",
        )
        return

    answer = messagebox.askyesno(
        "Check official 2027 opportunity",
        "The terminal will ask for three "
        "official sources:\n\n"
        "1. A university intake, admissions, "
        "or scholarship page that explicitly "
        "mentions 2027\n"
        "2. A professor-specific PhD project "
        "or opportunity page\n"
        "3. The professor's current official "
        "profile\n\n"
        "The pages will be checked directly. "
        "A publication page is not proof of "
        "recruitment. No AI quota is used."
        "\n\nContinue?",
    )

    if answer:
        run_script(
            FIND_SCRIPT,
            "Official 2027 opportunity check",
        )


def review_recruitment_report():
    open_file(
        RECRUITMENT_REPORT_FILE,
        "2027 evidence report",
    )


def review_all_leads():
    open_file(
        LEADS_FILE,
        "all checked opportunity records",
    )


def review_confirmed_candidates():
    (
        count,
        new_format,
    ) = count_confirmed_candidates()

    if not new_format:
        messagebox.showwarning(
            "New evidence check required",
            "The existing "
            "professor_candidates.csv does not "
            "contain the new three-source "
            "evidence fields.\n\n"
            "Run Check an Official 2027 PhD "
            "Opportunity first.",
        )
        return

    if count == 0:
        messagebox.showinfo(
            "No confirmed candidates",
            "No professor passed every strict "
            "2027 evidence check.",
        )
        return

    open_file(
        CONFIRMED_FILE,
        "confirmed 2027 candidates",
    )


def verify_professor():
    (
        count,
        new_format,
    ) = count_confirmed_candidates()

    if (
        not new_format
        or count == 0
    ):
        messagebox.showwarning(
            "Confirmed candidate required",
            "First check an official 2027 "
            "opportunity and approve a candidate "
            "supported by all three required "
            "sources.",
        )
        return

    messagebox.showinfo(
        "Strict professor verification",
        "The terminal will show the confirmed "
        "candidates.\n\n"
        "Enter the candidate ID to recheck the "
        "2027 intake evidence, "
        "professor-specific opportunity, "
        "current profile, research fit, "
        "institutional email, and "
        "professor-authored publications.",
    )

    run_script(
        VERIFY_SCRIPT,
        "Strict professor verification",
    )


def review_verification():
    open_file(
        VERIFIED_TEXT,
        "strict professor verification report",
    )


def create_tailored_cv():
    verification = (
        approved_verification()
    )

    if not verification:
        messagebox.showwarning(
            "Approved professor required",
            "The strict verification report "
            "must say READY FOR CONTACT: YES "
            "before a CV can be created.",
        )
        return

    answer = messagebox.askyesno(
        "Create safe tailored CV",
        "Create a separate CV copy for "
        f"{verification.get('name', '')}?"
        "\n\nMaster_CV.docx will remain "
        "unchanged. The established profile "
        "structure must remain intact, and you "
        "must approve the proposed "
        "research-interest wording in the "
        "terminal.",
    )

    if answer:
        run_script(
            TAILOR_SCRIPT,
            "Safe tailored CV",
        )


def review_tailored_cv():
    verification = (
        approved_verification()
    )

    path = current_tailored_cv(
        verification
    )

    if not path:
        messagebox.showwarning(
            "Matching CV not found",
            "Create a new safe CV for the "
            "currently verified professor.",
        )
        return

    open_file(
        path,
        "current tailored CV",
    )


def create_email_draft():
    verification = (
        approved_verification()
    )

    cv_path = current_tailored_cv(
        verification
    )

    if (
        not verification
        or not cv_path
    ):
        messagebox.showwarning(
            "Verified professor and CV required",
            "Verify a professor and create the "
            "matching safe CV first.",
        )
        return

    answer = messagebox.askyesno(
        "Create human-reviewed email draft",
        "Prepare an email for "
        f"{verification.get('name', '')}?"
        "\n\nThe email must use only verified "
        "facts, one verified professor-authored "
        "publication, and the matching student "
        "evidence. You must review it before an "
        "unsent Gmail draft is created."
        "\n\nThe app will not send the email.",
    )

    if answer:
        run_script(
            EMAIL_SCRIPT,
            "Human-reviewed email draft",
        )


def review_email_draft():
    open_file(
        EMAIL_DRAFT_FILE,
        "saved email draft",
    )


def open_tracker():
    open_file(
        TRACKER_FILE,
        "application tracker",
    )


def add_section(
    parent,
    text,
):
    tk.Label(
        parent,
        text=text,
        bg=BACKGROUND,
        fg=TEXT,
        font=(
            "Segoe UI",
            12,
            "bold",
        ),
    ).pack(
        anchor="w",
        pady=(18, 4),
    )


def add_button(
    parent,
    text,
    command,
    color=PRIMARY,
):
    active = (
        PRIMARY_ACTIVE
        if color == PRIMARY
        else ACCENT_ACTIVE
    )

    button = tk.Button(
        parent,
        text=text,
        command=command,
        bg=color,
        fg="white",
        activebackground=active,
        activeforeground="white",
        disabledforeground=DISABLED_TEXT,
        relief="flat",
        bd=0,
        font=(
            "Segoe UI",
            10,
            "bold",
        ),
        cursor="hand2",
        padx=18,
        pady=11,
        anchor="w",
    )

    button.pack(
        fill="x",
        pady=5,
    )

    return button


root = tk.Tk()

root.title(
    "Research Application Assistant"
)

root.geometry(
    "940x900"
)

root.minsize(
    760,
    720,
)

root.configure(
    bg=BACKGROUND
)

root.option_add(
    "*Font",
    (
        "Segoe UI",
        10,
    ),
)

header_frame = tk.Frame(
    root,
    bg=HEADER,
    height=150,
)

header_frame.pack(
    fill="x"
)

header_frame.pack_propagate(
    False
)

header_content = tk.Frame(
    header_frame,
    bg=HEADER,
)

header_content.pack(
    fill="both",
    expand=True,
    padx=34,
    pady=23,
)

logo_image = None

if LOGO_FILE.exists():
    try:
        logo_image = tk.PhotoImage(
            file=str(LOGO_FILE)
        )

        width = max(
            logo_image.width(),
            1,
        )

        if width > 80:
            factor = max(
                1,
                width // 80,
            )

            logo_image = (
                logo_image.subsample(
                    factor,
                    factor,
                )
            )

        logo_label = tk.Label(
            header_content,
            image=logo_image,
            bg=HEADER,
        )

    except tk.TclError:
        logo_image = None

if logo_image is None:
    logo_label = tk.Label(
        header_content,
        text="SA",
        bg=ACCENT,
        fg="white",
        font=(
            "Segoe UI",
            18,
            "bold",
        ),
        width=4,
        height=2,
    )

logo_label.pack(
    side="left",
    padx=(0, 18),
)

title_frame = tk.Frame(
    header_content,
    bg=HEADER,
)

title_frame.pack(
    side="left",
    fill="both",
    expand=True,
)

tk.Label(
    title_frame,
    text=(
        "Research Application Assistant"
    ),
    bg=HEADER,
    fg="white",
    font=(
        "Segoe UI",
        22,
        "bold",
    ),
).pack(
    anchor="w"
)

tk.Label(
    title_frame,
    text=(
        "Evidence-first verification and "
        "PhD application preparation"
    ),
    bg=HEADER,
    fg="#D9E8F5",
    font=(
        "Segoe UI",
        11,
    ),
).pack(
    anchor="w",
    pady=(5, 0),
)

outer = tk.Frame(
    root,
    bg=BACKGROUND,
)

outer.pack(
    fill="both",
    expand=True,
)

canvas = tk.Canvas(
    outer,
    bg=BACKGROUND,
    highlightthickness=0,
)

scrollbar = tk.Scrollbar(
    outer,
    orient="vertical",
    command=canvas.yview,
)

content = tk.Frame(
    canvas,
    bg=BACKGROUND,
)

content.bind(
    "<Configure>",
    lambda event: canvas.configure(
        scrollregion=canvas.bbox("all")
    ),
)

canvas_window = canvas.create_window(
    (0, 0),
    window=content,
    anchor="nw",
)

canvas.bind(
    "<Configure>",
    lambda event: canvas.itemconfigure(
        canvas_window,
        width=event.width,
    ),
)

canvas.configure(
    yscrollcommand=scrollbar.set
)

canvas.pack(
    side="left",
    fill="both",
    expand=True,
)

scrollbar.pack(
    side="right",
    fill="y",
)


def scroll_content(event):
    canvas.yview_scroll(
        int(
            -1
            * (
                event.delta
                / 120
            )
        ),
        "units",
    )


canvas.bind_all(
    "<MouseWheel>",
    scroll_content,
)

main = tk.Frame(
    content,
    bg=BACKGROUND,
)

main.pack(
    fill="both",
    expand=True,
    padx=34,
    pady=24,
)

status_card = tk.Frame(
    main,
    bg=CARD,
    highlightbackground=BORDER,
    highlightthickness=1,
)

status_card.pack(
    fill="x",
    pady=(0, 18),
)

tk.Label(
    status_card,
    text="Current evidence status",
    bg=CARD,
    fg=TEXT,
    font=(
        "Segoe UI",
        12,
        "bold",
    ),
).grid(
    row=0,
    column=0,
    columnspan=2,
    sticky="w",
    padx=20,
    pady=(16, 10),
)

status_rows = (
    (
        "Student research evidence:",
        1,
    ),
    (
        "Professor 2027 evidence:",
        2,
    ),
    (
        "Strict professor verification:",
        3,
    ),
    (
        "Matching safe CV:",
        4,
    ),
    (
        "Matching email draft:",
        5,
    ),
)

for (
    label_text,
    row_number,
) in status_rows:
    tk.Label(
        status_card,
        text=label_text,
        bg=CARD,
        fg=MUTED,
    ).grid(
        row=row_number,
        column=0,
        sticky="w",
        padx=20,
        pady=4,
    )


def status_value_label():
    return tk.Label(
        status_card,
        text="Checking...",
        bg=CARD,
        fg=MUTED,
        font=(
            "Segoe UI",
            10,
            "bold",
        ),
    )


evidence_value = (
    status_value_label()
)

recruitment_value = (
    status_value_label()
)

verification_value = (
    status_value_label()
)

cv_value = (
    status_value_label()
)

email_value = (
    status_value_label()
)

for (
    widget,
    row_number,
) in (
    (
        evidence_value,
        1,
    ),
    (
        recruitment_value,
        2,
    ),
    (
        verification_value,
        3,
    ),
    (
        cv_value,
        4,
    ),
    (
        email_value,
        5,
    ),
):
    widget.grid(
        row=row_number,
        column=1,
        sticky="w",
        padx=10,
        pady=4,
    )

refresh_button = tk.Button(
    status_card,
    text="Refresh Status",
    command=refresh_status,
    bg=CARD,
    fg=PRIMARY,
    activebackground="#EAF1FF",
    activeforeground=PRIMARY_ACTIVE,
    relief="flat",
    font=(
        "Segoe UI",
        9,
        "bold",
    ),
    cursor="hand2",
)

refresh_button.grid(
    row=0,
    column=2,
    rowspan=6,
    padx=20,
)

status_card.columnconfigure(
    1,
    weight=1,
)

status_text = tk.StringVar(
    value="The application is ready."
)

tk.Label(
    main,
    textvariable=status_text,
    bg=BACKGROUND,
    fg=MUTED,
    font=(
        "Segoe UI",
        9,
    ),
).pack(
    anchor="w",
    pady=(0, 5),
)

add_section(
    main,
    "1  Student evidence",
)

import_button = add_button(
    main,
    "Import or Update Research Documents",
    import_evidence,
)

review_evidence_button = add_button(
    main,
    "Review Extracted Research Evidence",
    review_evidence,
    ACCENT,
)

add_section(
    main,
    "2  Official 2027 opportunity evidence",
)

find_button = add_button(
    main,
    "Check an Official 2027 PhD Opportunity",
    check_2027_opportunity,
)

review_report_button = add_button(
    main,
    "Review 2027 Evidence Report",
    review_recruitment_report,
    ACCENT,
)

review_leads_button = add_button(
    main,
    "Review All Checked Opportunity Records",
    review_all_leads,
    ACCENT,
)

review_candidates_button = add_button(
    main,
    "Review Confirmed 2027 Candidates",
    review_confirmed_candidates,
    ACCENT,
)

add_section(
    main,
    "3  Strict professor verification",
)

verify_button = add_button(
    main,
    "Verify Research Fit and Original Publications",
    verify_professor,
)

review_verification_button = add_button(
    main,
    "Review Strict Verification Report",
    review_verification,
    ACCENT,
)

add_section(
    main,
    "4  Professor-specific application preparation",
)

tailor_button = add_button(
    main,
    "Create Safe Tailored CV",
    create_tailored_cv,
)

review_cv_button = add_button(
    main,
    "Review Current Tailored CV",
    review_tailored_cv,
    ACCENT,
)

email_button = add_button(
    main,
    "Create Human-Reviewed Gmail Draft",
    create_email_draft,
)

review_email_button = add_button(
    main,
    "Review Saved Email Draft",
    review_email_draft,
    ACCENT,
)

tk.Label(
    main,
    text=(
        "Buttons unlock only when the previous "
        "evidence stage passes. The app never "
        "sends an email automatically."
    ),
    bg=BACKGROUND,
    fg=MUTED,
    wraplength=820,
    justify="left",
    font=(
        "Segoe UI",
        9,
    ),
).pack(
    anchor="w",
    pady=(8, 12),
)

add_section(
    main,
    "5  Application records",
)

tracker_button = add_button(
    main,
    "Open Application Tracker",
    open_tracker,
    ACCENT,
)

close_button = tk.Button(
    main,
    text="Close Application",
    command=root.destroy,
    bg=HEADER,
    fg="white",
    activebackground="#0F2A45",
    activeforeground="white",
    relief="flat",
    bd=0,
    font=(
        "Segoe UI",
        10,
        "bold",
    ),
    cursor="hand2",
    padx=20,
    pady=11,
)

close_button.pack(
    fill="x",
    pady=(14, 30),
)

refresh_status()

root.mainloop()
