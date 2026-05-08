from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 10) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode('utf-8')
    try:
        req = urllib.request.Request(url=url, data=data, headers={**headers, 'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode('utf-8')
            if not body:
                return response.status, {}
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                return response.status, {'raw': body}
    except ValueError as exc:
        return 400, {'error': str(exc)}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8') if hasattr(exc, 'read') else '{}'
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {'raw': body}
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return 503, {'error': str(exc)}


def post_form(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 10) -> tuple[int, dict[str, Any]]:
    encoded = urllib.parse.urlencode(payload).encode('utf-8')
    try:
        req = urllib.request.Request(url=url, data=encoded, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode('utf-8')
            if not body:
                return response.status, {}
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                return response.status, {'raw': body}
    except ValueError as exc:
        return 400, {'error': str(exc)}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8') if hasattr(exc, 'read') else '{}'
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {'raw': body}
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return 503, {'error': str(exc)}


def get_json(url: str, headers: dict[str, str], timeout: int = 10) -> tuple[int, dict[str, Any]]:
    try:
        req = urllib.request.Request(url=url, headers=headers, method='GET')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode('utf-8')
            if not body:
                return response.status, {}
            try:
                parsed = json.loads(body)
                return response.status, parsed if isinstance(parsed, dict) else {'data': parsed}
            except json.JSONDecodeError:
                return response.status, {'raw': body}
    except ValueError as exc:
        return 400, {'error': str(exc)}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8') if hasattr(exc, 'read') else '{}'
        try:
            parsed = json.loads(body) if body else {}
            if not isinstance(parsed, dict):
                parsed = {'data': parsed}
        except json.JSONDecodeError:
            parsed = {'raw': body}
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return 503, {'error': str(exc)}
