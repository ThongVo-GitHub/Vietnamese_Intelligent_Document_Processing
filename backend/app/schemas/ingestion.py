from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FileUploadResponse(BaseModel):
    dossier_id: UUID
    source_file_id: UUID
    job_id: UUID
    original_name: str
    media_type: str
    size_bytes: int
    sha256: str
    job_status: str


class ProcessingJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dossier_id: UUID
    source_file_id: UUID | None
    job_type: str
    status: str
    current_step: str | None
    progress: int
    attempts: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None