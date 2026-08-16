def format_name(s: str) -> str:
    return s.strip().title()


def internal_helper():
    """This should NOT appear in pruned output when only format_name is needed."""
    return "secret"


class StringUtils:
    def upper(self, s: str) -> str:
        return s.upper()

    def lower(self, s: str) -> str:
        return s.lower()
