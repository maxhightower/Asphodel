"""NPC cognition: perception, memory, beliefs, relationships, social actions
(ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1).

    perception -> memory/belief -> evaluation -> CitizenRuntime goal / WorkRuntime
    constraint or help task -> existing execution

* :mod:`memory`        — structured, bounded, provenance-carrying facts
* :mod:`beliefs`       — beliefs derived from evidence (can be wrong)
* :mod:`relationships` — six bounded dimensions per directed pair
* :mod:`personality`   — five deterministic traits that bias decisions
* :mod:`social`        — the social-action grammar and sharing limits
* :mod:`runtime`       — :class:`CognitionRuntime`, the one owner of all of it
"""
from .runtime import CognitionRuntime, COGNITION_SCHEMA_VERSION  # noqa: F401
from .memory import MemoryFact, MemoryStore                       # noqa: F401
from .relationships import Relationship, RelationshipGraph        # noqa: F401
from .personality import Personality, personality_for             # noqa: F401
