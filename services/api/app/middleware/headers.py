"""Header decoding shared by the ASGI middleware.

Raw ASGI headers are a list of byte pairs with duplicates allowed and no case normalisation. Every
middleware here needs the same lower-cased mapping, and three near-identical comprehensions is
three places for the normalisation to drift.
"""

from __future__ import annotations

from starlette.types import Scope


def decode_headers(scope: Scope) -> dict[str, str]:
    """Lower-cased header mapping for one request.

    latin-1 is the encoding HTTP headers are defined in; it also cannot raise, so a header with
    unexpected bytes degrades to mojibake rather than throwing inside a middleware where there is
    no handler to catch it. A repeated header keeps its last value, which is what the headers this
    service reads (`x-request-id`, `content-length`, `x-forwarded-for`) expect.
    """
    return {
        key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]
    }
