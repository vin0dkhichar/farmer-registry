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
