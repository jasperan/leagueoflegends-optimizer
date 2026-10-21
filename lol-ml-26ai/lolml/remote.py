"""Read a member of a remote ZIP file with HTTP range requests (anonymous, standard library only).

The public Kaggle download URL redirects to a signed Google Cloud Storage URL. The zip directory
sits at the end of the file, so we can pull just the members we need instead of the whole archive.
"""
from __future__ import annotations

import io
import time
import urllib.error
import urllib.request
import zipfile

KAGGLE_URL = "https://www.kaggle.com/api/v1/datasets/download/{owner}/{dataset}"


class HTTPRangeFile(io.RawIOBase):
    def __init__(self, url: str, retries: int = 4):
        self.retries = retries
        req = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            cr = r.headers.get("Content-Range")
            self.size = int(cr.split("/")[-1]) if cr else int(r.headers["Content-Length"])
            self.url = r.geturl()  # signed URL, so the redirect is not repeated
        self.pos = 0

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, off: int, whence: int = 0) -> int:
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def readinto(self, b) -> int:
        if self.pos >= self.size:
            return 0
        end = min(self.pos + len(b), self.size) - 1
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == self.retries - 1:
                    raise
                time.sleep(2 ** attempt)
        b[: len(data)] = data
        self.pos += len(data)
        return len(data)


def open_remote_zip(owner: str, dataset: str) -> zipfile.ZipFile:
    raw = HTTPRangeFile(KAGGLE_URL.format(owner=owner, dataset=dataset))
    return zipfile.ZipFile(io.BufferedReader(raw, buffer_size=8 << 20))
