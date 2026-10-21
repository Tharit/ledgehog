"""What the model is given of an entry (spec §5.9 pass 3, "Limited payload").

The payload restriction and its fingerprint live in `app.core.plugins.model_payload`, the one function core
(settling) and this client share; they are re-exported here, where
`tests/plugins/classifiers/test_llm_payload.py` pins them.
"""

from __future__ import annotations

from app.core.plugins.model_payload import fingerprint_of, payload_fingerprint, payload_of, user_message

__all__ = ["fingerprint_of", "payload_fingerprint", "payload_of", "user_message"]
