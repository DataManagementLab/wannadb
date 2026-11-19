ALTER TABLE public.document_feedback
    ADD COLUMN reviewed boolean NOT NULL DEFAULT FALSE;
