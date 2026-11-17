import json
import unicodedata

from open_finnish_lexicon.db import connection_scope
from open_finnish_lexicon.normalize.lexemes import normalize_part_of_speech
from open_finnish_lexicon.sources.omorfi_loader import OmorfiRow


def normalize_surface_form(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def upsert_omorfi_rows(
    rows: list[OmorfiRow],
    *,
    source_file_id: int | None = None,
    replace_snapshot: bool = False,
    connection=None,
) -> None:
    if replace_snapshot and source_file_id is None:
        raise ValueError("replace_snapshot requires an Omorfi source_file_id")
    if not rows:
        if replace_snapshot:
            raise ValueError("refusing to replace Omorfi forms from an empty snapshot")
        return

    owns_connection = connection is None
    with connection_scope(connection) as conn:
        if source_file_id is not None:
            conn.execute(
                """
                create temporary table tmp_omorfi_stale_form (
                    form_id bigint primary key
                ) on commit drop
                """
            )
            if replace_snapshot:
                conn.execute(
                    """
                    insert into tmp_omorfi_stale_form (form_id)
                    select distinct fs.form_id
                    from lexicon.form_source fs
                    join warehouse.source_file sf on sf.id = fs.source_file_id
                    join warehouse.source_registry sr on sr.id = sf.source_registry_id
                    where sr.name = 'omorfi'
                    on conflict do nothing
                    """
                )
                conn.execute(
                    """
                    delete from lexicon.form_source fs
                    using warehouse.source_file sf
                    join warehouse.source_registry sr on sr.id = sf.source_registry_id
                    where fs.source_file_id = sf.id
                      and sr.name = 'omorfi'
                    """,
                )
                conn.execute(
                    """
                    delete from lexicon.form_analysis fa
                    using tmp_omorfi_stale_form stale
                    join lexicon.form f on f.id = stale.form_id
                    where fa.lexeme_id = f.lexeme_id
                      and fa.normalized_query = f.normalized_form
                    """
                )
                conn.execute(
                    """
                    delete from lexicon.form f
                    using tmp_omorfi_stale_form stale
                    where f.id = stale.form_id
                      and not exists (
                          select 1
                          from lexicon.form_source fs
                          where fs.form_id = f.id
                      )
                    """
                )

        conn.execute(
            """
            create temporary table tmp_omorfi_row (
                surface_form text not null,
                normalized_form text not null,
                lemma text not null,
                part_of_speech text not null,
                features jsonb not null,
                analysis_rank integer not null,
                confidence numeric(6, 5) not null
            ) on commit drop
            """
        )

        with conn.cursor() as cursor:
            with cursor.copy(
                """
                copy tmp_omorfi_row (
                    surface_form,
                    normalized_form,
                    lemma,
                    part_of_speech,
                    features,
                    analysis_rank,
                    confidence
                )
                from stdin
                """
            ) as copy:
                for row in rows:
                    copy.write_row(
                        (
                            row.surface_form,
                            normalize_surface_form(row.surface_form),
                            row.lemma,
                            normalize_part_of_speech(row.part_of_speech),
                            json.dumps(row.features, ensure_ascii=False),
                            row.analysis_rank,
                            row.confidence,
                        )
                    )

            cursor.execute(
                """
                insert into lexicon.lexeme (lemma, display_lemma, part_of_speech)
                select distinct lemma, lemma, part_of_speech
                from tmp_omorfi_row
                on conflict (lemma, part_of_speech) do update
                set display_lemma = excluded.display_lemma
                """
            )

            cursor.execute(
                """
                create temporary table tmp_omorfi_resolved as
                select
                    r.surface_form,
                    r.normalized_form,
                    l.id as lexeme_id,
                    r.features,
                    r.analysis_rank,
                    r.confidence
                from tmp_omorfi_row r
                join lexicon.lexeme l
                  on l.lemma = r.lemma
                 and l.part_of_speech = r.part_of_speech
                """
            )

            cursor.execute(
                """
                insert into lexicon.form (lexeme_id, surface_form, normalized_form, form_kind, features)
                select distinct lexeme_id, surface_form, normalized_form, 'omorfi', features
                from tmp_omorfi_resolved
                on conflict do nothing
                """
            )

            if source_file_id is not None:
                cursor.execute(
                    """
                    insert into lexicon.form_source (form_id, source_file_id)
                    select distinct f.id, %s
                    from lexicon.form f
                    join tmp_omorfi_resolved r
                      on r.lexeme_id = f.lexeme_id
                     and r.normalized_form = f.normalized_form
                     and r.features = f.features
                    where f.form_kind = 'omorfi'
                    on conflict do nothing
                    """,
                    (source_file_id,),
                )

            cursor.execute(
                """
                delete from lexicon.form_analysis fa
                using (
                    select distinct normalized_form, lexeme_id
                    from tmp_omorfi_resolved
                ) doomed
                where fa.normalized_query = doomed.normalized_form
                  and fa.lexeme_id = doomed.lexeme_id
                """
            )

            cursor.execute(
                """
                insert into lexicon.form_analysis (normalized_query, lexeme_id, analysis_rank, confidence, features)
                select normalized_form, lexeme_id, analysis_rank, confidence, features
                from (
                    select distinct on (normalized_form, lexeme_id, features)
                        normalized_form,
                        lexeme_id,
                        analysis_rank,
                        confidence,
                        features
                    from tmp_omorfi_resolved
                    order by normalized_form, lexeme_id, features, analysis_rank, confidence desc
                ) deduped
                """,
            )
        if owns_connection:
            conn.commit()
