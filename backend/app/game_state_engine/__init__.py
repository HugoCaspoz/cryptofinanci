from .models import GameState, PlayerState

__all__ = ["GameStateEngine", "GameState", "PlayerState"]


def __getattr__(name):
    # Contracts can be imported by the event module without importing vision.
    if name == "GameStateEngine":
        from .engine import GameStateEngine
        return GameStateEngine
    raise AttributeError(name)
