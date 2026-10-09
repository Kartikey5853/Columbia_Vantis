import asyncio
import os
import sys
from pathlib import Path
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
    Lightweight, asynchronous PostgREST & Storage client for Supabase.
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
        self.storage_url = f"{self.url}/storage/v1"
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
        offset: Optional[int] = None,
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
        if offset is not None:
            params["offset"] = str(offset)

        headers = {}
        if single:
            headers["Accept"] = "application/vnd.pgrst.object+json"

        res = await self._request_with_retry("GET", table, params=params, extra_headers=headers)
        if res.status_code == 404:
            return None if single else []
        if res.status_code >= 400:
            raise RuntimeError(f"Supabase select error on {table} ({res.status_code}): {res.text}")

        if not res.text or not res.text.strip():
            return None if single else []
        try:
            data = res.json()
        except Exception:
            return None if single else []
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
        if not res.text or not res.text.strip():
            return None
        try:
            return res.json()
        except Exception:
            return None

    # =========================================================================
    # Supabase Storage Methods
    # =========================================================================

    async def storage_download_stream(
        self,
        bucket: str,
        path: str,
        target_path: Union[str, Path]
    ) -> Path:
        """
        Downloads an object from Supabase Storage streaming directly to disk
        in 64 KB chunks to prevent out-of-memory errors in low-RAM environments.
        """
        target_path = Path(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{self.storage_url}/object/{bucket}/{path.lstrip('/')}"
        client = await self.get_client()

        for attempt in range(1, 4):
            try:
                async with client.stream("GET", url) as res:
                    if res.status_code == 404:
                        raise FileNotFoundError(f"Supabase Storage object not found: {bucket}/{path}")
                    if res.status_code in (401, 403):
                        raise PermissionError(f"Supabase Storage unauthorized ({res.status_code}) for {bucket}/{path}")
                    if res.status_code in (502, 503, 504, 429) and attempt < 3:
                        await asyncio.sleep(attempt * 2.0)
                        continue
                    if res.status_code >= 400:
                        raise RuntimeError(f"Supabase Storage download error ({res.status_code}) for {bucket}/{path}")

                    with open(target_path, "wb") as f:
                        async for chunk in res.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                    return target_path
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                if attempt < 3:
                    await asyncio.sleep(attempt * 2.0)
                    continue
                raise exc

        raise RuntimeError(f"Failed to download {bucket}/{path} after retries")

    async def storage_upload_file(
        self,
        bucket: str,
        path: str,
        source_path: Union[str, Path],
        upsert: bool = True
    ) -> Dict[str, Any]:
        """
        Uploads a file to Supabase Storage streaming from disk in chunks.
        """
        source_path = Path(source_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file to upload not found: {source_path}")

        url = f"{self.storage_url}/object/{bucket}/{path.lstrip('/')}"
        headers = dict(self.headers)
        headers["x-upsert"] = "true" if upsert else "false"
        headers["Content-Type"] = "application/octet-stream"

        async def file_generator():
            with open(source_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk

        client = await self.get_client()
        for attempt in range(1, 4):
            try:
                res = await client.post(url, headers=headers, content=file_generator())
                if res.status_code in (502, 503, 504, 429) and attempt < 3:
                    await asyncio.sleep(attempt * 2.0)
                    continue
                if res.status_code >= 400:
                    raise RuntimeError(f"Supabase Storage upload error ({res.status_code}) for {bucket}/{path}: {res.text}")
                return res.json() if res.text else {}
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                if attempt < 3:
                    await asyncio.sleep(attempt * 2.0)
                    continue
                raise exc

        raise RuntimeError(f"Failed to upload {bucket}/{path} after retries")

    async def storage_move(
        self,
        bucket: str,
        from_path: str,
        to_path: str
    ) -> bool:
        """
        Moves/renames an object within a bucket for atomic profile replacement.
        """
        url = f"{self.storage_url}/object/move"
        client = await self.get_client()
        res = await client.post(
            url,
            json={"bucketId": bucket, "sourceKey": from_path.lstrip("/"), "destinationKey": to_path.lstrip("/")}
        )
        if res.status_code >= 400:
            raise RuntimeError(f"Supabase Storage move error ({res.status_code}): {res.text}")
        return True

    async def storage_delete(
        self,
        bucket: str,
        paths: List[str]
    ) -> bool:
        """Deletes one or more objects from a bucket."""
        url = f"{self.storage_url}/object/{bucket}"
        client = await self.get_client()
        clean_paths = [p.lstrip("/") for p in paths]
        res = await client.request("DELETE", url, json={"prefixes": clean_paths})
        if res.status_code >= 400:
            raise RuntimeError(f"Supabase Storage delete error ({res.status_code}): {res.text}")
        return True

    async def storage_list(
        self,
        bucket: str,
        prefix: str = "",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Lists objects in a bucket with metadata."""
        url = f"{self.storage_url}/object/list/{bucket}"
        client = await self.get_client()
        res = await client.post(url, json={"prefix": prefix, "limit": limit})
        if res.status_code >= 400:
            raise RuntimeError(f"Supabase Storage list error ({res.status_code}): {res.text}")
        return res.json() if res.text else []


# Singleton factory for global reuse
_SHARED_CLIENT: Optional[SupabaseClient] = None


def get_supabase_client() -> SupabaseClient:
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None:
        _SHARED_CLIENT = SupabaseClient()
    return _SHARED_CLIENT
