"""Built-in components. Every module in this package is imported once, by the registry, the first
time anyone asks what exists (registry._load_builtins), so their @register calls run then and not
at import time of rag_core itself."""
