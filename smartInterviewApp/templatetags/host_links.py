from django import template


register = template.Library()


FALLBACK_PATHS = {
    "home": "/",
    "jobs": "/jobs/",
    "candidates": "/candidates/",
    "candidate_login": "/candidates/login/",
    "candidate_signup": "/candidates/signup/",
    "litio": "/",
    "marketing_candidate_login": "/",
    "marketing_jobs": "/",
}

LOCAL_HOSTS = {"127.0.0.1", "localhost"}
KNOWN_BASE_HOSTS = ("shortlistii.com", "lvh.me", "lvh.com")
TARGET_SUBDOMAINS = {
    "home": "",
    "jobs": "jobs",
    "candidates": "candidates",
    "candidate_login": "candidates",
    "candidate_signup": "candidates",
    "litio": "litio",
    "marketing_candidate_login": "candidates",
    "marketing_jobs": "jobs",
}
TARGET_PATHS = {
    "home": "/",
    "jobs": "/",
    "candidates": "/",
    "candidate_login": "/",
    "candidate_signup": "/signup/",
    "litio": "/",
    "marketing_candidate_login": "/",
    "marketing_jobs": "/",
}


def _split_host_port(host_value: str) -> tuple[str, str]:
    raw = (host_value or "").strip()
    if ":" in raw:
        host, port = raw.rsplit(":", 1)
        if port.isdigit():
            return host.lower(), port
    return raw.lower(), ""


def _build_absolute_url(request, host: str, path: str = "/") -> str:
    scheme = "https" if request.is_secure() else "http"
    current_host, current_port = _split_host_port(request.get_host())
    port = f":{current_port}" if current_port else ""
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{scheme}://{host}{port}{normalized_path}"


def _resolve_base_host(host: str) -> str:
    normalized = (host or "").strip().lower()
    if not normalized:
        return normalized
    if normalized in LOCAL_HOSTS:
        return normalized
    if normalized == "www.shortlistii.com":
        return "shortlistii.com"
    if normalized == "candidate.sshortlistii.com":
        return "shortlistii.com"

    for candidate in KNOWN_BASE_HOSTS:
        if normalized == candidate or normalized.endswith(f".{candidate}"):
            return candidate

    labels = [label for label in normalized.split(".") if label]
    if len(labels) >= 2:
        return ".".join(labels[-2:])
    return normalized


def _build_target_host(base_host: str, destination: str) -> str:
    subdomain = TARGET_SUBDOMAINS.get(destination, "")
    if not subdomain or not base_host:
        return base_host
    return f"{subdomain}.{base_host}"


def build_host_link(request, destination: str) -> str:
    if not hasattr(request, "get_host"):
        return FALLBACK_PATHS.get(destination, "/")

    host, _port = _split_host_port(request.get_host())
    base_host = _resolve_base_host(host)

    if base_host in LOCAL_HOSTS:
        return _build_absolute_url(request, base_host, FALLBACK_PATHS.get(destination, "/"))

    return _build_absolute_url(
        request,
        _build_target_host(base_host, destination),
        TARGET_PATHS.get(destination, "/"),
    )


@register.simple_tag
def host_link(request, destination: str) -> str:
    return build_host_link(request, destination)
