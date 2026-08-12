"""
KISAUNI PRIMARY SCHOOL - RESULT MANAGEMENT SYSTEM
Configuration & constant data used across the app.
"""

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "kisauni-secret-key-change-me")
    DATABASE = os.path.join(BASE_DIR, "kisauni.db")
    REPORTS_DIR = os.path.join(BASE_DIR, "reports", "generated")
    UPLOAD_DIR = os.path.join(BASE_DIR, "static", "images")

# ---------------------------------------------------------------------------
# SCHOOL / GRADING SETTINGS (defaults - editable later from Settings page,
# stored in the `settings` table; these are just fallback values)
# ---------------------------------------------------------------------------
DEFAULT_SCHOOL_NAME = "KISAUNI PRIMARY SCHOOL"
DEFAULT_ACADEMIC_YEAR = "2026"

# Grading system (as provided by the school):
#   A = 81-100   B = 61-80   C = 41-60   D = 21-40   E = 0-20
GRADE_BANDS = [
    ("A", 81, 100, "#198754"),   # green
    ("B", 61, 80,  "#0d6efd"),   # blue
    ("C", 41, 60,  "#ffc107"),   # yellow/amber
    ("D", 21, 40,  "#fd7e14"),   # orange
    ("E", 0,  20,  "#dc3545"),   # red
]

def grade_for_score(score):
    """Return (grade_letter, colour_hex) for a given numeric score/average."""
    if score is None:
        return ("-", "#6c757d")
    try:
        score = float(score)
    except (TypeError, ValueError):
        return ("-", "#6c757d")
    for letter, low, high, colour in GRADE_BANDS:
        if low <= score <= high:
            return (letter, colour)
    if score > 100:
        return ("A", "#198754")
    return ("E", "#dc3545")

# ---------------------------------------------------------------------------
# CLASSES: Standard One - Standard Seven (KG1/KG2 not included)
# ---------------------------------------------------------------------------
CLASS_NAMES = [
    "Standard One", "Standard Two", "Standard Three", "Standard Four",
    "Standard Five", "Standard Six", "Standard Seven",
]

# ---------------------------------------------------------------------------
# SUBJECTS per class band
#   Standard 1-3 (lower)  : SUMI, Kiswahili, English, Mazingira, Dini, Hisabati
#   Standard 4-7 (upper)  : Kiswahili, English, Hisabati, Dini, Kiarabu,
#                            Jamii (Social Studies), Sayansi na Teknolojia, SUMI
# ---------------------------------------------------------------------------
LOWER_CLASS_SUBJECTS = ["SUMI", "Kiswahili", "English", "Mazingira", "Dini", "Hisabati"]
UPPER_CLASS_SUBJECTS = [
    "Kiswahili", "English", "Hisabati", "Dini", "Kiarabu",
    "Jamii", "Sayansi na Teknolojia", "SUMI",
]
LOWER_CLASSES = {"Standard One", "Standard Two", "Standard Three"}

# ---------------------------------------------------------------------------
# EXAMINATION TYPES
# ---------------------------------------------------------------------------
EXAM_TYPES = ["MID TERM", "FIRST TERM", "SECOND MID TERM", "SECOND TERM"]

# ---------------------------------------------------------------------------
# ROLES
# ---------------------------------------------------------------------------
ROLE_HEADMASTER = "headmaster"
ROLE_CLASS_TEACHER = "class_teacher"

# ---------------------------------------------------------------------------
# Simple Tanzanian/Swahili/Islamic first-name lookup used to auto-detect
# gender. This is a best-effort heuristic only - the UI always shows a
# "Confirm Gender" control so staff can correct it.
# ---------------------------------------------------------------------------
MALE_NAMES = {
    "mohamed", "muhammad", "mohammed", "ally", "ali", "hassan", "hussein",
    "husein", "omar", "omary", "juma", "jumanne", "issa", "iddi", "idd",
    "rashid", "rashidi", "salum", "salim", "khamis", "khalifa", "abdallah",
    "abdala", "abdulla", "abdullah", "yusuph", "yusuf", "ibrahim", "ismail",
    "ismaili", "said", "seif", "suleiman", "sulemani", "hamisi", "hamis",
    "athuman", "athumani", "shabani", "shaban", "ramadhani", "ramadhan",
    "bakari", "bakar", "hamad", "hamadi", "kassim", "kasim", "amiri", "amir",
    "musa", "moses", "daudi", "david", "yohana", "john", "johnson", "peter",
    "petro", "paulo", "paul", "joseph", "yosefu", "emmanuel", "emanueli",
    "frank", "francis", "fransisko", "michael", "mikael", "jackson", "james",
    "jacob", "yakobo", "erick", "eric", "godfrey", "godwin", "edward",
    "eduard", "richard", "richard", "anthony", "antony", "baraka", "boniface",
    "bonifasi", "charles", "chalo", "clement", "dennis", "denis", "dickson",
    "elias", "eliya", "evans", "fred", "fredrick", "gabriel", "gasper",
    "george", "goodluck", "hamza", "hussen", "innocent", "isaya", "jaffar",
    "jafari", "kelvin", "kevin", "khalfan", "leonard", "makame", "maulid",
    "mbaraka", "mussa", "nasoro", "nassoro", "nuru" ,"rajabu", "rajab",
    "salehe", "saleh", "selemani", "sharif", "sharrif", "vincent", "wilbert",
    "zubery", "zuberi", "abel", "adam", "amani", "andrew", "andrea", "aziz",
}

FEMALE_NAMES = {
    "fatuma", "fatma", "aisha", "aysha", "amina", "mwanaisha", "mwajuma",
    "zainab", "zainabu", "mariam", "maria", "mary", "halima", "hadija",
    "hadijah", "khadija", "rehema", "rukia", "rukiya", "salma", "saumu",
    "asha", "asya", "bahati", "bibi", "farida", "hawa", "hawa", "husna",
    "jamila", "jamela", "juma", "kulthum", "latifa", "mwanahawa",
    "mwanahamisi", "mwanaidi", "nasra", "neema", "pili", "rahma", "raya",
    "sabra", "salama", "shakira", "sofia", "subira", "tatu", "tunu",
    "upendo", "zaituni", "zulfa", "agnes", "agness", "alice", "anna",
    "anastazia", "beatrice", "beatrice", "catherine", "cecilia", "consolata",
    "dorcas", "dorothy", "edna", "elizabeth", "esther", "eunice", "faraja",
    "flora", "florence", "gladness", "glory", "grace", "happiness", "irene",
    "jane", "janeth", "jesca", "joyce", "judith", "juliana", "lightness",
    "lilian", "lucy", "magdalena", "margareth", "martha", "mary", "monica",
    "naomi", "paulina", "prisca", "rehema", "rose", "ruth", "sarah", "sara",
    "scholastica", "stella", "susan", "teresia", "veronica", "victoria",
    "winfrida", "yustina", "zawadi", "zena", "zuhura",
}

def detect_gender(full_name):
    """Best-effort auto detection of gender from the first name.
    Returns 'Male', 'Female' or None (unknown -> needs manual confirmation).
    """
    if not full_name:
        return None
    first = full_name.strip().split()[0].lower()
    first = first.replace(".", "")
    if first in MALE_NAMES:
        return "Male"
    if first in FEMALE_NAMES:
        return "Female"
    return None
