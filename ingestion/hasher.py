"""ContractIQ Document Hasher.

Computes canonical SHA-256 hashes of document contents (raw bytes or text buffers)
for immutable tracking across analysis, verification, and memory retention.
"""

import hashlib
from typing import Union


def compute_sha256(content: Union[str, bytes]) -> str:
    """Computes a lowercase hex SHA-256 hash."""
    hasher = hashlib.sha256()
    if isinstance(content, str):
        hasher.update(content.encode("utf-8"))
    else:
        hasher.update(content)
    return hasher.hexdigest()
