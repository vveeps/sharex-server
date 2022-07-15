import asyncio
import json
import re
from io import BytesIO
from os import listdir, mkdir, path
from random import SystemRandom
from typing import Optional

import aiofiles
from baize.asgi.responses import FileResponse
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from PIL import Image, ImageOps

CHARS = "ABCDEFGHIJKLMOPQRSTUVWXYZabcdefghijklmopqrstuvwxyz0123456789-_"

ID_REGEX = re.compile(r"([a-zA-Z0-9\-_]{6})(?:\.+?)?")
FILE_REGEX = re.compile(r"([a-zA-Z0-9\-_]{6})\/(.+)\.(.+)")

APP = FastAPI()
NOT_FOUND = HTTPException(404, "Not Found")


async def read_data() -> dict[str, dict[str, str]]:
    async with aiofiles.open("data.json", "r") as f:
        return json.loads(await f.read())


async def write_data(data: dict[str, dict[str, str]]) -> None:
    async with aiofiles.open("data.json", "w") as f:
        await f.write(json.dumps(data))


def remove_jpeg_exif(image: bytes) -> bytes:
    buffer = BytesIO(image)
    original = Image.open(buffer)
    ImageOps.exif_transpose(original)

    exifless = Image.new(original.mode, original.size)  # type: ignore
    exifless.putdata(list(original.getdata()))

    new_buffer = BytesIO()
    exifless.save(new_buffer, format="jpeg")
    new_buffer.seek(0)

    return new_buffer.read()


@APP.get("/", response_class=RedirectResponse)
@APP.get("/upload", response_class=RedirectResponse)
async def index():
    return "https://veeps.moe"


@APP.post("/upload")
async def upload(
    auth: str,
    filename: str = Form(...),
    data: UploadFile = File(...),
    content_length: Optional[str] = Header(None),
):
    _data: dict[str, dict[str, str]] = await read_data()

    if content_length is None:
        raise HTTPException(411, "Length Required")

    if auth not in _data["auth"]:
        raise HTTPException(403, "Forbidden")

    user = _data["auth"][auth]

    if user != "veeps" and int(content_length) >= 101000000:
        raise HTTPException(413, "Request Entity Too Large")

    random = SystemRandom()
    while (file_id := "".join(random.choices(CHARS, k=6))) in _data["ids"]:
        file_id = "".join(random.choices(CHARS, k=6))

    _data["ids"][file_id] = user
    await write_data(_data)

    mkdir(f"./files/{user}/{file_id}")

    ext = filename.split(".")[-1].lower()
    async with aiofiles.open(f"./files/{user}/{file_id}/{filename}", "wb") as f:
        if ext in ("jpe", "jpeg", "jpg"):
            image = await asyncio.get_running_loop().run_in_executor(
                None,
                remove_jpeg_exif,
                await data.read(),
            )
            await f.write(image)
        else:
            while chunk := await data.read(134217728):
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                await f.write(chunk)

    return {"ext": ext, "url": f"https://cdn.veeps.moe/{file_id}"}


@APP.get("/{file:path}")
async def fetch_file(file: str):
    data = await read_data()

    if re.fullmatch(r"[a-zA-Z0-9\-_]{6}(?:\..+)?\/?", file):
        assert (file_id := ID_REGEX.match(file)) is not None
        file_id = file_id.group(1)

        if file_id not in data["ids"]:
            raise NOT_FOUND

        name = data["ids"][file_id]
        filename = listdir(f"./files/{name}/{file_id}")[0]
        return RedirectResponse(f"https://cdn.veeps.moe/{file_id}/{filename}", 301)

    if (match := FILE_REGEX.match(file)) is None:
        raise NOT_FOUND

    file_id, name, ext = match.groups()
    filename = f"{name}.{ext}"

    if ext is None:
        mime = "application/octet-stream"
    else:
        with open("mime.json", "r", encoding="utf-8") as f:
            mime_types: dict = json.load(f)
            mime = mime_types.get(ext.lower(), "application/octet-stream")

    if (user := data["ids"].get(file_id)) is None:
        raise NOT_FOUND

    filepath = f"./files/{user}/{file_id}/{filename}"

    if not path.exists(filepath):
        raise NOT_FOUND

    async def iter_file(path, *, chunk_size: int = 1_048_576):
        async with aiofiles.open(path, "rb") as f:
            yield await f.read(chunk_size)

    return StreamingResponse(iter_file(filepath), media_type=mime)
