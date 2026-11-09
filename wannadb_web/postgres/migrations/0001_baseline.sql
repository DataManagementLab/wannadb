-- Adopt the original public schema or create it on a fresh database.
CREATE TABLE IF NOT EXISTS public.users (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username text NOT NULL UNIQUE,
    password bytea NOT NULL
);

CREATE TABLE IF NOT EXISTS public.organisations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS public.membership (
    userid bigint NOT NULL REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    organisationid bigint NOT NULL REFERENCES public.organisations(id) ON UPDATE CASCADE ON DELETE CASCADE,
    authorisation bigint NOT NULL DEFAULT 10,
    PRIMARY KEY (userid, organisationid)
);

CREATE INDEX IF NOT EXISTS fki_organisationid ON public.membership (organisationid);

CREATE TABLE IF NOT EXISTS public.document_bases (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    attributes text NOT NULL DEFAULT '[]',
    organisation_id bigint NOT NULL REFERENCES public.organisations(id) ON UPDATE CASCADE ON DELETE CASCADE,
    last_modified timestamp NOT NULL DEFAULT now(),
    UNIQUE (name, organisation_id)
);

CREATE TABLE IF NOT EXISTS public.documents (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    content text,
    content_byte bytea,
    organisationid bigint NOT NULL REFERENCES public.organisations(id) ON UPDATE CASCADE ON DELETE CASCADE,
    userid bigint NOT NULL REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    documentbaseid bigint
);

CREATE TABLE IF NOT EXISTS public.document_feedback (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    documentid bigint NOT NULL REFERENCES public.documents(id) ON UPDATE CASCADE ON DELETE CASCADE,
    userid bigint NOT NULL REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    positive boolean NOT NULL,
    attribute text NOT NULL,
    feedback_start integer,
    feedback_end integer
);

-- Older installs may predate these two columns. Keep their existing rows and keys.
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS documentbaseid bigint;
ALTER TABLE public.document_bases ADD COLUMN IF NOT EXISTS last_modified timestamp NOT NULL DEFAULT now();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE contype = 'f'
          AND conrelid = 'public.documents'::regclass
          AND confrelid = 'public.document_bases'::regclass
          AND conkey = ARRAY[
              (SELECT attnum FROM pg_attribute WHERE attrelid = conrelid AND attname = 'documentbaseid')
          ]
          AND confkey = ARRAY[
              (SELECT attnum FROM pg_attribute WHERE attrelid = confrelid AND attname = 'id')
          ]
    ) THEN
        ALTER TABLE public.documents ADD CONSTRAINT documents_base_fkey
            FOREIGN KEY (documentbaseid) REFERENCES public.document_bases(id)
            ON UPDATE CASCADE ON DELETE CASCADE;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.update_last_modified()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.last_modified = now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER update_last_modified_trigger
    BEFORE UPDATE ON public.document_bases
    FOR EACH ROW EXECUTE FUNCTION public.update_last_modified();
