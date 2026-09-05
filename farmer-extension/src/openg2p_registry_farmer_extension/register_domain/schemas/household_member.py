from typing import Optional

from openg2p_registry_core.schemas import (
    G2PRegisterBaseSchema, G2PPersonSchema, G2PGeoSchema,
    G2PRegisterHistorySchema, G2PPersonHistorySchema, G2PGeoHistorySchema,
    G2PIntakeFormSchemaBase
)
from ..models.enums import RelationshipToTheHeadEnum


class G2PSchemaHouseholdMember:

    is_disabled: Optional[bool] = None
    is_head: Optional[bool] = None
    relationship_to_the_head: Optional[RelationshipToTheHeadEnum] = None


class G2PRegisterSchemaHouseholdMember(G2PRegisterBaseSchema, G2PPersonSchema, G2PGeoSchema, G2PSchemaHouseholdMember):
    """
    Schema for HouseholdMember register.
    Inherits fields from G2PRegisterBaseSchema, G2PPersonSchema, and G2PGeoSchema.
    Attributes inherited from G2PSchemaHouseholdMember are specific to the Household Member domain.
    """


class G2PRegisterHistorySchemaHouseholdMember(G2PRegisterHistorySchema, G2PPersonHistorySchema, G2PGeoHistorySchema):
    """
    Schema for HouseholdMember history.
    Inherits fields from G2PRegisterHistorySchema, G2PPersonHistorySchema, and G2PGeoHistorySchema.
    """


class G2PIntakeFormSchemaHouseholdMember(G2PIntakeFormSchemaBase, G2PRegisterBaseSchema, G2PPersonSchema, G2PGeoSchema, G2PSchemaHouseholdMember):
    """
    Schema for HouseholdMember intake form.
    Inherits fields from G2PRegisterBaseSchema, G2PPersonSchema, and G2PGeoSchema.
    Attributes inherited from G2PSchemaHouseholdMember are specific to the Household Member domain and are included in the intake form schema for data collection.
    """

