import base64
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import Settings


@dataclass(frozen=True)
class ZammadUser:
    id: int
    login: str
    firstname: str
    lastname: str

    @property
    def display_name(self) -> str:
        return " ".join(part for part in (self.firstname, self.lastname) if part).strip() or self.login


async def current_zammad_user(cookie_header: str | None, settings: Settings) -> ZammadUser:
    if not cookie_header:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Zammad session is missing")

    headers = {"Cookie": cookie_header, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(
            base_url=settings.zammad_base_url,
            verify=settings.zammad_verify_tls,
            timeout=settings.zammad_request_timeout_seconds,
            follow_redirects=False,
        ) as client:
            response = await client.get("/api/v1/users/me", headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Zammad is unavailable") from exc

    if response.status_code in {401, 403} or response.status_code in {301, 302, 303, 307, 308}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Zammad session is not valid")
    if response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unexpected response from Zammad")

    payload = response.json()
    if not payload.get("active", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zammad user is inactive")
    try:
        return ZammadUser(
            id=int(payload["id"]),
            login=str(payload["login"]),
            firstname=str(payload.get("firstname") or ""),
            lastname=str(payload.get("lastname") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Invalid user response from Zammad") from exc


class ZammadApiError(RuntimeError):
    pass


class ZammadApi:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def headers(self) -> dict[str, str]:
        if self.settings.zammad_api_token in {"", "replace_me"}:
            raise ZammadApiError("Zammad API token is not configured")
        return {
            "Authorization": f"Token token={self.settings.zammad_api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with httpx.AsyncClient(
                base_url=self.settings.zammad_base_url,
                verify=self.settings.zammad_verify_tls,
                timeout=self.settings.zammad_request_timeout_seconds,
            ) as client:
                response = await client.request(method, path, headers=self.headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ZammadApiError("Zammad API is unavailable") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise ZammadApiError(f"Zammad API returned HTTP {response.status_code}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ZammadApiError("Zammad API returned invalid JSON") from exc

    async def get_user(self, user_id: int) -> dict[str, Any]:
        data = await self.request("GET", f"/api/v1/users/{user_id}")
        if not isinstance(data, dict) or int(data.get("id", 0)) != user_id:
            raise ZammadApiError("Invalid Zammad user response")
        return data

    async def get_organization(self, organization_id: int) -> dict[str, Any]:
        data = await self.request("GET", f"/api/v1/organizations/{organization_id}")
        if not isinstance(data, dict) or int(data.get("id", 0)) != organization_id:
            raise ZammadApiError("Invalid Zammad organization response")
        return data

    async def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        data = await self.request(
            "GET",
            f"/api/v1/tickets/{ticket_id}",
            params={"expand": "true"},
        )
        if not isinstance(data, dict) or int(data.get("id", 0)) != ticket_id:
            raise ZammadApiError("Invalid Zammad ticket response")
        return data

    async def create_customer_ticket(
        self,
        *,
        user_id: int,
        group_id: int,
        title: str,
        body: str,
        attachments: list[tuple[str, str, bytes]] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "title": title,
            "group_id": group_id,
            "customer_id": user_id,
            "article": {
                "subject": title,
                "body": body,
                "content_type": "text/plain",
                "type": "web",
                "internal": False,
                "sender": "Customer",
                "origin_by_id": user_id,
            },
        }
        payload["article"]["sender_id"] = 2
        if attachments:
            payload["article"]["attachments"] = [
                {"filename": name, "mime-type": mime, "data": base64.b64encode(content).decode("ascii")}
                for name, mime, content in attachments
            ]
        data = await self.request("POST", "/api/v1/tickets", json=payload)
        if not isinstance(data, dict) or not data.get("id") or not data.get("number"):
            raise ZammadApiError("Invalid ticket creation response")
        return data

    async def add_article(
        self,
        *,
        ticket_id: int,
        user_id: int,
        body: str,
        sender: str,
        article_type: str,
        attachments: list[tuple[str, str, bytes]] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "ticket_id": ticket_id,
            "body": body,
            "content_type": "text/plain",
            "type": article_type,
            "internal": False,
            "sender": sender,
            "origin_by_id": user_id,
        }
        sender_ids = {"Agent": 1, "Customer": 2, "System": 3}
        sender_id = sender_ids.get(sender)
        if sender_id is not None:
            payload["sender_id"] = sender_id
        if attachments:
            payload["attachments"] = [
                {"filename": name, "mime-type": mime, "data": base64.b64encode(content).decode("ascii")}
                for name, mime, content in attachments
            ]
        data = await self.request("POST", "/api/v1/ticket_articles", json=payload)
        if not isinstance(data, dict) or not data.get("id"):
            raise ZammadApiError("Invalid article creation response")
        return data

    async def find_ticket_by_number(self, number: str) -> dict[str, Any] | None:
        candidates = await self.search_tickets(f"number:{number}", per_page=10)
        for ticket in candidates:
            if str(ticket.get("number")) == number:
                return ticket
        return None

    async def search_tickets(self, query: str, *, per_page: int = 20) -> list[dict[str, Any]]:
        data = await self.request(
            "GET",
            "/api/v1/tickets/search",
            params={
                "query": query,
                "page": 1,
                "per_page": max(1, min(per_page, 100)),
                "sort_by": "updated_at",
                "order_by": "desc",
                "expand": "true",
            },
        )
        candidates: list[dict[str, Any]] = []
        if isinstance(data, list):
            candidates = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict) and isinstance(data.get("tickets"), list):
            candidates = [item for item in data["tickets"] if isinstance(item, dict)]
        return candidates
