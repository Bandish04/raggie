# Annotated fixtures for .semgrep/raggie.yml — run: uvx semgrep --test .semgrep
# (never imported; exists only so every rule has positive and negative cases).
import hmac

import httpx
import requests


async def sql(conn, table, value, sets):
    # ruleid: raggie-sql-built-from-strings
    await conn.fetch(f"SELECT * FROM {table}")
    await conn.fetchrow(
        "UPDATE t SET a = 1"
        # ruleid: raggie-sql-built-from-strings
        f" WHERE id = {value}",
    )
    # ruleid: raggie-sql-built-from-strings
    await conn.execute("DELETE FROM t WHERE id = %s" % value)
    # ruleid: raggie-sql-built-from-strings
    await conn.execute("DELETE FROM t WHERE id = {}".format(value))
    # ok: raggie-sql-built-from-strings
    await conn.fetchrow("SELECT * FROM t WHERE id = $1", value)


async def documents(conn, doc_id):
    # ruleid: raggie-documents-query-without-soft-delete-filter
    await conn.fetchrow("SELECT * FROM documents WHERE id = $1", doc_id)
    # ruleid: raggie-documents-query-without-soft-delete-filter
    await conn.execute("UPDATE documents SET status = 'X' WHERE id = $1", doc_id)
    # ok: raggie-documents-query-without-soft-delete-filter
    await conn.fetchrow("SELECT * FROM documents WHERE id = $1 AND deleted_at IS NULL", doc_id)
    # ok: raggie-documents-query-without-soft-delete-filter
    await conn.fetchrow("INSERT INTO documents (id) VALUES ($1)", doc_id)


def secrets(presented_token, expected_token, api_key, header):
    # ruleid: raggie-secret-compared-without-hmac
    if presented_token == expected_token:
        pass
    # ruleid: raggie-secret-compared-without-hmac
    if header != api_key:
        pass
    # ok: raggie-secret-compared-without-hmac
    if presented_token == "":
        pass
    # ok: raggie-secret-compared-without-hmac
    if hmac.compare_digest(presented_token.encode(), expected_token.encode()):
        pass


async def http(url):
    # ruleid: raggie-http-call-without-timeout
    requests.get(url)
    # ruleid: raggie-http-call-without-timeout
    async with httpx.AsyncClient() as client:
        await client.get(url)
    # ok: raggie-http-call-without-timeout
    requests.get(url, timeout=5)
    # ok: raggie-http-call-without-timeout
    async with httpx.AsyncClient(timeout=10) as client:
        await client.get(url)
