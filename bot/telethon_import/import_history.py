import os
from dotenv import load_dotenv
load_dotenv()

# bot/telethon_import/import_history.py
# Telethon script to import channel history -> download media -> upload to S3 -> POST to backend

from telethon import TelegramClient, events, sync
import os
import sys
import time
import logging
import requests
from io import BytesIO
import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ENV required:
# TELETHON_API_ID, TELETHON_API_HASH, TELETHON_SESSION (optional), CHANNEL_USERNAME or channel id
# BACKEND_URL, S3_BUCKET, S3_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

API_ID = int(os.getenv('TELETHON_API_ID', '0'))
API_HASH = os.getenv('TELETHON_API_HASH')
SESSION = os.getenv('TELETHON_SESSION', 'importer_session')
CHANNEL = os.getenv('CHANNEL_USERNAME')  # @channel or channel id
BACKEND_URL = os.getenv('BACKEND_URL')
IMPORTER_API_KEY = os.getenv('IMPORTER_API_KEY') or os.getenv('BACKEND_IMPORTER_KEY')
S3_BUCKET = os.getenv('S3_BUCKET')
S3_REGION = os.getenv('S3_REGION', 'us-east-1')

if not API_ID or not API_HASH:
    logger.error('TELETHON_API_ID and TELETHON_API_HASH must be set')
    # sys.exit(1)
if not BACKEND_URL:
    logger.error('BACKEND_URL must be set')
    # sys.exit(1)
if not S3_BUCKET:
    logger.warning('S3_BUCKET is not set; telethon_import will skip uploading media to S3. Set S3_BUCKET to enable.')
    # sys.exit(1)
s3 = boto3.client('s3', region_name=S3_REGION)


def derive_backend_base(url: str) -> str:
    u = (url or '').strip().rstrip('/')
    if not u:
        return ''
    idx = u.find('/api/')
    if idx >= 0:
        return u[:idx]
    return u


def build_importer_candidates(url: str):
    raw = (url or '').strip().rstrip('/')
    if not raw:
        return []
    if raw.endswith('/importer/channel_post'):
        return [raw]
    base = derive_backend_base(raw)
    cands = [
        f'{base}/api/v1/importer/channel_post',
        f'{base}/api/importer/channel_post',
        f'{base}/importer/channel_post',
    ]
    if '/api/' in raw:
        cands.insert(0, raw)
    # dedupe preserve order
    out = []
    for c in cands:
        if c and c not in out:
            out.append(c)
    return out


IMPORTER_CANDIDATES = build_importer_candidates(BACKEND_URL)
logger.info('Importer endpoints: %s', ', '.join(IMPORTER_CANDIDATES))

client = TelegramClient(SESSION, API_ID, API_HASH)


def upload_bytes_to_s3(data_bytes: bytes, key: str, content_type: str = 'image/jpeg') -> str:
    try:
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data_bytes, ContentType=content_type, ACL='public-read')
    except ClientError as e:
        logger.exception('S3 upload failed: %s', e)
        raise
    return f'https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{key}'


def make_key(prefix='telethon', ext='jpg'):
    import hashlib, time
    h = hashlib.sha1(str(time.time()).encode()).hexdigest()[:12]
    return f'{prefix}/{int(time.time())}-{h}.{ext}'


async def process_message(msg):
    text = msg.message or ''
    message_id = msg.id
    chat = await msg.get_chat()
    channel_id = getattr(chat, 'id', None)

    image_urls = []
    # if media exists, download
    if msg.media:
        try:
            # Telethon can download media into bytes
            bio = BytesIO()
            await client.download_media(msg.media, file=bio)
            bio.seek(0)
            content_type = 'image/jpeg'
            key = make_key('telethon', 'jpg')
            url = upload_bytes_to_s3(bio.read(), key, content_type)
            image_urls.append(url)
        except Exception as e:
            logger.exception('Failed to download/upload media: %s', e)

    payload = {
        'channel_id': channel_id,
        'message_id': message_id,
        'date': int(msg.date.timestamp()),
        'text': text,
        'image_urls': image_urls,
    }

    try:
        headers = {'X-Importer-Key': IMPORTER_API_KEY} if IMPORTER_API_KEY else None
        last_exc = None
        ok = False
        for endpoint in IMPORTER_CANDIDATES:
            try:
                r = requests.post(endpoint, json=payload, timeout=20, headers=headers)
                if r.status_code in (404, 405):
                    continue
                r.raise_for_status()
                logger.info('Imported message %s -> %s (%s)', message_id, endpoint, r.status_code)
                ok = True
                break
            except Exception as e:
                last_exc = e
        if not ok:
            raise last_exc or RuntimeError('No importer endpoint accepted request')
    except Exception as e:
        logger.exception('Failed to POST to backend for message %s: %s', message_id, e)


async def run_import(limit=500):
    # iterate messages
    async for msg in client.iter_messages(CHANNEL, limit=limit):
        try:
            await process_message(msg)
            time.sleep(0.1)
        except Exception as e:
            logger.exception('Error processing message: %s', e)


if __name__ == '__main__':
    with client:
        lim = int(os.getenv('IMPORT_LIMIT', '200'))
        client.loop.run_until_complete(run_import(limit=lim))