-- Upstream example text and the evidence that associates it to a definition
-- are independent. Existing Tatoeba links do not record how they were chosen.
CREATE VIEW lexicon.export_example_link AS
SELECT se.sense_id, s.lexeme_id, se.example_id, se.sort_order,
       CASE
           WHEN e.source_label IS DISTINCT FROM 'tatoeba' THEN 'source-sense'
           WHEN EXISTS (
               SELECT 1 FROM lexicon.lexeme_sense other
               WHERE other.lexeme_id = s.lexeme_id AND other.id <> s.id
           ) THEN 'inferred-headword'
           ELSE 'inferred-single-sense'
       END AS match_method
FROM lexicon.sense_example se
JOIN lexicon.lexeme_sense s ON s.id = se.sense_id
JOIN lexicon.example e ON e.id = se.example_id;
