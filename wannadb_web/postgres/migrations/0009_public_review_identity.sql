LOCK TABLE public.document_feedback IN ACCESS EXCLUSIVE MODE;

ALTER TABLE public.document_feedback
    ADD COLUMN attribute_id uuid,
    ADD COLUMN mapping_revision text,
    ADD COLUMN source_revision text,
    ADD COLUMN feedback_revision uuid NOT NULL DEFAULT gen_random_uuid();

-- Historical votes retain their rows, but the value originally reviewed is unknown.
-- Valid corrections stay reviewable against their exact source and occurrence.
UPDATE public.document_feedback f
SET source_revision = encode(sha256(convert_to(d.content, 'UTF8')), 'hex'),
    attribute_id = (b.attribute_ids ->> f.attribute)::uuid
FROM public.documents d JOIN public.document_bases b
    ON b.id = d.documentbaseid AND b.organisation_id = d.organisationid
WHERE f.documentid = d.id;

ALTER TABLE public.document_feedback
    ADD CONSTRAINT document_feedback_mapping_revision_check
        CHECK (mapping_revision IS NULL OR mapping_revision ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT document_feedback_source_revision_check
        CHECK (source_revision IS NULL OR source_revision ~ '^[0-9a-f]{64}$');
