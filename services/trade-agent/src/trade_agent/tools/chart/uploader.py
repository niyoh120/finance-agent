import base64
import mimetypes
import os
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import requests


@dataclass
class UploadResult:
    url: str
    provider: str


def _guess_filename_and_mime(filename: str | None) -> Tuple[str, str]:
    name = filename or "image.png"
    mime, _ = mimetypes.guess_type(name)
    return name, (mime or "application/octet-stream")


def upload_imgbb_bytes(
    image_bytes: bytes,
    api_key: str,
    *,
    expiration_sec: int = 600,
    filename: str | None = None,
    timeout: int = 30,
) -> UploadResult:
    """
    ImgBB: supports base64 upload. Can set expiration (seconds).
    Docs: https://api.imgbb.com/
    """
    if not api_key:
        raise ValueError("Missing ImgBB api_key")

    b64 = base64.b64encode(image_bytes).decode("ascii")
    r = requests.post(
        "https://api.imgbb.com/1/upload",
        params={"key": api_key, "expiration": str(expiration_sec)},
        data={"image": b64, "name": (filename or "image")},
        timeout=timeout,
    )
    r.raise_for_status()
    j = r.json()
    url = j["data"]["url"]
    return UploadResult(url=url, provider="imgbb")


def upload_uguu_bytes(
    image_bytes: bytes,
    *,
    filename: str | None = None,
    timeout: int = 30,
) -> UploadResult:
    """
    Uguu: no key required. multipart field is files[]
    Docs: https://uguu.se/api
    """
    fname, mime = _guess_filename_and_mime(filename)
    r = requests.post(
        "https://uguu.se/upload",
        files=[("files[]", (fname, image_bytes, mime))],
        timeout=timeout,
    )
    r.raise_for_status()

    # Typical JSON: {"success":true,"files":[{"url":"..."}]}
    try:
        j = r.json()
        if isinstance(j, dict) and "files" in j and j["files"]:
            f0 = j["files"][0]
            if isinstance(f0, dict):
                url = f0.get("url") or f0.get("file") or f0.get("link")
                if url:
                    return UploadResult(url=url, provider="uguu")
            # fallback if structure changes
            return UploadResult(url=str(f0), provider="uguu")
        # other possible keys
        for k in ("url", "file", "link"):
            if isinstance(j, dict) and j.get(k):
                return UploadResult(url=j[k], provider="uguu")
        return UploadResult(url=str(j), provider="uguu")
    except Exception:
        # Some deployments might return plain text
        return UploadResult(url=r.text.strip(), provider="uguu")


def upload_0x0_bytes(
    image_bytes: bytes,
    *,
    filename: str | None = None,
    timeout: int = 30,
) -> UploadResult:
    """
    0x0.st: multipart field 'file', returns plain-text URL.
    (Unofficial but widely used.)
    """
    fname, mime = _guess_filename_and_mime(filename)
    r = requests.post(
        "https://0x0.st",
        files={"file": (fname, image_bytes, mime)},
        timeout=timeout,
    )
    r.raise_for_status()
    return UploadResult(url=r.text.strip(), provider="0x0.st")


def upload_image_bytes(
    image_bytes: bytes,
    *,
    filename: str | None = None,
    expiration_sec: int = 600,
    imgbb_api_key: str | None = None,
    timeout: int = 30,
) -> UploadResult:
    """
    Unified uploader with fallbacks:
    1) ImgBB (if api key provided) -> supports expiration
    2) Uguu (no key)
    3) 0x0.st (no key)
    """
    providers: list[Callable[[], UploadResult]] = []

    if imgbb_api_key:
        providers.append(
            lambda: upload_imgbb_bytes(
                image_bytes,
                imgbb_api_key,
                expiration_sec=expiration_sec,
                filename=filename,
                timeout=timeout,
            )
        )

    providers.append(
        lambda: upload_uguu_bytes(image_bytes, filename=filename, timeout=timeout)
    )
    providers.append(
        lambda: upload_0x0_bytes(image_bytes, filename=filename, timeout=timeout)
    )

    last_err: Optional[Exception] = None
    for fn in providers:
        try:
            return fn()
        except Exception as e:
            last_err = e

    raise RuntimeError(f"All upload providers failed. Last error: {last_err!r}")


# ---- Example usage ----
# if __name__ == "__main__":
#     # Suppose you already have bytes in memory:
#     # image_bytes = open("x.png","rb").read()
#     image_bytes = b"..."

#     res = upload_image_bytes(
#         image_bytes,
#         filename="ai.png",
#         expiration_sec=600,  # only applies to ImgBB
#         imgbb_api_key=os.getenv("IMGBB_API_KEY"),
#     )
#     print(res.provider, res.url)
