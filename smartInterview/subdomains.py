from __future__ import annotations


MAIN_HOSTS = {
    'shortlistii.com',
    'www.shortlistii.com',
    '127.0.0.1',
    'localhost',
    'lvh.com',
    'lvh.me',
}

CANDIDATE_HOSTS = {
    'candidate.sshortlistii.com',
    'candidates.shortlistii.com',
    'candidates.lvh.com',
    'candidates.lvh.me',
}

JOB_HOSTS = {
    'jobs.shortlistii.com',
    'jobs.lvh.com',
    'jobs.lvh.me',
}


def normalize_host(host: str) -> str:
    return (host or '').split(':', 1)[0].strip().lower()


def classify_subdomain(host: str) -> str:
    normalized_host = normalize_host(host)
    if normalized_host in CANDIDATE_HOSTS:
        return 'candidates'
    if normalized_host in JOB_HOSTS:
        return 'jobs'
    if normalized_host in MAIN_HOSTS:
        return 'main'
    return 'main'
