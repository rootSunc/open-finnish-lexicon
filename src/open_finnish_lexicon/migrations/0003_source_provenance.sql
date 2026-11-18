alter table warehouse.source_file
    add column assets jsonb not null default '[]'::jsonb;

alter table lexicon.example
    add column provenance jsonb;

update warehouse.source_registry
set license = 'CC-BY-SA-4.0'
where name = 'dbnary_zh' and license = 'CC-BY-SA-3.0';

update warehouse.source_registry
set license = 'LicenseRef-Chinese-Open-Wordnet'
where name = 'omw_zh' and license = 'WordNet';
