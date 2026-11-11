"""Copy legacy uploads from the local upload directory into the database."""

import asyncio
import logging
from pathlib import Path

from chat.uploads import detect_mime, valid_attachment_id

log = logging.getLogger(__name__)


async def preserve_legacy_uploads(store, upload_dir):
    attachments = await store.legacy_attachments()
    if not attachments:
        return
    preserved = 0
    missing = 0
    directory = Path(upload_dir)
    for attachment in attachments:
        att_id = attachment["id"]
        if not valid_attachment_id(att_id):
            continue
        try:
            content = await asyncio.to_thread((directory / att_id).read_bytes)
        except FileNotFoundError:
            missing += 1
            continue
        except OSError as error:
            log.warning("Could not read a legacy upload (%s)", type(error).__name__)
            missing += 1
            continue
        if not _matches_attachment(content, attachment):
            log.warning("A legacy upload failed its integrity check")
            missing += 1
            continue
        await store.preserve_attachment(att_id, content)
        preserved += 1
    log.info("Upload migration preserved %s files; %s previous files were unavailable", preserved, missing)


def _matches_attachment(content, attachment):
    if len(content) != attachment["size"]:
        return False
    try:
        return detect_mime(content, attachment["name"]) == attachment["mime"]
    except ValueError:
        return False
