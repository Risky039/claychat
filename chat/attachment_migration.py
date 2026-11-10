"""Preserve available disk uploads before the replacement web instance goes live."""

import asyncio
import logging
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout

from chat.uploads import MAX_UPLOAD_BYTES, detect_mime, valid_attachment_id

log = logging.getLogger(__name__)


async def preserve_legacy_uploads(store, upload_dir, origin=""):
    attachments = await store.legacy_attachments()
    if not attachments:
        return
    preserved = 0
    missing = 0
    async with ClientSession(timeout=ClientTimeout(total=20), trust_env=True) as session:
        for attachment in attachments:
            att_id = attachment["id"]
            if not valid_attachment_id(att_id):
                continue
            local = Path(upload_dir) / att_id
            if local.is_file():
                content = await asyncio.to_thread(local.read_bytes)
            elif origin:
                async with session.get(f"{origin.rstrip('/')}/api/uploads/{att_id}", allow_redirects=False) as response:
                    if response.status == 404:
                        missing += 1
                        continue
                    response.raise_for_status()
                    if response.status != 200:
                        raise RuntimeError("The previous instance could not serve an upload")
                    chunks = []
                    size = 0
                    async for chunk in response.content.iter_chunked(65536):
                        size += len(chunk)
                        if size > MAX_UPLOAD_BYTES:
                            raise RuntimeError("An existing upload exceeds the upload size limit")
                        chunks.append(chunk)
                    content = b"".join(chunks)
            else:
                continue
            if len(content) != attachment["size"] or detect_mime(content, attachment["name"]) != attachment["mime"]:
                raise RuntimeError("An existing upload failed its integrity check")
            await store.preserve_attachment(att_id, content)
            preserved += 1
    log.info("Upload migration preserved %s files; %s previous files were unavailable", preserved, missing)
