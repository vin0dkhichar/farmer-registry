-- NOTE: requires_registrant_authentication is TRUE on Farmer. Core refuses to
-- start a registrant authentication for a register that does not declare it,
-- and VC issuance is gated on that authentication -- so with it FALSE the
-- agent portal fails with "Registrant authentication is not enabled for this
-- register" and no credential can ever be issued.
INSERT INTO "public"."g2p_register_definitions" ("register_id","register_mnemonic","register_subject","register_description","master_register_id","register_rank","functional_id_generation_required","register_purpose","program_id","program_mnemonic","register_icon","has_image","dedup_is_enabled","dedup_threshold_score","completion_score_required","outgest_applicable","requires_registrant_authentication","registrant_authentication_validity_days","registrant_re_auth_warning_days_before") VALUES
('18df8370-3e9a-493f-aa27-fc1b9e05629c','FarmInputs','Farm Inputs','Farm Inputs Register','493153d5-07ef-4743-8efd-07f4099772b9',50,'FALSE','TABLE',NULL,NULL,NULL,'FALSE','FALSE',0,'FALSE','FALSE','FALSE',730,30),
('493153d5-07ef-4743-8efd-07f4099772b9','Land','Lands','Land Register','a1a4d25a-1cd4-4356-abac-985a0b3c6bcd',20,'FALSE','TABLE',NULL,NULL,NULL,'FALSE','FALSE',0,'FALSE','FALSE','FALSE',730,30),
('495f251c-83a5-4025-a307-1925712c9d0b','MembershipDetails','Membership Details','Membership Details Register','a1a4d25a-1cd4-4356-abac-985a0b3c6bcd',60,'FALSE','TABLE',NULL,NULL,NULL,'FALSE','FALSE',0,'FALSE','FALSE','FALSE',730,30),
('4bcb88a3-fc5e-44d2-abc6-e2c68670c5bb','Livestock','Livestocks','Livestock Register','493153d5-07ef-4743-8efd-07f4099772b9',40,'FALSE','TABLE',NULL,NULL,NULL,'FALSE','FALSE',0,'FALSE','FALSE','FALSE',730,30),
('52979fdd-220c-48dd-8de0-0a434e786427','HouseholdMember','Household Members','Household Member Register','9055ab43-c85d-4833-bd00-ca657bb72644',10,'FALSE','TABLE',NULL,NULL,NULL,'FALSE','FALSE',0,'FALSE','FALSE','FALSE',730,30),
('5fa096f8-ffdc-4b0a-ab16-9ca386c23310','Crop','Crops','Crop Register','493153d5-07ef-4743-8efd-07f4099772b9',30,'FALSE','TABLE',NULL,NULL,NULL,'FALSE','FALSE',0,'FALSE','FALSE','FALSE',730,30),
('a1a4d25a-1cd4-4356-abac-638239923092','Score','Scores','Score Register','9055ab43-c85d-4833-bd00-ca657bb72644',80,'FALSE','CORE_TABLE','NULL','NULL','','FALSE','FALSE',0,'FALSE','FALSE','FALSE',730,30),
<<<<<<< HEAD
('a1a4d25a-1cd4-4356-abac-985a0b3c6bcd','Farmer','Farmers','Farmer register description','9055ab43-c85d-4833-bd00-ca657bb72644',1,'FALSE','REGISTER',NULL,NULL,'','FALSE','TRUE',70,'TRUE','FALSE','TRUE',730,30),
('9055ab43-c85d-4833-bd00-ca657bb72644','Household','Households','Household Register',NULL,2,'FALSE','REGISTER',NULL,NULL,'','FALSE','TRUE',70,'FALSE','FALSE','FALSE',730,30);
=======
('a1a4d25a-1cd4-4356-abac-985a0b3c6bcd','Farmer','Farmers','Farmer register description','9055ab43-c85d-4833-bd00-ca657bb72644',1,'TRUE','REGISTER',NULL,NULL,'','FALSE','TRUE',70,'TRUE','FALSE','FALSE',730,30),
('9055ab43-c85d-4833-bd00-ca657bb72644','Household','Households','Household Register',NULL,2,'TRUE','REGISTER',NULL,NULL,'','FALSE','TRUE',70,'FALSE','FALSE','FALSE',730,30);
>>>>>>> 1.2
