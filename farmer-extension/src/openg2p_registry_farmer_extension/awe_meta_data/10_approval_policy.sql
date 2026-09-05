INSERT INTO "public"."approval_policy" (
    "id",
    "policy_key",
    "version",
    "name",
    "description",
    "status",
    "artifact_type",
    "created_by",
    "forbid_self_approval",
    "forbid_repeat_approvers",
    "created_at",
    "updated_at"
) VALUES
    ('576a69ba-a2ca-4c34-80b7-952e8c5a86f8', 'registry.change_request.farmer', 1, 'Policy for Farmer Change Request', NULL, 'active', 'registry.change_request', 'seed', 'FALSE', 'FALSE', NOW(), NOW()),
    ('57f40743-266c-4e25-9a16-fd45483f904c', 'registry.change_request.household', 1, 'Policy for Household Change Request', NULL, 'active', 'registry.change_request', 'seed', 'FALSE', 'FALSE', NOW(), NOW()),
    ('e725a02c-6120-4e33-b4ec-294a38b07b18', 'registry.intake_form.farmer', 1, 'Policy for Farmer Intake Form', NULL, 'active', 'registry.intake_form', 'seed', 'FALSE', 'FALSE', NOW(), NOW()),
    ('fb51a862-d2ed-460d-8e1f-929cbeabdd01', 'registry.intake_form.household', 1, 'Policy for Household Intake Form', NULL, 'active', 'registry.intake_form', 'seed', 'FALSE', 'FALSE', NOW(), NOW())
ON CONFLICT ("policy_key", "version") DO NOTHING;
