"""Grounded NPC dialogue (ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1).

    conversation context -> speech act -> proposition -> grounding validator
    -> surface renderer -> listener cognition (receive_fact) -> memory /
    belief / relationship / goal / WorkRuntime help task

* :mod:`acts`      — the speech-act grammar, propositions, requests
* :mod:`grounding` — retrieval and the validator over ONE citizen's store
* :mod:`render`    — the deterministic surface renderer
* :mod:`session`   — bounded persistent conversation sessions
* :mod:`runtime`   — :class:`DialogueRuntime`, the one owner of conversations
"""
from .runtime import DialogueRuntime, DIALOGUE_SCHEMA_VERSION   # noqa: F401
from .acts import Proposition, Request                          # noqa: F401
from .session import Conversation                               # noqa: F401
