from enum import Enum


class SessionStatus(str, Enum):
    UPLOADED = "UPLOADED"
    STYLE_LOCKED = "STYLE_LOCKED"
    RENDERING = "RENDERING"
    REVIEWING = "REVIEWING"
    EDITING = "EDITING"
    DONE = "DONE"
    FAILED = "FAILED"


class ImageVersionKind(str, Enum):
    FULL_RENDER = "FULL_RENDER"
    LOCAL_EDIT = "LOCAL_EDIT"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
