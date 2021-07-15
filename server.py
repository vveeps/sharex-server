import json
import re
from io import BytesIO
from os import listdir, mkdir, path
from random import SystemRandom
from string import ascii_letters, digits

from aiohttp import BodyPartReader, web
from aiohttp.web import (
    HTTPBadRequest,
    HTTPForbidden,
    HTTPMovedPermanently,
    HTTPNotFound,
    HTTPSeeOther,
    json_response,
    Request,
    Response,
    RouteTableDef
)

CHARS = ascii_letters + digits
ROUTES = RouteTableDef()

# Regex
ID_REGEX = re.compile(r"([a-zA-Z0-9]{6})(?:\.+?)?")
FILE_REGEX = re.compile(r"([a-zA-Z0-9]{6})\/(.+)\.(.+)")


def read_data() -> dict:
    with open("data.json", "r", encoding="utf-8") as f:
        return json.load(f)


def write_data(data: dict) -> None:
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def validate_field(name: str, field: BodyPartReader) -> BodyPartReader:
    if field.name == name:
        return field

    raise HTTPBadRequest()


@ROUTES.get("/")
@ROUTES.get(r"/{_:upload\/?}")
async def index(request: Request) -> Response:
    raise HTTPSeeOther("https://veeps.moe")


@ROUTES.get(r"/{file_id:[a-zA-Z0-9]{6}(?:\..+)?\/?}")
async def redirect_to_exact_file(request: Request) -> Response:
    data = read_data()

    file_id = ID_REGEX.match(request.match_info['file_id']).group(1)
    if file_id not in data["ids"]:
        raise HTTPNotFound()

    name = data["ids"][file_id]
    filename = listdir(f"./files/{name}/{file_id}")[0]
    raise HTTPMovedPermanently(f"https://cdn.veeps.moe/{file_id}/{filename}")


@ROUTES.get(r"/{file_path:[a-zA-Z0-9]{6}\/.+\/?}")
async def fetch_file(request: Request) -> Response:
    data = read_data()

    file_path = request.match_info['file_path']
    file_id, name, ext = FILE_REGEX.match(file_path).groups()

    filename = f"{name}.{ext}"

    if ext is None:
        mime = "application/octet-stream"
    else:
        with open("mime.json", "r", encoding="utf-8") as f:
            mime_types: dict = json.load(f)
            mime = mime_types.get(ext.lower(), "application/octet-stream")

    if (user := data["ids"].get(file_id)) is None:
        raise HTTPNotFound()

    with open(f"./files/{user}/{file_id}/{filename}", "rb") as f:
        return Response(body=f.read(), content_type=mime)


@ROUTES.post(r"/{_:upload\/?}")
async def upload(request: Request) -> Response:
    data = read_data()

    if (token := request.query.get("auth")) not in data["auth"]:
        raise HTTPForbidden(text="Bad authentication")

    reader = await request.multipart()
    
    field = validate_field("filename", await reader.next())
    filename = (await field.read()).decode("utf-8")

    field = validate_field("data", await reader.next())
    size = 0
    buffer = b""

    while True:
        chunk = await field.read_chunk()
        if not chunk:
            break

        size += len(chunk)
        if size >= 101000000:
            raise HTTPBadRequest()

        buffer += chunk

    random = SystemRandom()
    while (file_id := "".join(random.choices(CHARS, k=6))) in data["ids"]:
        file_id = "".join(random.choices(CHARS, k=6))

    user = data["auth"][token]
    data["ids"][file_id] = user

    write_data(data)

    mkdir(f"./files/{user}/{file_id}")
    with open(f"./files/{user}/{file_id}/{filename}", "wb") as f:
        f.write(buffer)

    return json_response({
        "ext": filename.split(".")[-1],
        "url": f"https://cdn.veeps.moe/{file_id}"
    })


APP = web.Application()
APP.add_routes(ROUTES)
web.run_app(APP, host="localhost", port=9999)
