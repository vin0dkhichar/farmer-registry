from openg2p_registry_core.models.g2p_intake_form import G2PIntakeForm
from sqlalchemy import Integer, Numeric, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column
from openg2p_registry_core.models import (
    G2PRegister, G2PRegisterHistory, G2PGeo, G2PGeoShape,
    G2PGeoHistory, G2PGeoShapeHistory
)
from .enums import LandOwnershipTypeEnum, LandSizeUnitEnum, CurrentLandUseEnum, FarmingTypeEnum
from ..services import G2PRegisterDomainServiceLand

class G2PLand:

    land_ownership_type: Mapped[LandOwnershipTypeEnum] = mapped_column(String, nullable=True)   # LandOwnershipTypeEnum
    certificate_storage_id: Mapped[str] = mapped_column(Text, nullable=True)
    land_size: Mapped[float] = mapped_column(Numeric, nullable=True)
    unit: Mapped[LandSizeUnitEnum] = mapped_column(String, nullable=True)        # LandSizeUnitEnum
    soil_fertility: Mapped[str] = mapped_column(String, nullable=True)
    current_land_use: Mapped[CurrentLandUseEnum] = mapped_column(String, nullable=True)      # CurrentLandUseEnum
    farming_type: Mapped[FarmingTypeEnum] = mapped_column(String, nullable=True)          # FarmingTypeEnum
    year_of_acquisition: Mapped[int] = mapped_column(Integer, nullable=True)
    means_of_acquisition: Mapped[str] = mapped_column(String, nullable=True)  # Attribute lookup

# All Register classes should have the prefix G2PRegister
class G2PRegisterLand(G2PRegister, G2PGeo, G2PGeoShape, G2PLand):
    __tablename__ = "g2p_register_lands"

    def get_search_text_fields(self) -> str:
        """Return land fields used to build search_text."""
        return G2PRegisterDomainServiceLand().construct_search_text(self.to_dict())

    def get_record_name_fields(self) -> str:
        """Return land record_name from domain service implementation."""
        return G2PRegisterDomainServiceLand().construct_record_name(self.to_dict())

# All Register History classes should have the prefix G2PRegisterHistory
class G2PRegisterHistoryLand(G2PRegisterHistory, G2PGeoHistory, G2PGeoShapeHistory, G2PLand):
    __tablename__ = "g2p_register_history_lands"

# All Intake Form classes should have the prefix G2PIntakeForm
class G2PIntakeFormLand(G2PIntakeForm, G2PRegister, G2PGeo, G2PGeoShape, G2PLand):
    __tablename__ = "g2p_intake_form_lands"

    def get_search_text_fields(self) -> str:
        """Return land fields used to build search_text."""
        return G2PRegisterDomainServiceLand().construct_search_text(self.to_dict())

    def get_record_name_fields(self) -> str:
        """Return land record_name from domain service implementation."""
        return G2PRegisterDomainServiceLand().construct_record_name(self.to_dict())
