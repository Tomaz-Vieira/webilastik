# pyright: reportUnusedCallResult=false

from asyncio.events import AbstractEventLoop
from dataclasses import dataclass
from functools import partial
import os
import signal
import asyncio
from typing import Callable, List, Optional, Mapping
import json
from base64 import b64decode
import ssl
import contextlib
from pathlib import Path
import traceback

import aiohttp
from aiohttp import web
from aiohttp.client import ClientSession
from aiohttp.http_websocket import WSCloseCode
from aiohttp.web_app import Application
from ndstructs.utils.json_serializable import JsonObject, JsonValue, ensureJsonObject, ensureJsonString

from webilastik.datasource.precomputed_chunks_datasource import PrecomputedChunksInfo
from webilastik.ui.applet.export_applet import WsExportApplet
from webilastik.ui.applet.datasource_picker import WsDataSourcePicker
from webilastik.ui.usage_error import UsageError
from webilastik.utility.url import Protocol, Url
from webilastik.scheduling.hashing_executor import HashingExecutor
from webilastik.server.tunnel import ReverseSshTunnel
from webilastik.ui.applet import dummy_prompt
from webilastik.ui.applet.ws_applet import WsApplet
from webilastik.ui.applet.ws_feature_selection_applet import WsFeatureSelectionApplet
from webilastik.ui.applet.ws_brushing_applet import WsBrushingApplet
from webilastik.ui.applet.ws_pixel_classification_applet import WsPixelClassificationApplet
from webilastik.ui.workflow.pixel_classification_workflow import PixelClassificationWorkflow
from webilastik.libebrains.user_token import UserToken


class MyLogger:
    def debug(self, message: str):
        print(f"\033[32m [DEBUG]{message}\033[0m")

    def info(self, message: str):
        print(f"\033[34m [INFO]{message}\033[0m")

    def warn(self, message: str):
        print(f"\033[33m [WARNING]{message}\033[0m")

    def error(self, message: str):
        print(f"\033[31m [ERROR]{message}\033[0m")


logger = MyLogger()

@dataclass
class RPCPayload:
    applet_name: str
    method_name: str
    arguments: JsonObject

    @classmethod
    def from_json_value(cls, value: JsonValue) -> "RPCPayload":
        value_obj = ensureJsonObject(value)
        return RPCPayload(
            applet_name=ensureJsonString(value_obj.get("applet_name")),
            method_name=ensureJsonString(value_obj.get("method_name")),
            arguments=ensureJsonObject(value_obj.get("arguments")),
        )

    def to_json_value(self) -> JsonObject:
        return {
            "applet_name": self.applet_name,
            "method_name": self.method_name,
            "arguments": self.arguments,
        }


class WsPixelClassificationWorkflow(PixelClassificationWorkflow):
    @property
    def http_client_session(self) -> ClientSession:
        if self._http_client_session is None:
            self._http_client_session = aiohttp.ClientSession()
        return self._http_client_session

    @property
    def loop(self) -> AbstractEventLoop:
        if self._loop == None:
            self._loop = self.app.loop
        return self._loop

    def enqueue_user_interaction(self, user_interaction: Callable[[], Optional[UsageError]]):
        async def do_rpc():
            error_message = None
            try:
                result = user_interaction()
                if isinstance(result, UsageError):
                    error_message = str(result)
            except Exception as e:
                traceback_messages = traceback.format_exc()
                error_message = f"Unhandled Exception: {e}\n\n{traceback_messages}"
                logger.error(error_message)
            await self._update_clients(error_message=error_message)
        self.loop.call_soon_threadsafe(lambda: self.loop.create_task(do_rpc()))

    async def close_websockets(self, app: Application):
        for ws in self.websockets:
            await ws.close(
                code=WSCloseCode.GOING_AWAY,
                message=json.dumps({
                    "error": 'Server shutdown'
                }).encode("utf8")
            )

    def __init__(self, ebrains_user_token: UserToken, ssl_context: Optional[ssl.SSLContext] = None):
        self.ssl_context = ssl_context
        self.ebrains_user_token = ebrains_user_token
        self.websockets: List[web.WebSocketResponse] = []
        self._http_client_session: Optional[ClientSession] = None
        self._loop: Optional[AbstractEventLoop] = None

        executor = HashingExecutor(name="Pixel Classification Executor")

        brushing_applet = WsBrushingApplet("brushing_applet")
        feature_selection_applet = WsFeatureSelectionApplet("feature_selection_applet", datasources=brushing_applet.datasources)


        self.pixel_classifier_applet = WsPixelClassificationApplet(
            "pixel_classification_applet",
            feature_extractors=feature_selection_applet.feature_extractors,
            annotations=brushing_applet.annotations,
            runner=executor,
            enqueue_interaction=self.enqueue_user_interaction
        )

        self.export_datasource_applet = WsDataSourcePicker(
            name="export_datasource_applet",
            allowed_protocols=tuple([Protocol.HTTPS, Protocol.HTTP]),
            ebrains_user_token=self.ebrains_user_token,
            datasource_suggestions=brushing_applet.datasources,
        )

        self.export_applet = WsExportApplet(
            name="export_applet",
            ebrains_user_token=self.ebrains_user_token,
            executor=executor,
            operator=self.pixel_classifier_applet.pixel_classifier,
            datasource=self.export_datasource_applet.datasource,
            on_job_step_completed=lambda job_id, step_index : self.enqueue_user_interaction(lambda: None),
            on_job_completed=lambda job_id : self.enqueue_user_interaction(lambda: None),
            enqueue_interaction=self.enqueue_user_interaction,
        )

        self.wsapplets : Mapping[str, WsApplet] = {
            feature_selection_applet.name: feature_selection_applet,
            brushing_applet.name: brushing_applet,
            self.pixel_classifier_applet.name: self.pixel_classifier_applet,
            self.export_datasource_applet.name: self.export_datasource_applet,
            self.export_applet.name: self.export_applet,
        }

        super().__init__(
            feature_selection_applet=feature_selection_applet,
            brushing_applet=brushing_applet,
            pixel_classifier_applet=self.pixel_classifier_applet,
        )

        self.app = web.Application()
        self.app.add_routes([
            web.get('/status', self.get_status),
            web.get('/ws', self.open_websocket), # type: ignore
            web.get(
                "/predictions/raw_data={encoded_raw_data}/generation={generation}/data/{xBegin}-{xEnd}_{yBegin}-{yEnd}_{zBegin}-{zEnd}",
                self.pixel_classifier_applet.precomputed_chunks_compute
            ),
            web.get(
                "/predictions/raw_data={encoded_raw_data}/generation={generation}/info",
                self.pixel_classifier_applet.predictions_precomputed_chunks_info
            ),
            web.post("/ilp_project", self.ilp_download),
            web.delete("/close", self.close_session),
            web.get(
                "/stripped_precomputed/url={encoded_original_url}/resolution={resolution_x}_{resolution_y}_{resolution_z}/info",
                self.stripped_precomputed_info
            ),
            web.get(
                "/stripped_precomputed/url={encoded_original_url}/resolution={resolution_x}_{resolution_y}_{resolution_z}/{rest:.*}",
                self.forward_chunk_request
            ),
        ])
        self.app.on_shutdown.append(self.close_websockets)

    async def get_status(self, request: web.Request) -> web.Response:
        return web.Response(
            text=json.dumps({
                "status": "running"
            }),
            content_type="application/json",
        )

    async def close_session(self, request: web.Request) -> web.Response:
        #FIXME: this is not properly killing the server
        _ = asyncio.get_event_loop().create_task(self._self_destruct())
        return web.Response()

    async def _self_destruct(self, after_seconds: int = 5):
        _ = await asyncio.sleep(5)
        try:
            pid = os.getpid()
            pgid = os.getpgid(pid)
            logger.info(f"[SESSION KILL]Gently killing local session (pid={pid}) with SIGINT on group....")
            os.killpg(pgid, signal.SIGINT)
            _ = await asyncio.sleep(10)
            logger.info(f"[SESSION KILL]Killing local session (pid={pid}) with SIGKILL on group....")
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def run(self, host: Optional[str] = None, port: Optional[int] = None, unix_socket_path: Optional[str] = None):
        web.run_app(self.app, port=port, path=unix_socket_path)

    async def open_websocket(self, request: web.Request):
        websocket = web.WebSocketResponse()
        _ = await websocket.prepare(request)
        self.websockets.append(websocket)
        logger.debug(f"JUST STABILISHED A NEW CONNECTION!!!! {len(self.websockets)}")
        await self._update_clients() # when a new client connects, send it the current state
        async for msg in websocket:
            if msg.type == aiohttp.WSMsgType.TEXT:
                if msg.data == 'close':
                    _ = await websocket.close()
                    continue
                try:
                    parsed_payload = json.loads(msg.data)
                    logger.debug(f"Got new rpc call:\n{json.dumps(parsed_payload, indent=4)}\n")
                    payload = RPCPayload.from_json_value(parsed_payload)
                    logger.debug("GOT PAYLOAD OK")
                    user_interaction = partial(
                        self.wsapplets[payload.applet_name].run_rpc,
                        user_prompt=dummy_prompt,
                        method_name=payload.method_name,
                        arguments=payload.arguments,
                    )
                    self.enqueue_user_interaction(user_interaction)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    await self._update_clients() # restore last known good state of offending client
            elif msg.type == aiohttp.WSMsgType.BINARY:
                logger.error(f'Unexpected binary message')
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error(f'ws connection closed with exception {websocket.exception()}')
        if websocket in self.websockets:
            logger.info(f"Removing websocket! Current websockets: {len(self.websockets)}")
            self.websockets.remove(websocket)
        logger.info('websocket connection closed')
        return websocket

    async def _update_clients(self, error_message: Optional[str] = None):
        if error_message is not None:
            payload = {"error": error_message}
        else:
            payload = {name: applet._get_json_state() for name, applet in self.wsapplets.items()}

        async def do_update(ws: web.WebSocketResponse):
            try:
                await websocket.send_str(json.dumps(payload))
            except ConnectionResetError as e:
                logger.error(f"Got an exception while updating remote:\n{e}\n\nRemoving websocket...")
                self.websockets.remove(websocket)

        loop = self.app.loop # FIXME?
        for websocket in self.websockets[:]:
            loop.create_task(do_update(websocket))

    async def ilp_download(self, request: web.Request):
        return web.Response(
            body=self.ilp_file.read(),
            content_type="application/octet-stream",
            headers={
                "Content-disposition": 'attachment; filename="MyProject.ilp"'
            }
        )

    async def stripped_precomputed_info(self, request: web.Request) -> web.Response:
        """Serves a precomp info stripped of all but one scales"""
        resolution_x = request.match_info.get("resolution_x")
        resolution_y = request.match_info.get("resolution_y")
        resolution_z = request.match_info.get("resolution_z")
        if resolution_x is None or resolution_y is None or resolution_z is None:
            return web.Response(status=400, text=f"Bad resolution: {resolution_x}_{resolution_y}_{resolution_z}")
        try:
            resolution = (int(resolution_x), int(resolution_x), int(resolution_x))
        except Exception:
            return web.Response(status=400, text=f"Bad resolution: {resolution_x}_{resolution_y}_{resolution_z}")

        encoded_original_url = request.match_info.get("encoded_original_url")
        if not encoded_original_url:
            return web.Response(status=400, text="Missing parameter: url")

        decoded_url = b64decode(encoded_original_url, altchars=b'-_').decode('utf8')
        base_url = Url.parse(decoded_url)
        if base_url is None:
            return web.Response(status=400, text=f"Bad url: {decoded_url}")
        info_url = base_url.joinpath("info")
        logger.debug(f"Will request this info: {info_url.schemeless_raw}")

        async with self.http_client_session.get(
            info_url.schemeless_raw,
            ssl=self.ssl_context,
            headers=self.ebrains_user_token.as_auth_header() if info_url.hostname == "data-proxy.ebrains.eu" else {},
            params={"redirect": "true"} if info_url.hostname == "data-proxy.ebrains.eu" else {},
        ) as response:
            response_text = await response.text()
            if response.status // 100 != 2:
                return web.Response(status=response.status, text=response_text)
            info = PrecomputedChunksInfo.from_json_value(json.loads(response_text))

        stripped_info = info.stripped(resolution=resolution)
        return web.json_response(stripped_info.to_json_value())

    async def forward_chunk_request(self, request: web.Request) -> web.Response:
        """Redirects a precomp chunk request to the original URL"""
        encoded_original_url = request.match_info.get("encoded_original_url")
        if not encoded_original_url:
            return web.Response(status=400, text="Missing parameter: url")
        decoded_url = b64decode(encoded_original_url, altchars=b'-_').decode('utf8')
        url = Url.parse(decoded_url)
        if url is None:
            return web.Response(status=400, text=f"Bad url: {decoded_url}")
        rest = request.match_info.get("rest", "").lstrip("/")
        tile_url = url.joinpath(rest)

        if tile_url.hostname != "data-proxy.ebrains.eu":
            raise web.HTTPFound(location=tile_url.schemeless_raw)

        async with self.http_client_session.get(
            tile_url.schemeless_raw,
            ssl=self.ssl_context,
            headers=self.ebrains_user_token.as_auth_header(),
        ) as response:
            cscs_url = (await response.json())["url"]
            print(f"@@@@@@@@@@@@@ FINAL REDIRECT URL IS {cscs_url}")
            raise web.HTTPFound(location=cscs_url)


if __name__ == '__main__':
    from argparse import ArgumentParser

    parser = ArgumentParser()
    parser.add_argument("--ebrains-user-access-token", type=str, required=True)
    parser.add_argument("--listen-socket", type=Path, required=True)
    parser.add_argument("--ca-cert-path", "--ca_cert_path", help="Path to CA crt file. Useful e.g. for testing with mkcert")

    subparsers = parser.add_subparsers(required=False, help="tunnel stuff")
    tunnel_parser = subparsers.add_parser("tunnel", help="Creates a reverse tunnel to an orchestrator")
    tunnel_parser.add_argument("--remote-username", type=str, required=True)
    tunnel_parser.add_argument("--remote-host", required=True)
    tunnel_parser.add_argument("--remote-unix-socket", type=Path, required=True)

    args = parser.parse_args()

    mpi_rank = 0
    try:
        from mpi4py import MPI #type: ignore
        mpi_rank = MPI.COMM_WORLD.Get_rank()
    except ModuleNotFoundError:
        pass

    ca_crt: Optional[str] = args.ca_cert_path or os.environ.get("CA_CERT_PATH")
    ssl_context: Optional[ssl.SSLContext] = None

    if ca_crt is not None:
        if not Path(ca_crt).exists():
            logger.error(f"File not found: {ca_crt}")
            exit(1)
        ssl_context = ssl.create_default_context(cafile=ca_crt)

    if "remote_username" in vars(args) and mpi_rank == 0:
        server_context = ReverseSshTunnel(
            remote_username=args.remote_username,
            remote_host=args.remote_host,
            remote_unix_socket=args.remote_unix_socket,
            local_unix_socket=args.listen_socket,
        )
    else:
        server_context = contextlib.nullcontext()

    with server_context:
        WsPixelClassificationWorkflow(
            ebrains_user_token=UserToken(access_token=args.ebrains_user_access_token),
            ssl_context=ssl_context
        ).run(
            unix_socket_path=str(args.listen_socket),
        )
    try:
        os.remove(args.listen_socket)
    except FileNotFoundError:
        pass

