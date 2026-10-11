"""No proxy, no redirects, validate every DNS answer and connect to that exact IP."""

import http.client
import ipaddress
import json
import re
import socket
import ssl
from urllib.parse import urlsplit, urlunsplit

from app.core.config import settings


class ProviderError(Exception):
    def __init__(self, code: str, status: int | None = None):
        self.code, self.status = code, status
        super().__init__(code)


def normalize_url(value: str) -> str:
    try:
        if not value or re.search(r"[\s\\%]", value):
            raise ValueError
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme not in {"https", "http"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "?" in value
            or "#" in value
        ):
            raise ValueError
        host = host.encode("idna").decode().lower()
        if host.endswith("."):
            host = host[:-1]
        if not re.fullmatch(r"[a-z0-9.:-]+", host):
            raise ValueError
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError
        path = parsed.path.rstrip("/")
        if (
            not re.fullmatch(r"(?:/[A-Za-z0-9_.~-]+)*", path)
            or any(p in {".", ".."} for p in path.split("/"))
            or path.endswith(("/chat/completions", "/responses", "/completions"))
        ):
            raise ValueError
        authority = f"[{host}]" if ":" in host else host
        if port != (443 if parsed.scheme == "https" else 80):
            authority += f":{port}"
        return urlunsplit((parsed.scheme, authority, path, "", ""))
    except (ValueError, UnicodeError):
        raise ProviderError("INVALID_BASE_URL") from None


def allowed(url: str) -> bool:
    origin = urlsplit(url)
    target = f"{origin.scheme}://{origin.netloc}"
    return any(normalize_url(entry) == target for entry in settings().model_allowed_origins)


def validate_target(url: str) -> list[tuple]:
    parsed = urlsplit(normalize_url(url))
    exception = allowed(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not exception and (parsed.scheme != "https" or port != 443):
        raise ProviderError("EGRESS_BLOCKED")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except OSError:
        raise ProviderError("DNS_FAILED") from None
    if not addresses:
        raise ProviderError("DNS_FAILED")
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        # Deny transition/translation networks as well as private/reserved destinations.
        transition = isinstance(ip, ipaddress.IPv6Address) and (
            ip.sixtofour is not None
            or ip.teredo is not None
            or ip in ipaddress.ip_network("64:ff9b::/96")
            or ip in ipaddress.ip_network("64:ff9b:1::/48")
        )
        if not exception and (not ip.is_global or ip.is_multicast or ip.is_reserved or transition):
            raise ProviderError("EGRESS_BLOCKED")
    return addresses


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, secure, timeout):
        super().__init__(host, port, timeout=timeout)
        self.address, self.secure = address, secure

    def connect(self):
        family, kind, protocol, _, sockaddr = self.address
        sock = socket.socket(family, kind, protocol)
        try:
            sock.settimeout(self.timeout)
            sock.connect(sockaddr)  # No second DNS resolution (including redirects/proxies).
            if self.secure:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
            self.sock = sock
        except Exception:
            sock.close()
            raise


def post(url: str, key: str, payload: dict, timeout: float) -> dict:
    url = normalize_url(url)
    parsed = urlsplit(url)
    addresses = validate_target(url)
    connection = PinnedConnection(
        parsed.hostname,
        parsed.port or (443 if parsed.scheme == "https" else 80),
        addresses[0],
        parsed.scheme == "https",
        timeout,
    )
    try:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        connection.request(
            "POST", parsed.path + "/chat/completions", json.dumps(payload).encode(), headers
        )
        response = connection.getresponse()
        status = response.status
        if 300 <= status < 400:
            raise ProviderError("REDIRECT_BLOCKED", status)
        if status != 200:
            code = {
                401: "AUTH_FAILED",
                403: "AUTH_FAILED",
                404: "MODEL_NOT_FOUND",
                429: "RATE_LIMITED",
                400: "UNSUPPORTED_REQUEST",
                422: "UNSUPPORTED_REQUEST",
            }.get(status, "PROVIDER_UNAVAILABLE" if status >= 500 else "PROVIDER_REJECTED")
            raise ProviderError(code, status)  # Never retain upstream error bodies.
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ProviderError("RESPONSE_TOO_LARGE")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ProviderError("INVALID_RESPONSE")
        return result
    except ProviderError:
        raise
    except TimeoutError:
        raise ProviderError("TIMEOUT") from None
    except ssl.SSLError:
        raise ProviderError("TLS_FAILED") from None
    except (ValueError, UnicodeError, RecursionError):
        raise ProviderError("INVALID_RESPONSE") from None
    except (OSError, http.client.HTTPException):
        raise ProviderError("NETWORK_ERROR") from None
    finally:
        connection.close()
