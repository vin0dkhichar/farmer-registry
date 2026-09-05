# ruff: noqa: E402
import asyncio
import logging

from .config import Settings

_config = Settings.get_config()

from openg2p_fastapi_common.app import Initializer as BaseInitializer
from openg2p_registry_core.app import Initializer as CoreInitializer

from .register_domain.models import (
    G2PRegisterFarmer, G2PRegisterHistoryFarmer,
    G2PRegisterHousehold, G2PRegisterHistoryHousehold,
    G2PRegisterHouseholdMember, G2PRegisterHistoryHouseholdMember,
    G2PRegisterCrop, G2PRegisterHistoryCrop,
    G2PRegisterLand, G2PRegisterHistoryLand,
    G2PRegisterFarmInputs, G2PRegisterHistoryFarmInputs,
    G2PRegisterLivestock, G2PRegisterHistoryLivestock,
    G2PRegisterMembershipDetails, G2PRegisterHistoryMembershipDetails,
    G2PIntakeFormHousehold, G2PIntakeFormFarmer, G2PIntakeFormHouseholdMember,
    G2PIntakeFormCrop, G2PIntakeFormLand, G2PIntakeFormFarmInputs, 
    G2PIntakeFormLivestock, G2PIntakeFormMembershipDetails,
)
from .register_domain.services import G2PRegisterDomainServiceFarmer, G2PRegisterDomainServiceHousehold

_logger = logging.getLogger(_config.logging_default_logger_name)


class Initializer(BaseInitializer):
    def initialize(self, **kwargs):
        super().initialize()
        CoreInitializer().initialize()

        G2PRegisterDomainServiceFarmer()
        G2PRegisterDomainServiceHousehold()

    def migrate_database(self, args):

        async def migrate():
            _logger.info("Migrating extensions database")

            await G2PRegisterHousehold.create_migrate()
            await G2PRegisterHistoryHousehold.create_migrate()
            await G2PIntakeFormHousehold.create_migrate()

            await G2PRegisterHouseholdMember.create_migrate()
            await G2PRegisterHistoryHouseholdMember.create_migrate()
            await G2PIntakeFormHouseholdMember.create_migrate()

            await G2PRegisterFarmer.create_migrate()
            await G2PRegisterHistoryFarmer.create_migrate()
            await G2PIntakeFormFarmer.create_migrate()

            await G2PRegisterMembershipDetails.create_migrate()
            await G2PRegisterHistoryMembershipDetails.create_migrate()
            await G2PIntakeFormMembershipDetails.create_migrate()

            await G2PRegisterLand.create_migrate()
            await G2PRegisterHistoryLand.create_migrate()
            await G2PIntakeFormLand.create_migrate()

            await G2PRegisterFarmInputs.create_migrate()
            await G2PRegisterHistoryFarmInputs.create_migrate()
            await G2PIntakeFormFarmInputs.create_migrate()

            await G2PRegisterCrop.create_migrate()
            await G2PRegisterHistoryCrop.create_migrate()
            await G2PIntakeFormCrop.create_migrate()

            await G2PRegisterLivestock.create_migrate()
            await G2PRegisterHistoryLivestock.create_migrate()
            await G2PIntakeFormLivestock.create_migrate()

        asyncio.run(migrate())
