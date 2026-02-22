from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


@dataclass
class GitHubAPIError(Exception):
    status_code: int
    message: str
    response_text: str | None = None


class GitHubClient:
    def __init__(self, *, token: str, api_base: str, timeout: float = 10.0, retries: int = 2):
        self._client = httpx.Client(
            base_url=api_base,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "review-bot",
            },
            timeout=timeout,
        )
        self._retries = retries

    def get_pull(self, *, owner: str, repo: str, pr_number: int) -> dict:
        response = self._request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}")
        return self._json_or_error(response)

    def list_pull_files(self, *, owner: str, repo: str, pr_number: int) -> list[dict]:
        files: list[dict] = []
        page = 1
        while True:
            response = self._request(
                "GET",
                f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
                params={"per_page": 100, "page": page},
            )
            data = self._json_or_error(response)
            if not data:
                break
            files.extend(data)
            if len(data) < 100:
                break
            page += 1
        return files

    def create_review(self, *, owner: str, repo: str, pr_number: int, comments: list[dict]) -> httpx.Response:
        payload = {
            "event": "COMMENT",
            "comments": [
                {
                    "path": comment["path"],
                    "line": comment["line"],
                    "side": comment.get("side", "RIGHT"),
                    "body": comment["body"],
                }
                for comment in comments
            ],
        }
        response = self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            json=payload,
        )
        if response.status_code == 422:
            return response
        self._raise_for_status(response)
        return response

    def create_issue_comment(self, *, owner: str, repo: str, pr_number: int, body: str) -> dict:
        payload = {"body": body}
        response = self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
            json=payload,
        )
        return self._json_or_error(response)

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_exc = None
        for attempt in range(self._retries + 1):
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < self._retries:
                    time.sleep(1 + attempt)
                    continue
                raise GitHubAPIError(0, f"Network error: {exc}") from exc

            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt < self._retries:
                    time.sleep(1 + attempt)
                    continue
            return response
        if last_exc:
            raise GitHubAPIError(0, f"Network error: {last_exc}")
        return response

    def _json_or_error(self, response: httpx.Response):
        self._raise_for_status(response)
        return response.json()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if 200 <= response.status_code < 300:
            return
        message = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict) and payload.get("message"):
                message = payload["message"]
        except ValueError:
            pass
        raise GitHubAPIError(response.status_code, message, response.text)
