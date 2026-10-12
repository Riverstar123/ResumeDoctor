"""Internal errors; M2 owns their HTTP mapping, never this pure module."""


class ScoringError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
