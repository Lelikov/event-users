class NotFoundError(Exception):
    def __init__(self, resource: str, resource_id: int | str) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"{resource} {resource_id!r} not found")


class ConflictError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
