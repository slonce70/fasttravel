"""Router registration is done in src.main to keep dependency order
explicit (commands → wizard → deals → destinations → subscribe → profile).
This package marker exists so `from src.handlers.X import router` works.
"""
