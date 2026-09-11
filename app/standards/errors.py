"""Actionable errors at normative data and analyzer boundaries."""


class NormativeValidationError(ValueError):
    """Invalid entity, file or cross-reference."""


class NormativeLookupError(LookupError):
    """Requested normative entity does not exist."""
