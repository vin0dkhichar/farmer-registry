from typing import Optional

from openg2p_registry_core.schemas import (
    G2PRegisterBaseSchema, G2PGeoSchema,
    G2PRegisterHistorySchema, G2PGeoHistorySchema,
    G2PIntakeFormSchemaBase
)


class G2PSchemaHousehold:

    household_head: Optional[str] = None
    size_of_group: Optional[int] = None
    number_of_children: Optional[int] = None
    number_of_elderly_members: Optional[int] = None
    number_of_female_members: Optional[int] = None
    number_of_male_members: Optional[int] = None
    other_land_owner: Optional[bool] = None


class G2PRegisterSchemaHousehold(G2PRegisterBaseSchema, G2PGeoSchema, G2PSchemaHousehold):
    """
    Schema for Household register.
    Inherits fields from G2PRegisterBaseSchema and G2PGeoSchema.
    Attributes inherited from G2PSchemaHousehold are specific to the Household domain.
    """


class G2PRegisterHistorySchemaHousehold(G2PRegisterHistorySchema, G2PGeoHistorySchema):
    """
    Schema for Household history.
    Inherits fields from G2PRegisterHistorySchema and G2PGeoHistorySchema.
    """


class G2PIntakeFormSchemaHousehold(G2PIntakeFormSchemaBase, G2PRegisterBaseSchema, G2PGeoSchema, G2PSchemaHousehold):
    """
    Schema for Household intake form.
    Inherits fields from G2PRegisterBaseSchema and G2PGeoSchema.
    Attributes inherited from G2PSchemaHousehold are specific to the Household domain and are included in the intake form schema for data collection.
    """
