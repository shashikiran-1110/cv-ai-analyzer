"""Domain packs (ROADMAP §6.4): extra skills, aliases and licence gates for non-tech occupations.

Aliases are deliberately specific ("patient triage", not "triage", which also means bug triage) so packs don't add
false positives to tech postings. Each pack is merged into the skill taxonomy at import time."""

PACKS: dict[str, dict[str, list[str]]] = {
    "Healthcare": {
        "Nursing": ["nursing", "nurse", "registered nurse", "staff nurse", "rn license", "rn licensure"],
        "Medication Administration": ["medication administration", "administering medications", "administer medications"],
        "BLS/ACLS": ["bls", "acls", "basic life support", "advanced cardiac life support", "pals certification"],
        "Patient Assessment": ["patient assessment", "patient assessments", "clinical assessment", "vital signs"],
        "Triage": ["patient triage", "triage nurse", "emergency triage", "triage patients"],
        "Phlebotomy": ["phlebotomy", "venipuncture", "blood draws"],
        "Critical Care": ["icu", "intensive care", "critical care"],
        "Infection Control": ["infection control", "infection prevention"],
        "Care Planning": ["care plans", "care planning", "care plan"],
        "Medical Terminology": ["medical terminology"],
        "Medical Coding": ["medical coding", "icd-10", "cpt coding"],
    },
    "Finance & Accounting": {
        "Accounts Payable": ["accounts payable"], "Accounts Receivable": ["accounts receivable"],
        "Reconciliation": ["reconciliation", "reconciliations", "account reconciliation", "bank reconciliations"],
        "Payroll": ["re:payroll(?!\\s+(?:deductions?|giving|benefits?|schedule))", "payroll processing"], "Financial Reporting": ["financial reporting", "financial statements"],
        "Auditing": ["financial audit", "internal audit", "external audit", "audit engagements", "statutory audit"],
        "Tax": ["tax preparation", "tax returns", "corporate tax", "tax compliance", "vat returns"],
        "FP&A": ["fp&a", "financial planning and analysis", "variance analysis"],
        "Risk Management": ["risk management", "credit risk", "market risk", "risk assessment"],
        "Investment Analysis": ["investment analysis", "equity research", "valuation", "dcf"],
    },
    "Legal": {
        "Contract Drafting": ["contract drafting", "drafting contracts", "drafted contracts", "drafting of contracts", "contract negotiation", "commercial contracts"],
        "Litigation": ["litigation", "civil litigation", "commercial litigation"],
        "Legal Research": ["legal research", "westlaw", "lexisnexis"],
        "Due Diligence": ["due diligence"], "Corporate Law": ["corporate law", "m&a transactions", "mergers and acquisitions"],
        "Regulatory Affairs": ["regulatory affairs", "regulatory submissions"],
        "Intellectual Property": ["intellectual property", "patent prosecution", "trademark"],
    },
    "Skilled Trades": {
        "Electrical Installation": ["electrical installation", "electrical wiring", "wiring diagrams", "electrical systems"],
        "Plumbing": ["plumbing", "pipefitting", "pipe fitting"], "HVAC": ["hvac", "refrigeration systems"],
        "Welding": ["welding", "mig welding", "tig welding"], "Carpentry": ["carpentry", "joinery", "timber framing"],
        "Blueprint Reading": ["blueprint reading", "reading blueprints", "technical drawings", "schematics"],
        "Forklift Operation": ["forklift", "forklift operation", "reach truck"],
        "OSHA Safety": ["osha", "health and safety", "workplace safety", "cscs card"],
        "Preventive Maintenance": ["preventive maintenance", "preventative maintenance", "troubleshooting equipment"],
        "CNC Machining": ["cnc", "cnc machining", "machining"],
    },
    "Education": {
        "Lesson Planning": ["lesson planning", "lesson plans"], "Classroom Management": ["classroom management"],
        "Curriculum Development": ["curriculum development", "curriculum design", "instructional design"],
        "Special Education": ["special education", "iep", "ieps"],
        "Student Assessment": ["student assessment", "formative assessment", "marking and assessment"],
        "Tutoring": ["tutoring", "tutor"], "E-learning": ["e-learning", "elearning", "lms", "moodle", "canvas lms"],
    },
    "Sales & Retail": {
        "Cold Calling": ["cold calling", "cold calls", "outbound prospecting", "prospecting"],
        "Retail Operations": ["retail operations", "store operations", "visual merchandising", "merchandising"],
        "Inventory Management": ["inventory management", "stock control", "inventory control"],
        "POS Systems": ["pos systems", "point of sale", "cash handling"],
        "Key Account Management": ["key account management", "key accounts"],
        "Sales Forecasting": ["sales forecasting", "pipeline management"],
    },
}

# Licences/credentials that act as hard gates (ROADMAP §6.3). pattern → display name. Matched in postings;
# satisfied when the same pattern appears on the resume (or the user lists it in their profile).
LICENSES: dict[str, str] = {
    r"\b(?:rn|registered nurse)\s+(?:license|licence|licensure|registration)\b|\bactive\s+rn\b|\bnmc\s+(?:pin|registration)\b": "Registered Nurse licence",
    r"\blpn\b|\blicensed practical nurse\b": "LPN licence",
    r"\bcpa\b(?!\s+firm)|\bchartered accountant\b|\baca\b|\bacca\s+qualified\b": "CPA / chartered accountant",
    r"\badmitted to (?:the|practi[cs]e)|\bbar admission\b|\blicensed (?:attorney|to practi[cs]e law)\b|\bqualified solicitor\b": "Bar admission / practising certificate",
    r"\bcdl\b|\bcommercial driver'?s licen[cs]e\b|\bhgv licen[cs]e\b": "Commercial driver's licence (CDL/HGV)",
    r"\bprofessional engineer\b|\bpe licen[cs]e\b|\bchartered engineer\b": "Professional Engineer (PE/CEng)",
    r"\bteaching (?:licen[cs]e|certificat\w+|credential)\b|\bqts\b|\bqualified teacher status\b": "Teaching licence (QTS)",
    r"\bseries\s+(?:7|63|65|66)\b": "FINRA Series licence",
    r"\bjourneyman\b|\bmaster electrician\b|\blicensed electrician\b": "Electrician licence",
    r"\bcfa\s+charter\b|\bcfa charterholder\b": "CFA charter",
    r"\bcissp\b": "CISSP certification",
}
