INSERT INTO "public"."approver_rule" (
    "id",
    "stage_id",
    "rule_type",
    "rule_value",
    "kind",
    "required",
    "created_at",
    "updated_at"
)
<<<<<<< HEAD
SELECT v."id", v."stage_id", v."rule_type", v."rule_value"::json, v."kind",
       v."required"::boolean, v."created_at"::timestamptz, v."updated_at"::timestamptz
FROM (VALUES
    ('4d45f51c-54a5-4850-921f-57f24128b956', '531b633a-faea-4d1a-ac1a-6e76016e8457', 'user', '{"user_id": "alex.carter"}', 'approver', 'FALSE', NOW(), NOW()),
    ('285f10fb-b221-44c0-b237-73bef2dd8a00', '6aea22f1-fe79-4aaa-9adb-5ccd9fe89b92', 'user', '{"user_id": "nina.patel"}', 'approver', 'FALSE', NOW(), NOW()),
    ('566c79dd-db66-40e0-8ea2-f58a7bca88f8', '8da27858-c065-43f9-95d7-310eb326743b', 'user', '{"user_id": "alex.carter"}', 'approver', 'FALSE', NOW(), NOW()),
    ('df2f2bb3-1eea-4ad9-a60d-afe065a1aeac', 'bbfc19f4-feb2-46cf-a101-2933b065b456', 'user', '{"user_id": "nina.patel"}', 'approver', 'FALSE', NOW(), NOW()),
    ('65861cd4-0833-4f0c-939f-49a32f176a50', '255f31be-f14c-40a5-a3fb-fd155ea79e54', 'user', '{"user_id": "alex.carter"}', 'approver', 'FALSE', NOW(), NOW()),
    ('eb97d0c0-f11e-4dbf-893c-1a0e14219e94', 'da640587-ffc0-432a-a6a9-82adeb8c5f42', 'user', '{"user_id": "nina.patel"}', 'approver', 'FALSE', NOW(), NOW()),
    ('c75ad1c2-8a76-44aa-bd25-afdf7cc9be26', '4b608b44-fe22-4b9c-acff-673a50db55bd', 'user', '{"user_id": "alex.carter"}', 'approver', 'FALSE', NOW(), NOW()),
    ('f05ee25b-b8aa-4fc7-9e2f-f58e767ae96f', '32c48f1c-20b9-4a28-883b-bc5949ddda5b', 'user', '{"user_id": "nina.patel"}', 'approver', 'FALSE', NOW(), NOW())
) AS v("id","stage_id","rule_type","rule_value","kind","required","created_at","updated_at")
-- Same reason as the stage filter: a rule whose stage was skipped must not abort
-- the statement and take the valid rules with it.
WHERE EXISTS (SELECT 1 FROM "public"."approval_stage" s WHERE s.id = v."stage_id")
ON CONFLICT DO NOTHING;
=======
SELECT v.id, s.id, v.rule_type, v.rule_value::json, v.kind, v.required, NOW(), NOW()
FROM (VALUES
    ('4d45f51c-54a5-4850-921f-57f24128b956', 'registry.change_request.farmer', 1, 'user', '{"user_id": "alex.carter"}', 'approver', FALSE),
    ('285f10fb-b221-44c0-b237-73bef2dd8a00', 'registry.change_request.farmer', 2, 'user', '{"user_id": "nina.patel"}', 'approver', FALSE),
    ('566c79dd-db66-40e0-8ea2-f58a7bca88f8', 'registry.change_request.household', 1, 'user', '{"user_id": "alex.carter"}', 'approver', FALSE),
    ('df2f2bb3-1eea-4ad9-a60d-afe065a1aeac', 'registry.change_request.household', 2, 'user', '{"user_id": "nina.patel"}', 'approver', FALSE),
    ('65861cd4-0833-4f0c-939f-49a32f176a50', 'registry.intake_form.farmer', 1, 'user', '{"user_id": "alex.carter"}', 'approver', FALSE),
    ('eb97d0c0-f11e-4dbf-893c-1a0e14219e94', 'registry.intake_form.farmer', 2, 'user', '{"user_id": "nina.patel"}', 'approver', FALSE),
    ('c75ad1c2-8a76-44aa-bd25-afdf7cc9be26', 'registry.intake_form.household', 1, 'user', '{"user_id": "alex.carter"}', 'approver', FALSE),
    ('f05ee25b-b8aa-4fc7-9e2f-f58e767ae96f', 'registry.intake_form.household', 2, 'user', '{"user_id": "nina.patel"}', 'approver', FALSE)
) AS v(id, policy_key, stage_order, rule_type, rule_value, kind, required)
INNER JOIN approval_policy p
    ON p.policy_key = v.policy_key
   AND p.version = 1
INNER JOIN approval_stage s
    ON s.policy_id = p.id
   AND s.stage_order = v.stage_order
WHERE NOT EXISTS (
    SELECT 1
    FROM approver_rule r
    WHERE r.stage_id = s.id
      AND r.rule_type = v.rule_type
      AND r.rule_value::text = v.rule_value
)
ON CONFLICT ("id") DO NOTHING;
>>>>>>> 1.2
