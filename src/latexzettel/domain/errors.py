class DomainError(Exception):
    """Error genérico de dominio para el API."""


class NoteAlreadyExists(DomainError):
    pass


class ReferenceAlreadyExists(DomainError):
    pass


class NoteNotFound(DomainError):
    pass


class DocumentsTexNotFound(DomainError):
    pass


class TemplateNotFound(DomainError):
    pass
