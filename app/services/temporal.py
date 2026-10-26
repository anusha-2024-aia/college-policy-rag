"""Temporal intent detection and time-travel query resolution."""

import logging
import re
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

MONTH_MAP = {
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
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

MONTH_REGEX_STR = "|".join(MONTH_MAP.keys())

# Pattern 1: "before July 2025", "prior to 2025"
BEFORE_MONTH_YEAR_REGEX = re.compile(
    rf"\b(?:before|prior to)\s+({MONTH_REGEX_STR})\s+(\d{{4}})\b",
    re.IGNORECASE,
)
BEFORE_YEAR_REGEX = re.compile(
    r"\b(?:before|prior to)\s+(\d{4})\b",
    re.IGNORECASE,
)

# Pattern 2: "in January 2025", "during July 2024", "as of March 2025"
MONTH_YEAR_REGEX = re.compile(
    rf"\b(?:in|during|as of|for)?\s*({MONTH_REGEX_STR})\s+(\d{{4}})\b",
    re.IGNORECASE,
)

# Pattern 3: "in 2024", "during 2023", "for 2024"
YEAR_REGEX = re.compile(
    r"\b(?:in|during|for|as of)\s+(\d{4})\b",
    re.IGNORECASE,
)

# Pattern 4: Historical / previous rule phrases
HISTORICAL_PHRASES = [
    "used to be",
    "old rule",
    "former rule",
    "previously",
    "historically",
    "prior rule",
    "earlier rule",
    "original rule",
    "past rule",
    "replaced rule",
]


def detect_temporal_intent(
    query: str, request_as_of: Optional[str] = None
) -> tuple[bool, date, Optional[str]]:
    """Detect whether query has temporal or historical intent and return corresponding target date.

    Args:
        query: User question string.
        request_as_of: Explicit ISO date string (YYYY-MM-DD) if passed in request.

    Returns:
        Tuple of (is_temporal: bool, target_as_of_date: date, label: Optional[str]).
    """
    if request_as_of:
        try:
            target_d = datetime.strptime(request_as_of.strip(), "%Y-%m-%d").date()
            return True, target_d, str(target_d)
        except ValueError:
            logger.warning("Invalid as_of date format '%s', falling back to query parsing", request_as_of)

    q_lower = query.lower()

    # 1. "before/prior to <Month> <Year>", e.g. "before July 2025" -> 2025-06-30
    m = BEFORE_MONTH_YEAR_REGEX.search(q_lower)
    if m:
        month_name = m.group(1).lower()
        month_num = MONTH_MAP[month_name]
        year_num = int(m.group(2))
        # End of previous month or start of target month
        if month_num == 1:
            target_d = date(year_num - 1, 12, 31)
        else:
            target_d = date(year_num, month_num - 1, 28)
        return True, target_d, f"before {month_name.title()} {year_num}"

    # 2. "before <Year>", e.g. "before 2025" -> 2024-12-31
    m = BEFORE_YEAR_REGEX.search(q_lower)
    if m:
        year_num = int(m.group(1))
        return True, date(year_num - 1, 12, 31), f"before {year_num}"

    # 3. "<Month> <Year>", e.g. "in January 2025" -> 2025-01-15
    m = MONTH_YEAR_REGEX.search(q_lower)
    if m:
        month_name = m.group(1).lower()
        month_num = MONTH_MAP[month_name]
        year_num = int(m.group(2))
        return True, date(year_num, month_num, 15), f"{month_name.title()} {year_num}"

    # 4. "in <Year>", e.g. "in 2024" -> 2024-07-01
    m = YEAR_REGEX.search(q_lower)
    if m:
        year_num = int(m.group(1))
        # Default mid-year for an academic year reference
        return True, date(year_num, 7, 1), str(year_num)

    # 5. Semantic historical phrases ("used to be", "old rule", etc.)
    if any(phrase in q_lower for phrase in HISTORICAL_PHRASES):
        # Default historical timestamp prior to 2025 revisions
        return True, date(2024, 6, 1), "historical rule"

    # Default: non-temporal query evaluates as of today
    return False, date.today(), None

