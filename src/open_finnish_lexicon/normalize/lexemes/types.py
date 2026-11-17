from dataclasses import dataclass

LEXEME_DELETE_BATCH_SIZE = 250


@dataclass(frozen=True)
class ReconcileStats:
    normalized_merge_count: int
    surface_form_alignment_count: int
    pruned_or_merged_shell_count: int
    pass_count: int


def normalize_part_of_speech(value: str) -> str:
    return value.strip().casefold()
