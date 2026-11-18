-- Baseline schema for open-finnish-lexicon.
--
-- warehouse: provenance and raw source documents
-- lexicon:   lexemes, senses, forms, examples, relations, topics
-- zh_layer:  Chinese glosses and example translations
-- semantic:  Chinese gloss candidates and sense alignment

create extension if not exists unaccent with schema public;
create extension if not exists pg_trgm with schema public;

create schema if not exists lexicon;

create schema if not exists semantic;

create schema if not exists warehouse;

create schema if not exists zh_layer;

CREATE OR REPLACE FUNCTION lexicon.immutable_unaccent(text) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    AS $_$ select public.unaccent('public.unaccent', $1) $_$;


SET default_tablespace = '';

SET default_table_access_method = heap;

CREATE TABLE lexicon.collocation (
    id bigint NOT NULL,
    lexeme_id bigint,
    sense_id bigint,
    phrase text NOT NULL,
    score numeric(8,5) DEFAULT 0.0 NOT NULL,
    source_label text NOT NULL
);

CREATE SEQUENCE lexicon.collocation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.collocation_id_seq OWNED BY lexicon.collocation.id;

CREATE TABLE lexicon.derivation_relation (
    id bigint NOT NULL,
    parent_lexeme_id bigint NOT NULL,
    child_lexeme_id bigint NOT NULL,
    relation_type text NOT NULL,
    note text
);

CREATE SEQUENCE lexicon.derivation_relation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.derivation_relation_id_seq OWNED BY lexicon.derivation_relation.id;

CREATE TABLE lexicon.derivation_relation_source (
    relation_id bigint NOT NULL,
    source_file_id bigint NOT NULL
);

CREATE TABLE lexicon.example (
    id bigint NOT NULL,
    text_fi text NOT NULL,
    text_en text,
    source_label text NOT NULL,
    quality_score numeric(6,5) DEFAULT 0.0 NOT NULL
);

CREATE SEQUENCE lexicon.example_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.example_id_seq OWNED BY lexicon.example.id;

CREATE TABLE lexicon.example_morphology_validation (
    example_id bigint NOT NULL,
    verdict text NOT NULL,
    token_count integer DEFAULT 0 NOT NULL,
    unknown_count integer DEFAULT 0 NOT NULL,
    unknown_tokens text[] DEFAULT '{}'::text[] NOT NULL,
    name_like_count integer DEFAULT 0 NOT NULL,
    name_like_tokens text[] DEFAULT '{}'::text[] NOT NULL,
    recognizer_version text NOT NULL,
    validated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT example_morphology_validation_counts_valid CHECK (((token_count >= 0) AND (unknown_count >= 0) AND (name_like_count >= 0))),
    CONSTRAINT example_morphology_validation_name_like_count_matches CHECK ((name_like_count = cardinality(name_like_tokens))),
    CONSTRAINT example_morphology_validation_unknown_count_matches CHECK ((unknown_count = cardinality(unknown_tokens))),
    CONSTRAINT example_morphology_validation_verdict_valid CHECK ((verdict = ANY (ARRAY['valid'::text, 'unknown_tokens'::text, 'empty'::text])))
);

CREATE VIEW lexicon.example_morphology_summary AS
 SELECT split_part(e.source_label, ':'::text, 1) AS source_family,
    count(*) AS examples,
    count(v.example_id) AS validated,
    count(*) FILTER (WHERE (v.verdict = 'valid'::text)) AS valid,
    count(*) FILTER (WHERE (v.verdict = 'unknown_tokens'::text)) AS unknown_tokens,
    count(*) FILTER (WHERE (v.verdict = 'empty'::text)) AS empty,
    round(((100.0 * (count(*) FILTER (WHERE (v.verdict = 'unknown_tokens'::text)))::numeric) / (NULLIF(count(v.example_id), 0))::numeric), 2) AS unknown_pct,
    sum(COALESCE(v.unknown_count, 0)) AS unknown_token_instances
   FROM (lexicon.example e
     LEFT JOIN lexicon.example_morphology_validation v ON ((v.example_id = e.id)))
  GROUP BY (split_part(e.source_label, ':'::text, 1))
  ORDER BY (round(((100.0 * (count(*) FILTER (WHERE (v.verdict = 'unknown_tokens'::text)))::numeric) / (NULLIF(count(v.example_id), 0))::numeric), 2)) DESC NULLS LAST, (split_part(e.source_label, ':'::text, 1));

CREATE TABLE lexicon.form (
    id bigint NOT NULL,
    lexeme_id bigint NOT NULL,
    surface_form text NOT NULL,
    normalized_form text NOT NULL,
    form_kind text NOT NULL,
    features jsonb DEFAULT '{}'::jsonb NOT NULL
)
WITH (autovacuum_vacuum_scale_factor='0.05', autovacuum_vacuum_cost_limit='2000');

CREATE TABLE lexicon.form_analysis (
    id bigint NOT NULL,
    normalized_query text NOT NULL,
    lexeme_id bigint NOT NULL,
    analysis_rank integer NOT NULL,
    confidence numeric(6,5) NOT NULL,
    features jsonb DEFAULT '{}'::jsonb NOT NULL
);

CREATE SEQUENCE lexicon.form_analysis_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.form_analysis_id_seq OWNED BY lexicon.form_analysis.id;

CREATE SEQUENCE lexicon.form_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.form_id_seq OWNED BY lexicon.form.id;

CREATE TABLE lexicon.form_source (
    form_id bigint NOT NULL,
    source_file_id bigint NOT NULL
)
WITH (autovacuum_vacuum_scale_factor='0.05', autovacuum_vacuum_cost_limit='2000');

CREATE TABLE lexicon.form_validation (
    form_id bigint NOT NULL,
    verdict text NOT NULL,
    predicted_surface text,
    validator text NOT NULL,
    rule text,
    confidence numeric(6,5) NOT NULL,
    explanation text DEFAULT ''::text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
)
WITH (autovacuum_vacuum_scale_factor='0.02', autovacuum_vacuum_cost_limit='2000');

CREATE TABLE lexicon.frequency_signal (
    id bigint NOT NULL,
    lexeme_id bigint NOT NULL,
    source_name text NOT NULL,
    raw_count bigint NOT NULL,
    normalized_score numeric(8,5) NOT NULL
);

CREATE SEQUENCE lexicon.frequency_signal_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.frequency_signal_id_seq OWNED BY lexicon.frequency_signal.id;

CREATE TABLE lexicon.grammar_note (
    id bigint NOT NULL,
    lexeme_id bigint,
    sense_id bigint,
    note_fi text,
    note_en text,
    note_kind text NOT NULL
);

CREATE SEQUENCE lexicon.grammar_note_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.grammar_note_id_seq OWNED BY lexicon.grammar_note.id;

CREATE TABLE lexicon.grammar_note_source (
    grammar_note_id bigint NOT NULL,
    source_file_id bigint NOT NULL
);

CREATE TABLE lexicon.lexeme (
    id bigint NOT NULL,
    lemma text NOT NULL,
    display_lemma text NOT NULL,
    part_of_speech text NOT NULL,
    frequency_rank integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE lexicon.lexeme_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.lexeme_id_seq OWNED BY lexicon.lexeme.id;

CREATE TABLE lexicon.lexeme_sense (
    id bigint NOT NULL,
    lexeme_id bigint NOT NULL,
    sense_key text NOT NULL,
    gloss_fi text,
    gloss_en text,
    labels text[] DEFAULT '{}'::text[] NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL
);

CREATE SEQUENCE lexicon.lexeme_sense_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.lexeme_sense_id_seq OWNED BY lexicon.lexeme_sense.id;

CREATE TABLE lexicon.lexical_relation (
    id bigint NOT NULL,
    source_lexeme_id bigint NOT NULL,
    target_lexeme_id bigint NOT NULL,
    relation_type text NOT NULL,
    confidence numeric(6,5) DEFAULT 1.0 NOT NULL
);

CREATE SEQUENCE lexicon.lexical_relation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.lexical_relation_id_seq OWNED BY lexicon.lexical_relation.id;

CREATE TABLE lexicon.lexical_relation_source (
    relation_id bigint NOT NULL,
    source_file_id bigint NOT NULL
);

CREATE TABLE lexicon.pronunciation (
    id bigint NOT NULL,
    lexeme_id bigint NOT NULL,
    ipa text,
    syllabification text,
    tts_voice text DEFAULT 'fi'::text NOT NULL
);

CREATE SEQUENCE lexicon.pronunciation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.pronunciation_id_seq OWNED BY lexicon.pronunciation.id;

CREATE TABLE lexicon.pronunciation_source (
    pronunciation_id bigint NOT NULL,
    source_file_id bigint NOT NULL
);

CREATE TABLE lexicon.sense_example (
    id bigint NOT NULL,
    sense_id bigint NOT NULL,
    example_id bigint NOT NULL,
    is_core boolean DEFAULT false NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL
);

CREATE SEQUENCE lexicon.sense_example_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.sense_example_id_seq OWNED BY lexicon.sense_example.id;

CREATE TABLE lexicon.sense_source (
    sense_id bigint NOT NULL,
    source_file_id bigint NOT NULL
);

CREATE TABLE lexicon.usage_warning (
    id bigint NOT NULL,
    lexeme_id bigint,
    sense_id bigint,
    warning_fi text,
    warning_en text,
    warning_kind text NOT NULL
);

CREATE SEQUENCE lexicon.usage_warning_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.usage_warning_id_seq OWNED BY lexicon.usage_warning.id;

CREATE TABLE lexicon.usage_warning_source (
    usage_warning_id bigint NOT NULL,
    source_file_id bigint NOT NULL
);

CREATE TABLE semantic.sense_alignment (
    id bigint NOT NULL,
    source_name text NOT NULL,
    source_document_id bigint NOT NULL,
    target_sense_id bigint NOT NULL,
    status text NOT NULL,
    confidence_score numeric(6,5) NOT NULL,
    selection_reason text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE semantic.sense_alignment_candidate (
    id bigint NOT NULL,
    source_name text NOT NULL,
    source_document_id bigint NOT NULL,
    target_sense_id bigint NOT NULL,
    candidate_kind text NOT NULL,
    confidence_score numeric(6,5) NOT NULL,
    match_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE semantic.sense_alignment_candidate_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE semantic.sense_alignment_candidate_id_seq OWNED BY semantic.sense_alignment_candidate.id;

CREATE SEQUENCE semantic.sense_alignment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE semantic.sense_alignment_id_seq OWNED BY semantic.sense_alignment.id;

CREATE TABLE semantic.zh_gloss_candidate (
    id bigint NOT NULL,
    target_sense_id bigint NOT NULL,
    source_name text NOT NULL,
    source_document_id bigint NOT NULL,
    gloss_zh text NOT NULL,
    confidence_score numeric(6,5) NOT NULL,
    candidate_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE semantic.zh_gloss_candidate_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE semantic.zh_gloss_candidate_id_seq OWNED BY semantic.zh_gloss_candidate.id;

CREATE TABLE semantic.zh_gloss_selection (
    target_sense_id bigint NOT NULL,
    zh_gloss_candidate_id bigint NOT NULL,
    gloss_zh text NOT NULL,
    selected_by text NOT NULL,
    confidence_score numeric(6,5) NOT NULL,
    selection_reason text NOT NULL,
    selected_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE warehouse.build_run (
    id bigint NOT NULL,
    build_kind text NOT NULL,
    status text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone
);

CREATE SEQUENCE warehouse.build_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE warehouse.build_run_id_seq OWNED BY warehouse.build_run.id;

CREATE TABLE warehouse.parser_run (
    id bigint NOT NULL,
    build_run_id bigint,
    source_registry_id bigint,
    parser_name text NOT NULL,
    status text NOT NULL,
    message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone
);

CREATE SEQUENCE warehouse.parser_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE warehouse.parser_run_id_seq OWNED BY warehouse.parser_run.id;

CREATE TABLE warehouse.source_claim (
    id bigint NOT NULL,
    source_document_id bigint NOT NULL,
    claim_type text NOT NULL,
    subject_key text NOT NULL,
    object_key text,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL
);

CREATE SEQUENCE warehouse.source_claim_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE warehouse.source_claim_id_seq OWNED BY warehouse.source_claim.id;

CREATE TABLE warehouse.source_document (
    id bigint NOT NULL,
    source_file_id bigint NOT NULL,
    external_id text,
    payload jsonb NOT NULL,
    imported_at timestamp with time zone DEFAULT now() NOT NULL,
    projection_eligible boolean DEFAULT true NOT NULL
);

CREATE SEQUENCE warehouse.source_document_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE warehouse.source_document_id_seq OWNED BY warehouse.source_document.id;

CREATE TABLE warehouse.source_file (
    id bigint NOT NULL,
    source_registry_id bigint NOT NULL,
    local_path text NOT NULL,
    checksum_sha256 text,
    imported_at timestamp with time zone DEFAULT now() NOT NULL,
    snapshot_state text DEFAULT 'active'::text NOT NULL,
    source_version text,
    source_url text,
    retired_at timestamp with time zone,
    retire_reason text,
    CONSTRAINT source_file_snapshot_state_valid CHECK ((snapshot_state = ANY (ARRAY['pending'::text, 'active'::text, 'retired'::text])))
);

CREATE SEQUENCE warehouse.source_file_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE warehouse.source_file_id_seq OWNED BY warehouse.source_file.id;

CREATE TABLE warehouse.source_registry (
    id bigint NOT NULL,
    name text NOT NULL,
    source_kind text NOT NULL,
    version text,
    source_url text,
    license text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE warehouse.source_registry_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE warehouse.source_registry_id_seq OWNED BY warehouse.source_registry.id;

CREATE TABLE warehouse.source_release (
    id bigint NOT NULL,
    source_registry_id bigint NOT NULL,
    version text NOT NULL,
    source_url text NOT NULL,
    archive_path text NOT NULL,
    unpacked_path text NOT NULL,
    checksum_sha256 text NOT NULL,
    downloaded_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE warehouse.source_release_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE warehouse.source_release_id_seq OWNED BY warehouse.source_release.id;

CREATE TABLE zh_layer.zh_example_translation (
    id bigint NOT NULL,
    example_id bigint NOT NULL,
    text_zh text NOT NULL,
    generation_method text NOT NULL,
    generation_version text NOT NULL,
    is_primary boolean DEFAULT false NOT NULL
);

CREATE SEQUENCE zh_layer.zh_example_translation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE zh_layer.zh_example_translation_id_seq OWNED BY zh_layer.zh_example_translation.id;

CREATE TABLE zh_layer.zh_gloss (
    id bigint NOT NULL,
    sense_id bigint NOT NULL,
    gloss_zh text,
    generation_method text NOT NULL,
    generation_version text NOT NULL,
    is_primary boolean DEFAULT false NOT NULL
);

CREATE SEQUENCE zh_layer.zh_gloss_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE zh_layer.zh_gloss_id_seq OWNED BY zh_layer.zh_gloss.id;

CREATE TABLE zh_layer.zh_note (
    id bigint NOT NULL,
    lexeme_id bigint,
    sense_id bigint,
    note_zh text NOT NULL,
    note_kind text NOT NULL,
    generation_method text NOT NULL,
    generation_version text NOT NULL
);

CREATE SEQUENCE zh_layer.zh_note_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE zh_layer.zh_note_id_seq OWNED BY zh_layer.zh_note.id;

CREATE TABLE zh_layer.zh_warning (
    id bigint NOT NULL,
    lexeme_id bigint,
    sense_id bigint,
    warning_zh text NOT NULL,
    warning_kind text NOT NULL,
    generation_method text NOT NULL,
    generation_version text NOT NULL
);

CREATE SEQUENCE zh_layer.zh_warning_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE zh_layer.zh_warning_id_seq OWNED BY zh_layer.zh_warning.id;

ALTER TABLE ONLY lexicon.collocation ALTER COLUMN id SET DEFAULT nextval('lexicon.collocation_id_seq'::regclass);

ALTER TABLE ONLY lexicon.derivation_relation ALTER COLUMN id SET DEFAULT nextval('lexicon.derivation_relation_id_seq'::regclass);

ALTER TABLE ONLY lexicon.example ALTER COLUMN id SET DEFAULT nextval('lexicon.example_id_seq'::regclass);

ALTER TABLE ONLY lexicon.form ALTER COLUMN id SET DEFAULT nextval('lexicon.form_id_seq'::regclass);

ALTER TABLE ONLY lexicon.form_analysis ALTER COLUMN id SET DEFAULT nextval('lexicon.form_analysis_id_seq'::regclass);

ALTER TABLE ONLY lexicon.frequency_signal ALTER COLUMN id SET DEFAULT nextval('lexicon.frequency_signal_id_seq'::regclass);

ALTER TABLE ONLY lexicon.grammar_note ALTER COLUMN id SET DEFAULT nextval('lexicon.grammar_note_id_seq'::regclass);

ALTER TABLE ONLY lexicon.lexeme ALTER COLUMN id SET DEFAULT nextval('lexicon.lexeme_id_seq'::regclass);

ALTER TABLE ONLY lexicon.lexeme_sense ALTER COLUMN id SET DEFAULT nextval('lexicon.lexeme_sense_id_seq'::regclass);

ALTER TABLE ONLY lexicon.lexical_relation ALTER COLUMN id SET DEFAULT nextval('lexicon.lexical_relation_id_seq'::regclass);

ALTER TABLE ONLY lexicon.pronunciation ALTER COLUMN id SET DEFAULT nextval('lexicon.pronunciation_id_seq'::regclass);

ALTER TABLE ONLY lexicon.sense_example ALTER COLUMN id SET DEFAULT nextval('lexicon.sense_example_id_seq'::regclass);

ALTER TABLE ONLY lexicon.usage_warning ALTER COLUMN id SET DEFAULT nextval('lexicon.usage_warning_id_seq'::regclass);

ALTER TABLE ONLY semantic.sense_alignment ALTER COLUMN id SET DEFAULT nextval('semantic.sense_alignment_id_seq'::regclass);

ALTER TABLE ONLY semantic.sense_alignment_candidate ALTER COLUMN id SET DEFAULT nextval('semantic.sense_alignment_candidate_id_seq'::regclass);

ALTER TABLE ONLY semantic.zh_gloss_candidate ALTER COLUMN id SET DEFAULT nextval('semantic.zh_gloss_candidate_id_seq'::regclass);

ALTER TABLE ONLY warehouse.build_run ALTER COLUMN id SET DEFAULT nextval('warehouse.build_run_id_seq'::regclass);

ALTER TABLE ONLY warehouse.parser_run ALTER COLUMN id SET DEFAULT nextval('warehouse.parser_run_id_seq'::regclass);

ALTER TABLE ONLY warehouse.source_claim ALTER COLUMN id SET DEFAULT nextval('warehouse.source_claim_id_seq'::regclass);

ALTER TABLE ONLY warehouse.source_document ALTER COLUMN id SET DEFAULT nextval('warehouse.source_document_id_seq'::regclass);

ALTER TABLE ONLY warehouse.source_file ALTER COLUMN id SET DEFAULT nextval('warehouse.source_file_id_seq'::regclass);

ALTER TABLE ONLY warehouse.source_registry ALTER COLUMN id SET DEFAULT nextval('warehouse.source_registry_id_seq'::regclass);

ALTER TABLE ONLY warehouse.source_release ALTER COLUMN id SET DEFAULT nextval('warehouse.source_release_id_seq'::regclass);

ALTER TABLE ONLY zh_layer.zh_example_translation ALTER COLUMN id SET DEFAULT nextval('zh_layer.zh_example_translation_id_seq'::regclass);

ALTER TABLE ONLY zh_layer.zh_gloss ALTER COLUMN id SET DEFAULT nextval('zh_layer.zh_gloss_id_seq'::regclass);

ALTER TABLE ONLY zh_layer.zh_note ALTER COLUMN id SET DEFAULT nextval('zh_layer.zh_note_id_seq'::regclass);

ALTER TABLE ONLY zh_layer.zh_warning ALTER COLUMN id SET DEFAULT nextval('zh_layer.zh_warning_id_seq'::regclass);

ALTER TABLE ONLY lexicon.collocation
    ADD CONSTRAINT collocation_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.derivation_relation
    ADD CONSTRAINT derivation_relation_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.derivation_relation_source
    ADD CONSTRAINT derivation_relation_source_pkey PRIMARY KEY (relation_id, source_file_id);

ALTER TABLE ONLY lexicon.example_morphology_validation
    ADD CONSTRAINT example_morphology_validation_pkey PRIMARY KEY (example_id);

ALTER TABLE ONLY lexicon.example
    ADD CONSTRAINT example_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.form_analysis
    ADD CONSTRAINT form_analysis_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.form
    ADD CONSTRAINT form_lexeme_id_normalized_form_form_kind_features_key UNIQUE (lexeme_id, normalized_form, form_kind, features);

ALTER TABLE ONLY lexicon.form
    ADD CONSTRAINT form_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.form_source
    ADD CONSTRAINT form_source_pkey PRIMARY KEY (form_id, source_file_id);

ALTER TABLE ONLY lexicon.form_validation
    ADD CONSTRAINT form_validation_pkey PRIMARY KEY (form_id);

ALTER TABLE ONLY lexicon.frequency_signal
    ADD CONSTRAINT frequency_signal_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.grammar_note
    ADD CONSTRAINT grammar_note_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.grammar_note_source
    ADD CONSTRAINT grammar_note_source_pkey PRIMARY KEY (grammar_note_id, source_file_id);

ALTER TABLE ONLY lexicon.lexeme
    ADD CONSTRAINT lexeme_lemma_part_of_speech_key UNIQUE (lemma, part_of_speech);

ALTER TABLE ONLY lexicon.lexeme
    ADD CONSTRAINT lexeme_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.lexeme_sense
    ADD CONSTRAINT lexeme_sense_lexeme_id_sense_key_key UNIQUE (lexeme_id, sense_key);

ALTER TABLE ONLY lexicon.lexeme_sense
    ADD CONSTRAINT lexeme_sense_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.lexical_relation
    ADD CONSTRAINT lexical_relation_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.lexical_relation_source
    ADD CONSTRAINT lexical_relation_source_pkey PRIMARY KEY (relation_id, source_file_id);

ALTER TABLE ONLY lexicon.pronunciation
    ADD CONSTRAINT pronunciation_lexeme_id_ipa_key UNIQUE (lexeme_id, ipa);

ALTER TABLE ONLY lexicon.pronunciation
    ADD CONSTRAINT pronunciation_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.pronunciation_source
    ADD CONSTRAINT pronunciation_source_pkey PRIMARY KEY (pronunciation_id, source_file_id);

ALTER TABLE ONLY lexicon.sense_example
    ADD CONSTRAINT sense_example_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.sense_example
    ADD CONSTRAINT sense_example_sense_id_example_id_key UNIQUE (sense_id, example_id);

ALTER TABLE ONLY lexicon.sense_source
    ADD CONSTRAINT sense_source_pkey PRIMARY KEY (sense_id, source_file_id);

ALTER TABLE ONLY lexicon.usage_warning
    ADD CONSTRAINT usage_warning_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.usage_warning_source
    ADD CONSTRAINT usage_warning_source_pkey PRIMARY KEY (usage_warning_id, source_file_id);

ALTER TABLE ONLY semantic.sense_alignment_candidate
    ADD CONSTRAINT sense_alignment_candidate_pkey PRIMARY KEY (id);

ALTER TABLE ONLY semantic.sense_alignment_candidate
    ADD CONSTRAINT sense_alignment_candidate_source_name_source_document_id_ta_key UNIQUE (source_name, source_document_id, target_sense_id, candidate_kind);

ALTER TABLE ONLY semantic.sense_alignment
    ADD CONSTRAINT sense_alignment_pkey PRIMARY KEY (id);

ALTER TABLE ONLY semantic.sense_alignment
    ADD CONSTRAINT sense_alignment_source_name_source_document_id_target_sense_key UNIQUE (source_name, source_document_id, target_sense_id);

ALTER TABLE ONLY semantic.zh_gloss_candidate
    ADD CONSTRAINT zh_gloss_candidate_pkey PRIMARY KEY (id);

ALTER TABLE ONLY semantic.zh_gloss_candidate
    ADD CONSTRAINT zh_gloss_candidate_target_sense_id_source_name_source_docum_key UNIQUE (target_sense_id, source_name, source_document_id, gloss_zh);

ALTER TABLE ONLY semantic.zh_gloss_selection
    ADD CONSTRAINT zh_gloss_selection_pkey PRIMARY KEY (target_sense_id);

ALTER TABLE ONLY warehouse.build_run
    ADD CONSTRAINT build_run_pkey PRIMARY KEY (id);

ALTER TABLE ONLY warehouse.parser_run
    ADD CONSTRAINT parser_run_pkey PRIMARY KEY (id);

ALTER TABLE ONLY warehouse.source_claim
    ADD CONSTRAINT source_claim_pkey PRIMARY KEY (id);

ALTER TABLE ONLY warehouse.source_document
    ADD CONSTRAINT source_document_pkey PRIMARY KEY (id);

ALTER TABLE ONLY warehouse.source_file
    ADD CONSTRAINT source_file_pkey PRIMARY KEY (id);

ALTER TABLE ONLY warehouse.source_registry
    ADD CONSTRAINT source_registry_name_key UNIQUE (name);

ALTER TABLE ONLY warehouse.source_registry
    ADD CONSTRAINT source_registry_pkey PRIMARY KEY (id);

ALTER TABLE ONLY warehouse.source_release
    ADD CONSTRAINT source_release_pkey PRIMARY KEY (id);

ALTER TABLE ONLY warehouse.source_release
    ADD CONSTRAINT source_release_source_registry_id_version_key UNIQUE (source_registry_id, version);

ALTER TABLE ONLY zh_layer.zh_example_translation
    ADD CONSTRAINT zh_example_translation_pkey PRIMARY KEY (id);

ALTER TABLE ONLY zh_layer.zh_gloss
    ADD CONSTRAINT zh_gloss_pkey PRIMARY KEY (id);

ALTER TABLE ONLY zh_layer.zh_note
    ADD CONSTRAINT zh_note_pkey PRIMARY KEY (id);

ALTER TABLE ONLY zh_layer.zh_warning
    ADD CONSTRAINT zh_warning_pkey PRIMARY KEY (id);

CREATE INDEX idx_collocation_lexeme_id ON lexicon.collocation USING btree (lexeme_id);

CREATE INDEX idx_collocation_sense_score_id ON lexicon.collocation USING btree (sense_id, score DESC, id);

CREATE INDEX idx_derivation_relation_parent_child ON lexicon.derivation_relation USING btree (parent_lexeme_id, child_lexeme_id);

CREATE INDEX idx_derivation_relation_source_file ON lexicon.derivation_relation_source USING btree (source_file_id, relation_id);

CREATE UNIQUE INDEX idx_derivation_relation_unique ON lexicon.derivation_relation USING btree (parent_lexeme_id, child_lexeme_id, relation_type, note);

CREATE INDEX idx_example_morphology_validation_unknown_tokens ON lexicon.example_morphology_validation USING gin (unknown_tokens);

CREATE INDEX idx_example_morphology_validation_verdict ON lexicon.example_morphology_validation USING btree (verdict, unknown_count DESC, example_id);

CREATE INDEX idx_example_morphology_validation_version ON lexicon.example_morphology_validation USING btree (recognizer_version);

CREATE INDEX idx_example_source_label ON lexicon.example USING btree (source_label);

CREATE INDEX idx_example_source_label_text_fi_id ON lexicon.example USING btree (source_label, text_fi, id);

CREATE INDEX idx_form_analysis_lexeme_id ON lexicon.form_analysis USING btree (lexeme_id);

CREATE INDEX idx_form_analysis_query_lexeme_rank ON lexicon.form_analysis USING btree (normalized_query, lexeme_id, analysis_rank);

CREATE INDEX idx_form_analysis_query_rank ON lexicon.form_analysis USING btree (normalized_query, analysis_rank);

CREATE INDEX idx_form_normalized ON lexicon.form USING btree (normalized_form);

CREATE INDEX idx_form_source_source_file ON lexicon.form_source USING btree (source_file_id, form_id);

CREATE INDEX idx_form_validation_verdict ON lexicon.form_validation USING btree (verdict, form_id);

CREATE INDEX idx_frequency_signal_lexeme_id ON lexicon.frequency_signal USING btree (lexeme_id);

CREATE INDEX idx_grammar_note_lexeme_id ON lexicon.grammar_note USING btree (lexeme_id) WHERE (lexeme_id IS NOT NULL);

CREATE UNIQUE INDEX idx_grammar_note_lexeme_unique ON lexicon.grammar_note USING btree (lexeme_id, note_kind, note_en) WHERE ((sense_id IS NULL) AND (note_en IS NOT NULL));

CREATE UNIQUE INDEX idx_grammar_note_sense_unique ON lexicon.grammar_note USING btree (sense_id, note_kind, note_en) WHERE ((lexeme_id IS NULL) AND (note_en IS NOT NULL));

CREATE INDEX idx_grammar_note_source_file ON lexicon.grammar_note_source USING btree (source_file_id, grammar_note_id);

CREATE INDEX idx_lexeme_lemma ON lexicon.lexeme USING btree (lemma);

CREATE INDEX idx_lexeme_lemma_trgm ON lexicon.lexeme USING gin (lemma public.gin_trgm_ops);

CREATE INDEX idx_lexeme_lemma_unaccent ON lexicon.lexeme USING btree (lexicon.immutable_unaccent(lemma));

CREATE INDEX idx_lexeme_lower_lemma ON lexicon.lexeme USING btree (lower(lemma));

CREATE INDEX idx_lexical_relation_source_file ON lexicon.lexical_relation_source USING btree (source_file_id, relation_id);

CREATE INDEX idx_lexical_relation_source_relation ON lexicon.lexical_relation_source USING btree (relation_id);

CREATE INDEX idx_lexical_relation_source_type_target ON lexicon.lexical_relation USING btree (source_lexeme_id, relation_type, target_lexeme_id);

CREATE INDEX idx_pronunciation_source_file ON lexicon.pronunciation_source USING btree (source_file_id, pronunciation_id);

CREATE INDEX idx_sense_example_example_id ON lexicon.sense_example USING btree (example_id);

CREATE INDEX idx_sense_source_sense ON lexicon.sense_source USING btree (sense_id);

CREATE INDEX idx_sense_source_source_file ON lexicon.sense_source USING btree (source_file_id, sense_id);

CREATE INDEX idx_usage_warning_lexeme_id ON lexicon.usage_warning USING btree (lexeme_id) WHERE (lexeme_id IS NOT NULL);

CREATE UNIQUE INDEX idx_usage_warning_sense_unique ON lexicon.usage_warning USING btree (sense_id, warning_kind, warning_en) WHERE ((lexeme_id IS NULL) AND (warning_en IS NOT NULL));

CREATE INDEX idx_usage_warning_source_file ON lexicon.usage_warning_source USING btree (source_file_id, usage_warning_id);

CREATE INDEX idx_semantic_sense_alignment_candidate_source_document ON semantic.sense_alignment_candidate USING btree (source_document_id);

CREATE INDEX idx_semantic_sense_alignment_source_document ON semantic.sense_alignment USING btree (source_document_id);

CREATE INDEX idx_semantic_zh_gloss_candidate_sense ON semantic.zh_gloss_candidate USING btree (target_sense_id, confidence_score DESC);

CREATE INDEX idx_semantic_zh_gloss_candidate_source_document ON semantic.zh_gloss_candidate USING btree (source_document_id);

CREATE INDEX idx_semantic_zh_gloss_selection_candidate ON semantic.zh_gloss_selection USING btree (zh_gloss_candidate_id);

CREATE INDEX idx_source_claim_document_id ON warehouse.source_claim USING btree (source_document_id);

CREATE INDEX idx_source_document_batch_name ON warehouse.source_document USING btree (((payload ->> 'batch_name'::text))) WHERE (payload ? 'batch_name'::text);

CREATE UNIQUE INDEX idx_source_document_file_external_id ON warehouse.source_document USING btree (source_file_id, external_id);

CREATE UNIQUE INDEX idx_source_file_one_active_per_registry ON warehouse.source_file USING btree (source_registry_id) WHERE (snapshot_state = 'active'::text);

CREATE INDEX idx_source_file_registry_path ON warehouse.source_file USING btree (source_registry_id, local_path, snapshot_state, imported_at DESC);

CREATE INDEX idx_source_file_snapshot_state ON warehouse.source_file USING btree (source_registry_id, snapshot_state, imported_at DESC);

CREATE INDEX idx_zh_example_translation_example_id ON zh_layer.zh_example_translation USING btree (example_id);

CREATE INDEX idx_zh_example_translation_generation_version ON zh_layer.zh_example_translation USING btree (generation_version) WHERE (generation_method = ANY (ARRAY['example-llm'::text, 'human-intervention-example'::text]));

CREATE INDEX idx_zh_example_translation_primary_example_id ON zh_layer.zh_example_translation USING btree (example_id, id) WHERE (is_primary = true);

CREATE INDEX idx_zh_gloss_primary_sense_id ON zh_layer.zh_gloss USING btree (sense_id, id DESC) WHERE (is_primary = true);

CREATE INDEX idx_zh_note_lexeme_kind_id ON zh_layer.zh_note USING btree (lexeme_id, note_kind, id);

CREATE INDEX idx_zh_note_sense_id ON zh_layer.zh_note USING btree (sense_id, id);

CREATE INDEX idx_zh_warning_lexeme_id ON zh_layer.zh_warning USING btree (lexeme_id, id);

CREATE INDEX idx_zh_warning_sense_id ON zh_layer.zh_warning USING btree (sense_id, id);

CREATE UNIQUE INDEX uq_zh_example_translation_one_primary ON zh_layer.zh_example_translation USING btree (example_id) WHERE (is_primary = true);

ALTER TABLE ONLY lexicon.collocation
    ADD CONSTRAINT collocation_lexeme_id_fkey FOREIGN KEY (lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY lexicon.collocation
    ADD CONSTRAINT collocation_sense_id_fkey FOREIGN KEY (sense_id) REFERENCES lexicon.lexeme_sense(id);

ALTER TABLE ONLY lexicon.derivation_relation
    ADD CONSTRAINT derivation_relation_child_lexeme_id_fkey FOREIGN KEY (child_lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY lexicon.derivation_relation
    ADD CONSTRAINT derivation_relation_parent_lexeme_id_fkey FOREIGN KEY (parent_lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY lexicon.derivation_relation_source
    ADD CONSTRAINT derivation_relation_source_relation_id_fkey FOREIGN KEY (relation_id) REFERENCES lexicon.derivation_relation(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.derivation_relation_source
    ADD CONSTRAINT derivation_relation_source_source_file_id_fkey FOREIGN KEY (source_file_id) REFERENCES warehouse.source_file(id);

ALTER TABLE ONLY lexicon.example_morphology_validation
    ADD CONSTRAINT example_morphology_validation_example_id_fkey FOREIGN KEY (example_id) REFERENCES lexicon.example(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.form_analysis
    ADD CONSTRAINT form_analysis_lexeme_id_fkey FOREIGN KEY (lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY lexicon.form
    ADD CONSTRAINT form_lexeme_id_fkey FOREIGN KEY (lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY lexicon.form_source
    ADD CONSTRAINT form_source_form_id_fkey FOREIGN KEY (form_id) REFERENCES lexicon.form(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.form_source
    ADD CONSTRAINT form_source_source_file_id_fkey FOREIGN KEY (source_file_id) REFERENCES warehouse.source_file(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.form_validation
    ADD CONSTRAINT form_validation_form_id_fkey FOREIGN KEY (form_id) REFERENCES lexicon.form(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.frequency_signal
    ADD CONSTRAINT frequency_signal_lexeme_id_fkey FOREIGN KEY (lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY lexicon.grammar_note
    ADD CONSTRAINT grammar_note_lexeme_id_fkey FOREIGN KEY (lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY lexicon.grammar_note
    ADD CONSTRAINT grammar_note_sense_id_fkey FOREIGN KEY (sense_id) REFERENCES lexicon.lexeme_sense(id);

ALTER TABLE ONLY lexicon.grammar_note_source
    ADD CONSTRAINT grammar_note_source_grammar_note_id_fkey FOREIGN KEY (grammar_note_id) REFERENCES lexicon.grammar_note(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.grammar_note_source
    ADD CONSTRAINT grammar_note_source_source_file_id_fkey FOREIGN KEY (source_file_id) REFERENCES warehouse.source_file(id);

ALTER TABLE ONLY lexicon.lexeme_sense
    ADD CONSTRAINT lexeme_sense_lexeme_id_fkey FOREIGN KEY (lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY lexicon.lexical_relation
    ADD CONSTRAINT lexical_relation_source_lexeme_id_fkey FOREIGN KEY (source_lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY lexicon.lexical_relation_source
    ADD CONSTRAINT lexical_relation_source_relation_id_fkey FOREIGN KEY (relation_id) REFERENCES lexicon.lexical_relation(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.lexical_relation_source
    ADD CONSTRAINT lexical_relation_source_source_file_id_fkey FOREIGN KEY (source_file_id) REFERENCES warehouse.source_file(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.lexical_relation
    ADD CONSTRAINT lexical_relation_target_lexeme_id_fkey FOREIGN KEY (target_lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY lexicon.pronunciation
    ADD CONSTRAINT pronunciation_lexeme_id_fkey FOREIGN KEY (lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY lexicon.pronunciation_source
    ADD CONSTRAINT pronunciation_source_pronunciation_id_fkey FOREIGN KEY (pronunciation_id) REFERENCES lexicon.pronunciation(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.pronunciation_source
    ADD CONSTRAINT pronunciation_source_source_file_id_fkey FOREIGN KEY (source_file_id) REFERENCES warehouse.source_file(id);

ALTER TABLE ONLY lexicon.sense_example
    ADD CONSTRAINT sense_example_example_id_fkey FOREIGN KEY (example_id) REFERENCES lexicon.example(id);

ALTER TABLE ONLY lexicon.sense_example
    ADD CONSTRAINT sense_example_sense_id_fkey FOREIGN KEY (sense_id) REFERENCES lexicon.lexeme_sense(id);

ALTER TABLE ONLY lexicon.sense_source
    ADD CONSTRAINT sense_source_sense_id_fkey FOREIGN KEY (sense_id) REFERENCES lexicon.lexeme_sense(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.sense_source
    ADD CONSTRAINT sense_source_source_file_id_fkey FOREIGN KEY (source_file_id) REFERENCES warehouse.source_file(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.usage_warning
    ADD CONSTRAINT usage_warning_lexeme_id_fkey FOREIGN KEY (lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY lexicon.usage_warning
    ADD CONSTRAINT usage_warning_sense_id_fkey FOREIGN KEY (sense_id) REFERENCES lexicon.lexeme_sense(id);

ALTER TABLE ONLY lexicon.usage_warning_source
    ADD CONSTRAINT usage_warning_source_source_file_id_fkey FOREIGN KEY (source_file_id) REFERENCES warehouse.source_file(id);

ALTER TABLE ONLY lexicon.usage_warning_source
    ADD CONSTRAINT usage_warning_source_usage_warning_id_fkey FOREIGN KEY (usage_warning_id) REFERENCES lexicon.usage_warning(id) ON DELETE CASCADE;

ALTER TABLE ONLY semantic.sense_alignment_candidate
    ADD CONSTRAINT sense_alignment_candidate_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES warehouse.source_document(id);

ALTER TABLE ONLY semantic.sense_alignment_candidate
    ADD CONSTRAINT sense_alignment_candidate_target_sense_id_fkey FOREIGN KEY (target_sense_id) REFERENCES lexicon.lexeme_sense(id);

ALTER TABLE ONLY semantic.sense_alignment
    ADD CONSTRAINT sense_alignment_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES warehouse.source_document(id);

ALTER TABLE ONLY semantic.sense_alignment
    ADD CONSTRAINT sense_alignment_target_sense_id_fkey FOREIGN KEY (target_sense_id) REFERENCES lexicon.lexeme_sense(id);

ALTER TABLE ONLY semantic.zh_gloss_candidate
    ADD CONSTRAINT zh_gloss_candidate_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES warehouse.source_document(id);

ALTER TABLE ONLY semantic.zh_gloss_candidate
    ADD CONSTRAINT zh_gloss_candidate_target_sense_id_fkey FOREIGN KEY (target_sense_id) REFERENCES lexicon.lexeme_sense(id);

ALTER TABLE ONLY semantic.zh_gloss_selection
    ADD CONSTRAINT zh_gloss_selection_target_sense_id_fkey FOREIGN KEY (target_sense_id) REFERENCES lexicon.lexeme_sense(id);

ALTER TABLE ONLY semantic.zh_gloss_selection
    ADD CONSTRAINT zh_gloss_selection_zh_gloss_candidate_id_fkey FOREIGN KEY (zh_gloss_candidate_id) REFERENCES semantic.zh_gloss_candidate(id);

ALTER TABLE ONLY warehouse.parser_run
    ADD CONSTRAINT parser_run_build_run_id_fkey FOREIGN KEY (build_run_id) REFERENCES warehouse.build_run(id);

ALTER TABLE ONLY warehouse.parser_run
    ADD CONSTRAINT parser_run_source_registry_id_fkey FOREIGN KEY (source_registry_id) REFERENCES warehouse.source_registry(id);

ALTER TABLE ONLY warehouse.source_claim
    ADD CONSTRAINT source_claim_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES warehouse.source_document(id);

ALTER TABLE ONLY warehouse.source_document
    ADD CONSTRAINT source_document_source_file_id_fkey FOREIGN KEY (source_file_id) REFERENCES warehouse.source_file(id);

ALTER TABLE ONLY warehouse.source_file
    ADD CONSTRAINT source_file_source_registry_id_fkey FOREIGN KEY (source_registry_id) REFERENCES warehouse.source_registry(id);

ALTER TABLE ONLY warehouse.source_release
    ADD CONSTRAINT source_release_source_registry_id_fkey FOREIGN KEY (source_registry_id) REFERENCES warehouse.source_registry(id);

ALTER TABLE ONLY zh_layer.zh_example_translation
    ADD CONSTRAINT zh_example_translation_example_id_fkey FOREIGN KEY (example_id) REFERENCES lexicon.example(id);

ALTER TABLE ONLY zh_layer.zh_gloss
    ADD CONSTRAINT zh_gloss_sense_id_fkey FOREIGN KEY (sense_id) REFERENCES lexicon.lexeme_sense(id);

ALTER TABLE ONLY zh_layer.zh_note
    ADD CONSTRAINT zh_note_lexeme_id_fkey FOREIGN KEY (lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY zh_layer.zh_note
    ADD CONSTRAINT zh_note_sense_id_fkey FOREIGN KEY (sense_id) REFERENCES lexicon.lexeme_sense(id);

ALTER TABLE ONLY zh_layer.zh_warning
    ADD CONSTRAINT zh_warning_lexeme_id_fkey FOREIGN KEY (lexeme_id) REFERENCES lexicon.lexeme(id);

ALTER TABLE ONLY zh_layer.zh_warning
    ADD CONSTRAINT zh_warning_sense_id_fkey FOREIGN KEY (sense_id) REFERENCES lexicon.lexeme_sense(id);

CREATE TABLE lexicon.lexeme_topic (
    id bigint NOT NULL,
    lexeme_id bigint NOT NULL,
    sense_id bigint,
    topic_id text NOT NULL,
    confidence numeric(6,5) DEFAULT 0.60000 NOT NULL,
    source text NOT NULL,
    source_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT lexeme_topic_confidence_valid CHECK (((confidence >= (0)::numeric) AND (confidence <= (1)::numeric))),
    CONSTRAINT lexeme_topic_status_valid CHECK ((status = ANY (ARRAY['active'::text, 'hidden'::text, 'rejected'::text])))
);

CREATE SEQUENCE lexicon.lexeme_topic_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE lexicon.lexeme_topic_id_seq OWNED BY lexicon.lexeme_topic.id;

CREATE TABLE lexicon.lexeme_topic_source (
    lexeme_topic_id bigint NOT NULL,
    source_file_id bigint NOT NULL
);

CREATE TABLE lexicon.topic_taxonomy (
    id text NOT NULL,
    label_en text NOT NULL,
    label_cn text,
    parent_id text,
    description text DEFAULT ''::text NOT NULL,
    display_order integer DEFAULT 1000 NOT NULL,
    source text DEFAULT 'manual'::text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT topic_taxonomy_status_valid CHECK ((status = ANY (ARRAY['active'::text, 'hidden'::text])))
);

ALTER TABLE ONLY lexicon.lexeme_topic ALTER COLUMN id SET DEFAULT nextval('lexicon.lexeme_topic_id_seq'::regclass);

ALTER TABLE ONLY lexicon.lexeme_topic
    ADD CONSTRAINT lexeme_topic_pkey PRIMARY KEY (id);

ALTER TABLE ONLY lexicon.lexeme_topic_source
    ADD CONSTRAINT lexeme_topic_source_pkey PRIMARY KEY (lexeme_topic_id, source_file_id);

ALTER TABLE ONLY lexicon.topic_taxonomy
    ADD CONSTRAINT topic_taxonomy_pkey PRIMARY KEY (id);

CREATE INDEX idx_lexeme_topic_lexeme_confidence ON lexicon.lexeme_topic USING btree (lexeme_id, status, confidence DESC);

CREATE INDEX idx_lexeme_topic_source_file ON lexicon.lexeme_topic_source USING btree (source_file_id, lexeme_topic_id);

CREATE INDEX idx_lexeme_topic_topic_confidence ON lexicon.lexeme_topic USING btree (topic_id, status, confidence DESC);

CREATE INDEX idx_topic_taxonomy_parent_order ON lexicon.topic_taxonomy USING btree (parent_id, display_order, label_en) WHERE (status = 'active'::text);

CREATE UNIQUE INDEX uq_lexeme_topic_no_sense_source ON lexicon.lexeme_topic USING btree (lexeme_id, topic_id, source) WHERE (sense_id IS NULL);

CREATE UNIQUE INDEX uq_lexeme_topic_sense_source ON lexicon.lexeme_topic USING btree (lexeme_id, sense_id, topic_id, source) WHERE (sense_id IS NOT NULL);

ALTER TABLE ONLY lexicon.lexeme_topic
    ADD CONSTRAINT lexeme_topic_lexeme_id_fkey FOREIGN KEY (lexeme_id) REFERENCES lexicon.lexeme(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.lexeme_topic
    ADD CONSTRAINT lexeme_topic_sense_id_fkey FOREIGN KEY (sense_id) REFERENCES lexicon.lexeme_sense(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.lexeme_topic_source
    ADD CONSTRAINT lexeme_topic_source_lexeme_topic_id_fkey FOREIGN KEY (lexeme_topic_id) REFERENCES lexicon.lexeme_topic(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.lexeme_topic_source
    ADD CONSTRAINT lexeme_topic_source_source_file_id_fkey FOREIGN KEY (source_file_id) REFERENCES warehouse.source_file(id);

ALTER TABLE ONLY lexicon.lexeme_topic
    ADD CONSTRAINT lexeme_topic_topic_id_fkey FOREIGN KEY (topic_id) REFERENCES lexicon.topic_taxonomy(id) ON DELETE CASCADE;

ALTER TABLE ONLY lexicon.topic_taxonomy
    ADD CONSTRAINT topic_taxonomy_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES lexicon.topic_taxonomy(id) ON DELETE SET NULL;
