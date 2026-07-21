-- Eligible and contacted leads for an Olmem Tech admin page
SELECT
    p.id,
    p.company_name,
    p.website,
    p.contact_email,
    p.contact_email_source_url,
    p.selected_offer_key,
    p.fit_score,
    p.status,
    p.research_json,
    p.fit_json,
    p.last_contacted_at,
    p.updated_at
FROM outreach_prospects p
ORDER BY
    CASE p.status
        WHEN 'eligible' THEN 1
        WHEN 'contacted' THEN 2
        WHEN 'rejected' THEN 3
        ELSE 4
    END,
    p.fit_score DESC NULLS LAST,
    p.updated_at DESC;

-- Engagement timeline
SELECT
    m.id AS message_id,
    p.company_name,
    m.recipient_email,
    m.subject,
    m.status AS message_status,
    e.event_type,
    e.occurred_at,
    e.event_json
FROM outreach_messages m
JOIN outreach_prospects p ON p.id = m.prospect_id
LEFT JOIN outreach_events e ON e.message_id = m.id
ORDER BY COALESCE(e.occurred_at, m.created_at) DESC;
