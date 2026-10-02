class DomainError(Exception):
    status_code = 400


class AuthenticationRequired(DomainError):
    status_code = 401


class PermissionDenied(DomainError):
    status_code = 403


class InvalidCredentials(DomainError):
    status_code = 401


class SeedConflict(DomainError):
    status_code = 409


class NotFound(DomainError):
    status_code = 404


class VersionConflict(DomainError):
    status_code = 409


class InputError(DomainError):
    status_code = 422

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
