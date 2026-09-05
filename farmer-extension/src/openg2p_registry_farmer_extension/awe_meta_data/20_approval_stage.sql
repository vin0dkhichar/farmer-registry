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
<<<<<<< HEAD
SELECT v."id", v."policy_id", v."stage_order"::int, v."name", v."mode",
       v."mode_value"::int, v."sla_hours"::int, v."parallel_group"::int,
       v."skip_if"::json, v."on_empty", v."on_breach",
       v."escalation_rules_json"::json, v."created_at"::timestamptz, v."updated_at"::timestamptz
FROM (VALUES
    ('531b633a-faea-4d1a-ac1a-6e76016e8457', '576a69ba-a2ca-4c34-80b7-952e8c5a86f8', 1, 'Stage 1 Officers', 'all', NULL, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('6aea22f1-fe79-4aaa-9adb-5ccd9fe89b92', '576a69ba-a2ca-4c34-80b7-952e8c5a86f8', 2, 'Stage 2 Officers', 'all', NULL, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('8da27858-c065-43f9-95d7-310eb326743b', '57f40743-266c-4e25-9a16-fd45483f904c', 1, 'Stage 1 Officers', 'all', NULL, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('bbfc19f4-feb2-46cf-a101-2933b065b456', '57f40743-266c-4e25-9a16-fd45483f904c', 2, 'Stage 2 Officers', 'all', NULL, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('255f31be-f14c-40a5-a3fb-fd155ea79e54', 'e725a02c-6120-4e33-b4ec-294a38b07b18', 1, 'Stage 1 Officers', 'all', NULL, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('da640587-ffc0-432a-a6a9-82adeb8c5f42', 'e725a02c-6120-4e33-b4ec-294a38b07b18', 2, 'Stage 2 Officers', 'all', NULL, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('4b608b44-fe22-4b9c-acff-673a50db55bd', 'fb51a862-d2ed-460d-8e1f-929cbeabdd01', 1, 'Stage 1 Officers', 'all', NULL, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('32c48f1c-20b9-4a28-883b-bc5949ddda5b', 'fb51a862-d2ed-460d-8e1f-929cbeabdd01', 2, 'Stage 2 Officers', 'all', NULL, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW())
) AS v("id","policy_id","stage_order","name","mode","mode_value","sla_hours",
        "parallel_group","skip_if","on_empty","on_breach","escalation_rules_json",
        "created_at","updated_at")
-- Skip stages whose policy is absent. A policy row can legitimately be skipped
-- above (the platform already owns that policy_key), and without this filter the
-- orphan's FK violation aborts the whole statement, taking the valid stages with it.
WHERE EXISTS (SELECT 1 FROM "public"."approval_policy" p WHERE p.id = v."policy_id")
ON CONFLICT DO NOTHING;
=======
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
>>>>>>> 1.2
