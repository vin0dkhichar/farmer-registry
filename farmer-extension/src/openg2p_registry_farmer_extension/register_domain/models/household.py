from openg2p_registry_core.models.g2p_intake_form import G2PIntakeForm
from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from openg2p_registry_core.models import G2PRegister, G2PRegisterHistory, G2PGeo, G2PGeoHistory
from ..services import G2PRegisterDomainServiceHousehold


class G2PHousehold:

    household_head: Mapped[str] = mapped_column(String, nullable=True)
    size_of_group: Mapped[int] = mapped_column(Integer, nullable=True)
    number_of_children: Mapped[int] = mapped_column(Integer, nullable=True)
    number_of_elderly_members: Mapped[int] = mapped_column(Integer, nullable=True)
    number_of_female_members: Mapped[int] = mapped_column(Integer, nullable=True)
    number_of_male_members: Mapped[int] = mapped_column(Integer, nullable=True)
    other_land_owner: Mapped[bool] = mapped_column(Boolean, nullable=True)


# All Register classes should have the prefix G2PRegister
class G2PRegisterHousehold(G2PRegister, G2PGeo, G2PHousehold):
    __tablename__ = "g2p_register_households"

    def get_search_text_fields(self) -> str:
        """Return household fields used to build search_text."""
        return G2PRegisterDomainServiceHousehold().construct_search_text(self.to_dict())

    def get_record_name_fields(self) -> str:
        """Return household record_name from domain service implementation."""
        return G2PRegisterDomainServiceHousehold().construct_record_name(self.to_dict())


# All Register History classes should have the prefix G2PRegisterHistory
class G2PRegisterHistoryHousehold(G2PRegisterHistory, G2PGeoHistory, G2PHousehold):
    __tablename__ = "g2p_register_history_households"

# All Intake Form classes should have the prefix G2PIntakeForm
class G2PIntakeFormHousehold(G2PIntakeForm, G2PRegister, G2PGeo, G2PHousehold):
    __tablename__ = "g2p_intake_form_households"

    def get_search_text_fields(self) -> str:
        """Return household fields used to build search_text."""
        return G2PRegisterDomainServiceHousehold().construct_search_text(self.to_dict())

    def get_record_name_fields(self) -> str:
        """Return household record_name from domain service implementation."""
        return G2PRegisterDomainServiceHousehold().construct_record_name(self.to_dict())
