-- migrate:up

-- One row per security-relevant event. Rows are only ever ADDED, through audit.append().
CREATE TABLE audit.events (
    seq          bigint      PRIMARY KEY,                -- 1, 2, 3 … with no gaps (assigned by append)
    occurred_at  timestamptz NOT NULL,
    actor        text        NOT NULL,                   -- the token's "sub": a stable id, never a name
    client_id    text        NOT NULL,                   -- the app that acted for them (rag-web, rag-cli…)
    action       text        NOT NULL,                   -- search, admin:ping, …
    outcome      text        NOT NULL CHECK (outcome IN ('allowed', 'denied', 'error')),
    resource     text        NOT NULL,                   -- what was acted on
    details      jsonb       NOT NULL DEFAULT '{}',      -- e.g. ids of the documents returned
    trace_id     text,                                   -- links to the trace in Tempo (Step 21)
    prev_hash    bytea       NOT NULL CHECK (octet_length(prev_hash) = 32),
    hash         bytea       NOT NULL UNIQUE CHECK (octet_length(hash) = 32)
);
CREATE INDEX events_actor_time ON audit.events (actor, occurred_at);   -- "what did X do in March?"
CREATE INDEX events_trace ON audit.events (trace_id);                  -- "which event is this trace?"

-- The exact text that gets hashed. Same row -> same text, on any machine and in any time zone.
CREATE FUNCTION audit.event_body(e audit.events) RETURNS text
LANGUAGE sql STABLE SET search_path = pg_catalog, pg_temp AS $$
    SELECT jsonb_build_object(
        'seq',         e.seq,
        'occurred_at', to_char(e.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        'actor',       e.actor,
        'client_id',   e.client_id,
        'action',      e.action,
        'outcome',     e.outcome,
        'resource',    e.resource,
        'details',     e.details,
        'trace_id',    e.trace_id
    )::text
$$;

-- The ONLY way in. Runs with the owner's rights (SECURITY DEFINER), so callers need no table rights.
CREATE FUNCTION audit.append(
    p_actor     text,
    p_client_id text,
    p_action    text,
    p_outcome   text,
    p_resource  text,
    p_details   jsonb DEFAULT '{}',
    p_trace_id  text  DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    last audit.events%ROWTYPE;
    e    audit.events%ROWTYPE;
BEGIN
    -- Validate: an audit log full of junk is as useless as none
    IF p_actor IS NULL OR p_actor !~ '^[A-Za-z0-9._:@-]{1,128}$' THEN
        RAISE EXCEPTION 'audit.append: invalid actor' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_action IS NULL OR p_action !~ '^[a-z][a-z0-9_.:-]{0,63}$' THEN
        RAISE EXCEPTION 'audit.append: invalid action' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_trace_id IS NOT NULL AND p_trace_id !~ '^[0-9a-f]{32}$' THEN
        RAISE EXCEPTION 'audit.append: invalid trace id' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF octet_length(coalesce(p_details, '{}')::text) > 8192 THEN
        RAISE EXCEPTION 'audit.append: details larger than 8 KB' USING ERRCODE = 'program_limit_exceeded';
    END IF;

    -- One writer at a time: the chain has exactly one "latest link". Readers are not blocked.
    LOCK TABLE audit.events IN EXCLUSIVE MODE;
    SELECT * INTO last FROM audit.events ORDER BY seq DESC LIMIT 1;

    e.seq         := coalesce(last.seq, 0) + 1;
    e.prev_hash   := coalesce(last.hash, decode(repeat('00', 32), 'hex'));  -- genesis: 32 zero bytes
    e.occurred_at := clock_timestamp();                                     -- the real time, after the lock
    e.actor       := p_actor;
    e.client_id   := coalesce(nullif(p_client_id, ''), 'unknown');
    e.action      := p_action;
    e.outcome     := p_outcome;                                             -- CHECK constraint validates
    e.resource    := coalesce(p_resource, '');
    e.details     := coalesce(p_details, '{}');
    e.trace_id    := p_trace_id;
    e.hash        := sha256(e.prev_hash || convert_to(audit.event_body(e), 'UTF8'));

    INSERT INTO audit.events SELECT (e).*;
    RETURN e.seq;
END
$$;

-- Recompute the chain and report the FIRST broken link (or ok = true).
CREATE FUNCTION audit.verify(p_from bigint DEFAULT 1, p_to bigint DEFAULT NULL)
RETURNS TABLE (ok boolean, checked bigint, first_bad_seq bigint, problem text)
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    e        audit.events%ROWTYPE;
    expected bigint := p_from;
    prev     bytea;
    n        bigint := 0;
BEGIN
    IF p_from = 1 THEN
        prev := decode(repeat('00', 32), 'hex');
    ELSE
        SELECT hash INTO prev FROM audit.events WHERE seq = p_from - 1;
        IF NOT FOUND THEN
            RETURN QUERY SELECT false, 0::bigint, p_from - 1, format('row %s is missing', p_from - 1);
            RETURN;
        END IF;
    END IF;

    FOR e IN SELECT * FROM audit.events
             WHERE seq >= p_from AND (p_to IS NULL OR seq <= p_to) ORDER BY seq LOOP
        IF e.seq <> expected THEN
            RETURN QUERY SELECT false, n, expected,
                format('row %s is missing (the next row is %s)', expected, e.seq);
            RETURN;
        END IF;
        IF e.prev_hash <> prev THEN
            RETURN QUERY SELECT false, n, e.seq,
                'link broken: prev_hash does not match the previous row''s hash'::text;
            RETURN;
        END IF;
        IF e.hash <> sha256(e.prev_hash || convert_to(audit.event_body(e), 'UTF8')) THEN
            RETURN QUERY SELECT false, n, e.seq, 'contents changed: hash does not match the row'::text;
            RETURN;
        END IF;
        prev := e.hash;
        expected := expected + 1;
        n := n + 1;
    END LOOP;
    RETURN QUERY SELECT true, n, NULL::bigint, NULL::text;
END
$$;

-- Append-only: UPDATE, DELETE and TRUNCATE are refused, even for the table's owner.
CREATE FUNCTION audit.forbid_change() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    RAISE EXCEPTION 'audit.events is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END
$$;
CREATE TRIGGER events_append_only
    BEFORE UPDATE OR DELETE OR TRUNCATE ON audit.events
    FOR EACH STATEMENT EXECUTE FUNCTION audit.forbid_change();

-- Exactly the rights each role needs, nothing more
REVOKE ALL ON audit.events FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA audit FROM PUBLIC;   -- belt and braces (bootstrap did it too)
GRANT EXECUTE ON FUNCTION audit.append(text, text, text, text, text, jsonb, text) TO audit_writer;
GRANT SELECT ON audit.events TO audit_reader;
GRANT EXECUTE ON FUNCTION audit.verify(bigint, bigint), audit.event_body(audit.events) TO audit_reader;

-- migrate:down

-- An audit log is never rolled back. Fix mistakes with a new, forward migration.
DO $$ BEGIN
    RAISE EXCEPTION 'the audit log cannot be rolled back: write a new forward migration instead';
END $$;
