-- Schema enhancements, missing foreign-key indexes, and sequence cache tuning.

ALTER TABLE lexicon.lexeme
    ADD COLUMN IF NOT EXISTS is_lemma boolean DEFAULT true NOT NULL;

ALTER TABLE lexicon.example
    ADD COLUMN IF NOT EXISTS attribution text;

ALTER TABLE zh_layer.zh_example_translation
    ADD COLUMN IF NOT EXISTS is_usable boolean DEFAULT true NOT NULL;

-- Full B-Tree indexes on foreign-key target columns to eliminate sequential
-- scans during lexeme/sense merges, cascades, and orphan pruning.
CREATE INDEX IF NOT EXISTS idx_lexical_relation_target_lexeme_id
    ON lexicon.lexical_relation USING btree (target_lexeme_id);

CREATE INDEX IF NOT EXISTS idx_derivation_relation_child_lexeme_id
    ON lexicon.derivation_relation USING btree (child_lexeme_id);

CREATE INDEX IF NOT EXISTS idx_lexeme_topic_sense_id
    ON lexicon.lexeme_topic USING btree (sense_id);

CREATE INDEX IF NOT EXISTS idx_zh_gloss_sense_id
    ON zh_layer.zh_gloss USING btree (sense_id);

CREATE INDEX IF NOT EXISTS idx_grammar_note_sense_id
    ON lexicon.grammar_note USING btree (sense_id);

CREATE INDEX IF NOT EXISTS idx_usage_warning_sense_id
    ON lexicon.usage_warning USING btree (sense_id);

CREATE INDEX IF NOT EXISTS idx_semantic_sense_alignment_target_sense
    ON semantic.sense_alignment USING btree (target_sense_id);

CREATE INDEX IF NOT EXISTS idx_semantic_sense_alignment_candidate_target_sense
    ON semantic.sense_alignment_candidate USING btree (target_sense_id);

CREATE INDEX IF NOT EXISTS idx_lexeme_canonical_lemma
    ON lexicon.lexeme USING btree (lemma)
    WHERE (is_lemma = true);

-- Increase sequence caches on high-volume tables to reduce catalog contention.
ALTER SEQUENCE lexicon.form_id_seq CACHE 1000;
ALTER SEQUENCE lexicon.form_analysis_id_seq CACHE 1000;
ALTER SEQUENCE lexicon.lexeme_id_seq CACHE 1000;
ALTER SEQUENCE lexicon.lexeme_sense_id_seq CACHE 1000;
ALTER SEQUENCE lexicon.example_id_seq CACHE 1000;
ALTER SEQUENCE lexicon.sense_example_id_seq CACHE 1000;
ALTER SEQUENCE lexicon.lexical_relation_id_seq CACHE 1000;
ALTER SEQUENCE lexicon.derivation_relation_id_seq CACHE 1000;
ALTER SEQUENCE lexicon.pronunciation_id_seq CACHE 1000;
ALTER SEQUENCE warehouse.source_document_id_seq CACHE 1000;
ALTER SEQUENCE warehouse.source_claim_id_seq CACHE 1000;
