from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class S3CompatibleStorage:
    """S3 / Cloudflare R2 backend. Credentials never leave the worker or API process."""

    def __init__(
        self,
        *,
        bucket: str,
        access_key: str,
        secret_key: str,
        endpoint: str,
        region: str = "auto",
        public_base: str = "",
    ) -> None:
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.endpoint = endpoint.rstrip("/")
        self.region = region or "auto"
        self.public_base = public_base.rstrip("/")
        self._types: dict[str, str] = {}
        self._meta: dict[str, dict[str, str]] = {}

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "") -> str:
        headers = {"Content-Type": content_type or "application/octet-stream"}
        self._request("PUT", key, data=data, headers=headers)
        self._types[key] = headers["Content-Type"]
        self._meta[key] = {
            "content_type": headers["Content-Type"],
            "size": str(len(data)),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        return key

    def get_bytes(self, key: str) -> bytes:
        status, body, _headers = self._request("GET", key)
        if status == 404:
            raise KeyError(key)
        return body

    def exists(self, key: str) -> bool:
        status, _body, _headers = self._request("HEAD", key, allow_missing=True)
        return status == 200

    def delete(self, key: str) -> None:
        self._request("DELETE", key, allow_missing=True)

    def url_for(self, key: str) -> str:
        if self.public_base:
            return f"{self.public_base}/{urllib.parse.quote(key)}"
        return self.signed_url(key)

    def signed_url(self, key: str, *, expires_in: int = 3600, method: str = "GET") -> str:
        return self._presign(method.upper(), key, expires_in=expires_in)

    def metadata(self, key: str) -> dict[str, str]:
        return dict(self._meta.get(key) or {})

    def content_type_for(self, key: str) -> str:
        return self._types.get(key, "application/octet-stream")

    def _object_url(self, key: str) -> str:
        encoded = "/".join(urllib.parse.quote(part, safe="") for part in key.split("/"))
        return f"{self.endpoint}/{self.bucket}/{encoded}"

    def _request(
        self,
        method: str,
        key: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        allow_missing: bool = False,
    ) -> tuple[int, bytes, dict[str, str]]:
        url = self._object_url(key)
        now = dt.datetime.now(dt.UTC)
        payload = data or b""
        extra = dict(headers or {})
        signed = self._signed_headers(method, url, payload, extra, now)
        request = urllib.request.Request(
            url, data=data if method != "HEAD" else None, method=method
        )
        for name, value in signed.items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = b"" if method == "HEAD" else response.read()
                return response.status, body, dict(response.headers)
        except urllib.error.HTTPError as exc:
            if allow_missing and exc.code in {404, 404}:
                return exc.code, b"", {}
            if exc.code == 404:
                raise KeyError(key) from exc
            raise

    def _signed_headers(
        self,
        method: str,
        url: str,
        payload: bytes,
        extra: dict[str, str],
        now: dt.datetime,
    ) -> dict[str, str]:
        parsed = urllib.parse.urlparse(url)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(payload).hexdigest()
        headers = {
            "host": parsed.netloc,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
            **{k.lower(): v for k, v in extra.items()},
        }
        signed_header_names = ";".join(sorted(headers))
        canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
        canonical = "\n".join(
            [
                method,
                parsed.path or "/",
                parsed.query,
                canonical_headers,
                signed_header_names,
                payload_hash,
            ]
        )
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            ]
        )
        signature = _hex_signature(self.secret_key, date_stamp, self.region, string_to_sign)
        headers["Authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_header_names}, Signature={signature}"
        )
        restored = {
            self._header_name(name): value for name, value in headers.items() if name != "host"
        }
        restored["Host"] = parsed.netloc
        return restored

    def _presign(self, method: str, key: str, *, expires_in: int) -> str:
        url = self._object_url(key)
        parsed = urllib.parse.urlparse(url)
        now = dt.datetime.now(dt.UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        credential = f"{self.access_key}/{credential_scope}"
        query = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": credential,
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(int(expires_in)),
            "X-Amz-SignedHeaders": "host",
        }
        canonical_query = urllib.parse.urlencode(
            sorted(query.items()), quote_via=urllib.parse.quote
        )
        canonical = "\n".join(
            [
                method,
                parsed.path or "/",
                canonical_query,
                f"host:{parsed.netloc}\n",
                "host",
                "UNSIGNED-PAYLOAD",
            ]
        )
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            ]
        )
        signature = _hex_signature(self.secret_key, date_stamp, self.region, string_to_sign)
        query["X-Amz-Signature"] = signature
        return f"{url}?{urllib.parse.urlencode(query, quote_via=urllib.parse.quote)}"

    @staticmethod
    def _header_name(name: str) -> str:
        return "-".join(part.capitalize() for part in name.split("-"))


class FakeS3Storage:
    """In-memory S3-compatible fake for tests. Never contacts a network."""

    def __init__(self, *, bucket: str = "videoforge-test") -> None:
        self.bucket = bucket
        self._blobs: dict[str, bytes] = {}
        self._types: dict[str, str] = {}

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "") -> str:
        self._blobs[key] = data
        self._types[key] = content_type or "application/octet-stream"
        return key

    def get_bytes(self, key: str) -> bytes:
        return self._blobs[key]

    def exists(self, key: str) -> bool:
        return key in self._blobs

    def delete(self, key: str) -> None:
        self._blobs.pop(key, None)
        self._types.pop(key, None)

    def url_for(self, key: str) -> str:
        return self.signed_url(key)

    def signed_url(self, key: str, *, expires_in: int = 3600, method: str = "GET") -> str:
        return f"https://signed.example/{self.bucket}/{key}?exp={expires_in}&m={method}"

    def metadata(self, key: str) -> dict[str, str]:
        data = self._blobs[key]
        return {
            "content_type": self._types.get(key, "application/octet-stream"),
            "size": str(len(data)),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def content_type_for(self, key: str) -> str:
        return self._types.get(key, "application/octet-stream")


def _hex_signature(secret: str, date_stamp: str, region: str, string_to_sign: str) -> str:
    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = _sign(("AWS4" + secret).encode("utf-8"), date_stamp)
    k_region = hmac.new(k_date, region.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
    return hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()


def storage_signed_url(storage: Any, key: str, *, expires_in: int = 3600) -> str | None:
    signer = getattr(storage, "signed_url", None)
    if callable(signer):
        return str(signer(key, expires_in=expires_in))
    return None
