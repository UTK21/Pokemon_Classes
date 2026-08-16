from .helpers import format_name


def greet(name: str) -> str:
    """Greet a person by their formatted name."""
    return f"Hello, {format_name(name)}!"


def unused_function():
    """This function should NOT appear in pruned output."""
    return 42


class Config:
    """This class should NOT appear when only greet is requested."""
    debug: bool = False
