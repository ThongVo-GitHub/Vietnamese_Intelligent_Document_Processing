from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4


MEDIA_TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "application/xml": ".xml",
}


@dataclass(frozen=True)
class StoredFile:
    storage_key: str
    sha256: str
    size_bytes: int


def store_file(
    *,
    content: bytes,
    media_type: str,
    dossier_id: UUID,
    upload_dir: Path,
) -> StoredFile:
    try:
        extension = MEDIA_TYPE_EXTENSIONS[media_type]
    except KeyError as exc:
        raise ValueError("Unsupported media type") from exc

    relative_path = Path(str(dossier_id)) / f"{uuid4()}{extension}"
    target_path = upload_dir / relative_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(content)

    return StoredFile(
        storage_key=relative_path.as_posix(),
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
    )