CREATE TABLE public.feedback_outcomes (
    user_id bigint NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    command_id text NOT NULL,
    session_id text NOT NULL,
    base_id bigint NOT NULL REFERENCES public.document_bases(id) ON DELETE CASCADE,
    expected_version bigint NOT NULL CHECK (expected_version > 0),
    request_fingerprint text NOT NULL,
    snapshot_version text NOT NULL,
    committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (user_id, command_id)
);

CREATE INDEX feedback_outcomes_base_id_idx ON public.feedback_outcomes (base_id);
