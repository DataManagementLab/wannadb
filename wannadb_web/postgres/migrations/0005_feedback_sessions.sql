CREATE TABLE public.feedback_sessions (
    user_id bigint NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    session_id text NOT NULL,
    base_id bigint NOT NULL REFERENCES public.document_bases(id) ON DELETE CASCADE,
    snapshot_id bigint NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
    attribute_schema_version uuid NOT NULL,
    snapshot_hash text NOT NULL CHECK (snapshot_hash ~ '^[a-f0-9]{64}$'),
    version bigint NOT NULL CHECK (version > 0),
    phase text NOT NULL CHECK (phase IN ('selection', 'ranking', 'finished')),
    attribute text,
    checkpoint bytea,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (user_id, session_id),
    CHECK (
        (phase = 'finished' AND attribute IS NULL AND checkpoint IS NULL)
        OR (phase IN ('selection', 'ranking') AND attribute IS NOT NULL AND checkpoint IS NOT NULL)
    )
);

CREATE INDEX feedback_sessions_expiry_idx ON public.feedback_sessions (expires_at);
CREATE INDEX feedback_sessions_base_id_idx ON public.feedback_sessions (base_id);
CREATE INDEX feedback_sessions_snapshot_id_idx ON public.feedback_sessions (snapshot_id);
