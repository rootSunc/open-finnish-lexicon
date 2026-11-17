"""CLI command dispatchers grouped by domain."""

from open_finnish_lexicon.cli.commands.build import dispatch as dispatch_build
from open_finnish_lexicon.cli.commands.export import dispatch as dispatch_export
from open_finnish_lexicon.cli.commands.ingest import dispatch as dispatch_ingest
from open_finnish_lexicon.cli.commands.morphology import dispatch as dispatch_morphology
from open_finnish_lexicon.cli.commands.normalize import dispatch as dispatch_normalize
from open_finnish_lexicon.cli.commands.quality import dispatch as dispatch_quality

DISPATCHERS = [
    dispatch_build,
    dispatch_ingest,
    dispatch_normalize,
    dispatch_morphology,
    dispatch_quality,
    dispatch_export,
]
