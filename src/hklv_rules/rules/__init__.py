from ._shared import Assignment
from .academic import check_academic
from .bank import check_bank
from .birth import check_birth_certificates
from .death import check_death_certificates
from .employment import check_employment
from .financial_chain import check_financial_chain
from .frc import check_frc
from .language import check_language_tests
from .nid import check_nids
from .nid_assignment import NidAssignment, assign_nids
from .passport import check_passport
from .required import check_required_documents
from .stamps import check_stamp_dates
from .tax import check_income_tax
from .tin import check_tin
from .trade import check_trade_licenses

__all__ = [
    "Assignment",
    "NidAssignment",
    "assign_nids",
    "check_academic",
    "check_bank",
    "check_birth_certificates",
    "check_death_certificates",
    "check_employment",
    "check_financial_chain",
    "check_frc",
    "check_income_tax",
    "check_language_tests",
    "check_nids",
    "check_passport",
    "check_required_documents",
    "check_stamp_dates",
    "check_tin",
    "check_trade_licenses",
]
