from enum import Enum


class ImageStatus(str, Enum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SEGMENTED = "segmented"

class VersionKind(str, Enum):
    INITIAL = "initial"
    REGENERATE = "regenerate"
    SEMANTIC_EDIT = "semantic_edit"


class JobType(str, Enum):
    INITIAL = "initial"
    REGENERATE = "regenerate"
    SEMANTIC_EDIT = "semantic_edit"
    SAM_SEGMENT = "sam_segment"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
