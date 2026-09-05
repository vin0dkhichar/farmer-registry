import logging

from openg2p_registry_core.services import G2PRegisterDomainService

from .domain_validation_utils import as_int, validation_error

_logger = logging.getLogger("g2p-register-domain-service")


class G2PRegisterDomainServiceHousehold(G2PRegisterDomainService):
    async def validate_domain_attributes(self, records: list[dict]):
        for record in records:
            self._validate_household_size(record)

    def _validate_household_size(self, record: dict) -> None:
        size_of_group = as_int(record.get("size_of_group"))
        male = as_int(record.get("number_of_male_members"))
        female = as_int(record.get("number_of_female_members"))
        if size_of_group is not None and male is not None and female is not None:
            if size_of_group != male + female:
                validation_error(
                    "size_of_group must equal number_of_male_members + number_of_female_members"
                )

        children = as_int(record.get("number_of_children"))
        if size_of_group is not None and children is not None and children > size_of_group:
            validation_error("number_of_children must not exceed size_of_group")

        elderly = as_int(record.get("number_of_elderly_members"))
        if size_of_group is not None and elderly is not None and elderly > size_of_group:
            validation_error("number_of_elderly_members must not exceed size_of_group")

    def construct_search_text(self, payload: dict, extra: list[str] = None) -> str:
        _logger.info("Constructing search text for household")

        keys = [
            "functional_record_id",
            "record_name",
            "household_head",
            "latitude",
            "longitude",
            "altitude",
            "plus_code",
            "address_line_1",
            "address_line_2",
            "postal_code",
            "country_code",
        ]
        search_text = []
        if extra:
            search_text.extend(
                str(value).strip() for value in extra if str(value).strip()
            )
        search_text.extend(
            str(payload.get(key) or "").strip()
            for key in keys
            if str(payload.get(key) or "").strip()
        )

        return " ".join(search_text).strip()

    def construct_record_name(self, payload: dict, extra: list[str] = None) -> str:
        _logger.info("Constructing record name for household")

        keys = ["household_head", "functional_record_id"]
        record_name = []
        if extra:
            record_name.extend(str(item).strip() for item in extra if str(item).strip())
        record_name.extend(
            str(payload.get(key) or "").strip()
            for key in keys
            if str(payload.get(key) or "").strip()
        )

        return " ".join(record_name).strip()
