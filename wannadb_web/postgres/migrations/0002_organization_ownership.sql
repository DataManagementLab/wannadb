-- The organization owns shared content. A user ID records attribution only.
ALTER TABLE public.documents ALTER COLUMN userid DROP NOT NULL;
ALTER TABLE public.document_feedback ALTER COLUMN userid DROP NOT NULL;

-- The original setup and the versioned baseline used different constraint names.
DO $$
DECLARE
    prior_fk record;
BEGIN
    FOR prior_fk IN
        SELECT fk.conrelid::regclass AS relation, fk.conname
        FROM pg_constraint fk
        JOIN pg_attribute col ON col.attrelid = fk.conrelid AND col.attname = 'userid'
        WHERE fk.contype = 'f' AND fk.confrelid = 'public.users'::regclass
          AND fk.conrelid IN ('public.documents'::regclass, 'public.document_feedback'::regclass)
          AND fk.conkey = ARRAY[col.attnum]
    LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', prior_fk.relation, prior_fk.conname);
    END LOOP;
END;
$$;

-- Older unvalidated constraints can leave a reference to a missing account.
UPDATE public.documents d SET userid = NULL
WHERE d.userid IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.users u WHERE u.id = d.userid);
UPDATE public.document_feedback f SET userid = NULL
WHERE f.userid IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.users u WHERE u.id = f.userid);

ALTER TABLE public.documents ADD CONSTRAINT documents_userid_fkey
    FOREIGN KEY (userid) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL;
ALTER TABLE public.document_feedback ADD CONSTRAINT document_feedback_userid_fkey
    FOREIGN KEY (userid) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL;

COMMENT ON COLUMN public.documents.userid IS 'Creator attribution. The organization owns the document or snapshot.';
COMMENT ON COLUMN public.document_feedback.userid IS 'Contributor attribution. The feedback belongs to its document.';
