"""Online verification against official Bangladeshi government sites (ACAD-01, TAX-04).

The rules engine never does I/O. This package fills in each document's `online` result
between extraction and the rules; the rules only interpret it.
"""

from .checks import (
    ACHALLAN_HOST,
    APOSTILLE_HOST,
    apostille_id,
    apply_online_checks,
    achallan_number,
    check_apostille,
    check_challan,
)

__all__ = [
    "ACHALLAN_HOST",
    "APOSTILLE_HOST",
    "achallan_number",
    "apostille_id",
    "apply_online_checks",
    "check_apostille",
    "check_challan",
]
