ALTER TABLE public.document_bases
    ADD COLUMN attribute_schema_version uuid NOT NULL DEFAULT gen_random_uuid(),
    ADD COLUMN attribute_ids jsonb NOT NULL DEFAULT '{}'::jsonb;

-- Older snapshots already contain their attribute names. The web application
-- derives initial IDs from the per-base UUID and stores them on the first edit.
