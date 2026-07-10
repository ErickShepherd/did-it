"""did-it — reconcile an AI coding agent's claims against its Claude Code session evidence.

Scaffolding only. See docs/design/did-it.md for the authoritative design. The pipeline is two
separately-measured stages with an end-to-end headline metric:

    transcript.parse  ->  extraction.extract_claims  ->  reconcile.reconcile  ->  report.render

Nothing in this package is implemented yet; public functions raise NotImplementedError.
"""

__version__ = "0.0.0"

from .verdicts import Verdict  # noqa: F401  (public surface; structure only)

__all__ = ["Verdict", "__version__"]
