import base64
from pathlib import Path
import json
import logging
import urllib.request
import urllib.parse
import uuid
import websocket

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Dict


# Load default logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


# API definition
api_title = 'ComfyUI 接口文档'
api_version = '0.0.1'
server_address = '192.168.19.40:8188'
client_id = str(uuid.uuid4())
images_folder = Path(__file__).parent.joinpath("images")
images_folder.mkdir(parents=True, exist_ok=True)

def queue_prompt(prompt):
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req =  urllib.request.Request("http://{}/prompt".format(server_address), data=data)
    return json.loads(urllib.request.urlopen(req).read())

def get_image(filename, subfolder, folder_type):
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen("http://{}/view?{}".format(server_address, url_values)) as response:
        return response.read()

def get_history(prompt_id):
    with urllib.request.urlopen("http://{}/history/{}".format(server_address, prompt_id)) as response:
        return json.loads(response.read())

def get_images(ws, prompt):
    prompt_id = queue_prompt(prompt)['prompt_id']
    output_images = {}
    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            if message['type'] == 'executing':
                data = message['data']
                if data['node'] is None and data['prompt_id'] == prompt_id:
                    break #Execution is done
        else:
            continue #previews are binary data

    history = get_history(prompt_id)[prompt_id]
    for o in history['outputs']:
        for node_id in history['outputs']:
            node_output = history['outputs'][node_id]
            if 'images' in node_output:
                images_output = []
                for image in node_output['images']:
                    image_data = get_image(image['filename'], image['subfolder'], image['type'])
                    images_output.append(image_data)
            output_images[node_id] = images_output

    return output_images


class Payload(BaseModel):  # pylint: disable=too-few-public-methods
    """Payload properties."""

    prompt: Dict = Field(
        title='Prompt',
        description='ComfyUI 的 workflow(json)'
    )

class Response(BaseModel):  # pylint: disable=too-few-public-methods
    """Response properties."""

    images: list = Field(
        title='Image',
        description='图片结果'
    )

log.info('Start %s API, version %s', api_title, api_version)
app = FastAPI(title=api_title, version=api_version)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.mount("/images", StaticFiles(directory=images_folder), name="images")

# Endpoints
@app.post('/prompt', response_model=Response, description='Execute a ComfyUI workflow.')
def prompt(payload: Payload, request: Request):
    image_url = urllib.parse.urljoin(str(request.url), 'images')
    ws = websocket.WebSocket()
    ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id))
    prompt = payload.prompt
    images = get_images(ws, prompt)
    r = []
    for node_id in images:
        for image_data in images[node_id]:
            from PIL import Image
            import io
            image = Image.open(io.BytesIO(image_data))
            # image.show()
            filename = f"{client_id}-{node_id}.png"
            filepath = images_folder.joinpath(filename)
            image.save(filepath)
            r.append(image_url + "/" + filename)
    ws.close()
    response = { 'images': r }
    return JSONResponse(content=response, status_code=200)
