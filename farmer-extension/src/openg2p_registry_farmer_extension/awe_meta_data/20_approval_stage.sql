INSERT INTO "public"."approval_stage" (
    "id",
    "policy_id",
    "stage_order",
    "name",
    "mode",
    "mode_value",
    "sla_hours",
    "parallel_group",
    "skip_if",
    "on_empty",
    "on_breach",
    "escalation_rules_json",
    "created_at",
    "updated_at"
)
SELECT v.id, p.id, v.stage_order, v.name, v.mode,
       CAST(NULL AS integer), CAST(NULL AS integer), CAST(NULL AS integer),
       'null', 'block', CAST(NULL AS integer), 'null',
       NOW(), NOW()
FROM (VALUES
    ('531b633a-faea-4d1a-ac1a-6e76016e8457', 'registry.change_request.farmer', 1, 'Stage 1 Officers', 'all'),
    ('6aea22f1-fe79-4aaa-9adb-5ccd9fe89b92', 'registry.change_request.farmer', 2, 'Stage 2 Officers', 'all'),
    ('8da27858-c065-43f9-95d7-310eb326743b', 'registry.change_request.household', 1, 'Stage 1 Officers', 'all'),
    ('bbfc19f4-feb2-46cf-a101-2933b065b456', 'registry.change_request.household', 2, 'Stage 2 Officers', 'all'),
    ('255f31be-f14c-40a5-a3fb-fd155ea79e54', 'registry.intake_form.farmer', 1, 'Stage 1 Officers', 'all'),
    ('da640587-ffc0-432a-a6a9-82adeb8c5f42', 'registry.intake_form.farmer', 2, 'Stage 2 Officers', 'all'),
    ('4b608b44-fe22-4b9c-acff-673a50db55bd', 'registry.intake_form.household', 1, 'Stage 1 Officers', 'all'),
    ('32c48f1c-20b9-4a28-883b-bc5949ddda5b', 'registry.intake_form.household', 2, 'Stage 2 Officers', 'all')
) AS v(id, policy_key, stage_order, name, mode)
INNER JOIN approval_policy p
    ON p.policy_key = v.policy_key
   AND p.version = 1
WHERE NOT EXISTS (
    SELECT 1
    FROM approval_stage s
    WHERE s.policy_id = p.id
      AND s.stage_order = v.stage_order
)
ON CONFLICT ("id") DO NOTHING;
