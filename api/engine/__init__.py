"""FrameFusion production engine: agents, media services, and schemas.

This package is framework-free. The Django apps call into it and install the
per-request LLM resolver and job runtime (see ``engine.llm`` and
``engine.runtime``).
"""
