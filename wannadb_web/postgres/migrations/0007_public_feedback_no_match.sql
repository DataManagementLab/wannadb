ALTER TABLE public.document_feedback
    ADD COLUMN no_match boolean NOT NULL DEFAULT FALSE,
    ADD CONSTRAINT document_feedback_no_match_check
        CHECK (NOT no_match OR (NOT positive AND feedback_start IS NULL AND feedback_end IS NULL));
