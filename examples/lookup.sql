-- Find the lemma behind an inflected form.
SELECT f.surface_form, l.lemma, l.part_of_speech, f.validation
FROM form f JOIN lexeme l ON l.id = f.lexeme_id
WHERE f.surface_form = 'juoksen';

-- Look up separate senses of a homograph.
SELECT l.lemma, l.part_of_speech, s.gloss_en
FROM lexeme l JOIN sense s ON s.lexeme_id = l.id
WHERE l.lemma = 'kuusi'
ORDER BY l.part_of_speech, s.sort_order;

-- Look up where a sense came from.
SELECT s.gloss_en, ss.source_name, ss.source_entry, src.version
FROM sense s
JOIN sense_source ss ON ss.sense_id = s.id
JOIN sources src ON src.name = ss.source_name
WHERE ss.source_entry = 'juosta';
