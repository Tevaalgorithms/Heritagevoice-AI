"""Audio storage: a local folder for development, private encrypted S3 for deployment."""

import re
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*")
MAX_KEY_LENGTH = 200
S3_CONFIG = Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2})


def check_key(key: str) -> str:
    if len(key) > MAX_KEY_LENGTH or not KEY_PATTERN.fullmatch(key):
        raise ValueError("Invalid storage key")
    return key


class LocalAudioStore:
    """Development only. Keep the folder inside the git-ignored `data/` directory."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self._root / check_key(key)).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError("Invalid storage key")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3AudioStore:
    """Private bucket, objects encrypted with KMS. Access is only through presigned URLs."""

    def __init__(
        self, bucket: str, kms_key_id: str | None = None, client: Any | None = None
    ) -> None:
        self._bucket = bucket
        self._kms_key_id = kms_key_id
        self._client = client or boto3.client("s3", config=S3_CONFIG)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        extra = {"SSEKMSKeyId": self._kms_key_id} if self._kms_key_id else {}
        self._client.put_object(
            Bucket=self._bucket,
            Key=check_key(key),
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="aws:kms",
            **extra,
        )

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=check_key(key))
        return bytes(response["Body"].read())

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=check_key(key))
