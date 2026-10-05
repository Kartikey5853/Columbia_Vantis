import asyncio
import os
import sys
from typing import Any, Dict, List, Optional, Union
from dotenv import load_dotenv
import httpx

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()


class SupabaseClient:
    """
    Lightweight, asynchronous PostgREST client for Supabase.
    Designed specifically for memory-constrained environments (<512 MB).
    """

    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        timeout: float = 15.0,
        max_connections: int = 10
    ):
        self.url = (url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.key = (
            key
            or os.getenv("SUPABASE_SECRET_KEY")
            or os.getenv("SUPABASE_KEY", "")
        )

        if not self.url or not self.key:
            raise ValueError(
                "Supabase URL and Key must be provided or configured via SUPABASE_URL and SUPABASE_KEY/SUPABASE_SECRET_KEY."
            )

        self.rest_url = f"{self.url}/rest/v1"
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.timeout = httpx.Timeout(timeout, connect=10.0)
        self.limits = httpx.Limits(max_keepalive_connections=max_connections, max_connections=max_connections)
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=self.limits,
                headers=self.headers
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Any] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        retries: int = 3
    ) -> httpx.Response:
        client = await self.get_client()
        url = f"{self.rest_url}/{path.lstrip('/')}"
        headers = dict(self.headers)
        if extra_headers:
            headers.update(extra_headers)

        last_exc = None
        for attempt in range(1, retries + 1):
            try:
                res = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                    headers=headers
                )
                if res.status_code in (502, 503, 504, 429) and attempt < retries:
                    await asyncio.sleep(attempt * 1.5)
                    continue
                return res
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(attempt * 1.5)
                    continue
                raise exc

        if last_exc:
            raise last_exc
        raise RuntimeError("Request failed after retries")

    async def select(
        self,
        table: str,
        columns: str = "*",
        filters: Optional[Dict[str, str]] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
        single: bool = False
    ) -> Union[List[Dict[str, Any]], Dict[str, Any], None]:
        """
        Executes a PostgREST GET request.
        Example filter: {"scraper_id": "eq.abc-123", "status": "neq.completed"}
        """
        params = {"select": columns}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)

        headers = {}
        if single:
            headers["Accept"] = "application/vnd.pgrst.object+json"

        res = await self._request_with_retry("GET", table, params=params, extra_headers=headers)
        if res.status_code == 404:
            return None if single else []
        if res.status_code >= 400:
            raise RuntimeError(f"Supabase select error on {table} ({res.status_code}): {res.text}")

        data = res.json()
        return data

    async def insert(
        self,
        table: str,
        data: Union[Dict[str, Any], List[Dict[str, Any]]],
        return_representation: bool = True
    ) -> List[Dict[str, Any]]:
        """Executes a PostgREST POST request (INSERT)."""
        headers = {}
        if return_representation:
            headers["Prefer"] = "return=representation"

        res = await self._request_with_retry("POST", table, json_data=data, extra_headers=headers)
        if res.status_code >= 400:
            raise RuntimeError(f"Supabase insert error on {table} ({res.status_code}): {res.text}")

        if return_representation and res.text:
            return res.json()
        return []

    async def upsert(
        self,
        table: str,
        data: Union[Dict[str, Any], List[Dict[str, Any]]],
        on_conflict: Optional[str] = None,
        return_representation: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Executes a PostgREST POST request with merge-duplicates resolution (UPSERT).
        """
        prefer = "resolution=merge-duplicates"
        if return_representation:
            prefer += ",return=representation"
        headers = {"Prefer": prefer}

        params = {}
        if on_conflict:
            params["on_conflict"] = on_conflict

        res = await self._request_with_retry("POST", table, params=params, json_data=data, extra_headers=headers)
        if res.status_code >= 400:
            raise RuntimeError(f"Supabase upsert error on {table} ({res.status_code}): {res.text}")

        if return_representation and res.text:
            return res.json()
        return []

    async def update(
        self,
        table: str,
        data: Dict[str, Any],
        filters: Dict[str, str],
        return_representation: bool = False
    ) -> List[Dict[str, Any]]:
        """Executes a PostgREST PATCH request (UPDATE)."""
        headers = {}
        if return_representation:
            headers["Prefer"] = "return=representation"

        res = await self._request_with_retry("PATCH", table, params=filters, json_data=data, extra_headers=headers)
        if res.status_code >= 400:
            raise RuntimeError(f"Supabase update error on {table} ({res.status_code}): {res.text}")

        if return_representation and res.text:
            return res.json()
        return []

    async def delete(
        self,
        table: str,
        filters: Dict[str, str]
    ) -> bool:
        """Executes a PostgREST DELETE request."""
        res = await self._request_with_retry("DELETE", table, params=filters)
        if res.status_code >= 400:
            raise RuntimeError(f"Supabase delete error on {table} ({res.status_code}): {res.text}")
        return True

    async def rpc(
        self,
        func_name: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Executes a PostgreSQL stored function via /rest/v1/rpc/{func_name}."""
        res = await self._request_with_retry("POST", f"rpc/{func_name}", json_data=params or {})
        if res.status_code >= 400:
            raise RuntimeError(f"Supabase RPC error on {func_name} ({res.status_code}): {res.text}")
        return res.json()


# Singleton factory for global reuse
_SHARED_CLIENT: Optional[SupabaseClient] = None


def get_supabase_client() -> SupabaseClient:
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None:
        _SHARED_CLIENT = SupabaseClient()
    return _SHARED_CLIENT
