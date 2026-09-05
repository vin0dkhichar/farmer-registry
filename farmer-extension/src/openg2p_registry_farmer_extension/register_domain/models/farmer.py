from openg2p_registry_core.models.g2p_intake_form import G2PIntakeForm
from sqlalchemy import Boolean, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column
from openg2p_registry_core.models import (
    G2PRegister, G2PRegisterHistory, G2PGeo, G2PPerson,
    G2PPersonHistory, G2PGeoHistory
)
from ..services import G2PRegisterDomainServiceFarmer
from .enums import DisabilityTypeEnum, DisabilitySeverityEnum, SourceOfIncomeEnum, EducationalLevelEnum

class G2PFarmer:

    estimated_age: Mapped[int] = mapped_column(Integer, nullable=True)
    has_personal_phone: Mapped[bool] = mapped_column(Boolean, nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=True)
    disability_type: Mapped[DisabilityTypeEnum] = mapped_column(String, nullable=True)       # DisabilityTypeEnum
    disability_severity: Mapped[DisabilitySeverityEnum] = mapped_column(String, nullable=True)   # DisabilitySeverityEnum
    source_of_income: Mapped[SourceOfIncomeEnum] = mapped_column(String, nullable=True)      # MDS SOURCE_OF_INCOME; use source_of_income_other when SOI_OTHERS
    source_of_income_other: Mapped[str] = mapped_column(String, nullable=True)
    language_spoken: Mapped[str] = mapped_column(String, nullable=True)       # Attribute lookup (Excel: ISO-639-2 searchable dropdown)
    education_level: Mapped[EducationalLevelEnum] = mapped_column(String, nullable=True)       # EducationalLevelEnum
    national_id_masked: Mapped[str] = mapped_column(String, nullable=True)

# All Register classes should have the prefix G2PRegister
class G2PRegisterFarmer(G2PRegister, G2PPerson, G2PGeo, G2PFarmer):
    __tablename__ = "g2p_register_farmers"

    def get_record_name_fields(self) -> str:
        """Return farmer fields used to build record_name."""
        return G2PRegisterDomainServiceFarmer().construct_record_name(self.to_dict())

    def get_search_text_fields(self) -> str:
        """Return farmer fields used to build search_text."""
        return G2PRegisterDomainServiceFarmer().construct_search_text(self.to_dict())

# All Register History classes should have the prefix G2PRegisterHistory
class G2PRegisterHistoryFarmer(G2PRegisterHistory, G2PPersonHistory, G2PGeoHistory, G2PFarmer):
    __tablename__ = "g2p_register_history_farmers"

# All Intake Form classes should have the prefix G2PIntakeForm
class G2PIntakeFormFarmer(G2PIntakeForm, G2PRegister, G2PPerson, G2PGeo, G2PFarmer):
    __tablename__ = "g2p_intake_form_farmers"

    def get_record_name_fields(self) -> str:
        """Return farmer fields used to build record_name."""
        return G2PRegisterDomainServiceFarmer().construct_record_name(self.to_dict())

    def get_search_text_fields(self) -> str:
        """Return farmer fields used to build search_text."""
        return G2PRegisterDomainServiceFarmer().construct_search_text(self.to_dict())
