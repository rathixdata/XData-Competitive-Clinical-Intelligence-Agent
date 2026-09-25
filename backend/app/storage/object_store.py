"""Content-addressed, write-once object storage for raw source artifacts (FR-SRC-008).

Keys are ``<source>/<sha256[:2]>/<sha256>``. Writing an existing key is a no-op, so repeated
fetches of an unchanged payload never create duplicates, and stored bytes can always be verified
against the checksum recorded on SourceDocument.
"""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings


class ObjectStore(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    def put_content_addressed(self, namespace: str, data: bytes, content_type: str) -> tuple[str, str]:
        digest = hashlib.sha256(data).hexdigest()
        key = f"{namespace}/{digest[:2]}/{digest}"
        if not self.exists(key):
            self.put(key, data, content_type)
        return key, digest

    def verify(self, key: str, checksum: str) -> bool:
        return hashlib.sha256(self.get(key)).hexdigest() == checksum


class LocalObjectStore(ObjectStore):
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("invalid key")
        return p

    def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        os.chmod(p, 0o444)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            os.chmod(p, 0o644)
            p.unlink()


class S3ObjectStore(ObjectStore):
    """S3 / S3-compatible store. Production buckets should enable Object Lock (compliance mode)
    and SSE-KMS; ``s3_kms_key_id`` enforces KMS encryption on write."""

    def __init__(self, bucket: str, region: str | None, endpoint_url: str | None, kms_key_id: str | None):
        import boto3

        self.bucket = bucket
        self.kms_key_id = kms_key_id
        self.client = boto3.client("s3", region_name=region, endpoint_url=endpoint_url)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        extra = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.kms_key_id} if self.kms_key_id else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, **extra)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


@lru_cache
def get_object_store() -> ObjectStore:
    s = get_settings()
    if s.object_store_backend == "s3":
        return S3ObjectStore(s.s3_bucket, s.s3_region, s.s3_endpoint_url, s.s3_kms_key_id)
    return LocalObjectStore(s.object_store_local_path)
