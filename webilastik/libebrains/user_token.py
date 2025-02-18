from pathlib import PurePosixPath
from typing import Optional, Mapping, Union

import requests
from ndstructs.utils.json_serializable import JsonObject, JsonValue, JsonableValue, ensureJsonObject

from webilastik.utility.url import Url



class UserToken:
    def __init__(
        self,
        *,
        access_token: str,
        refresh_token: Optional[str] = None,
        # expires_in: int,
        # refresh_expires_in: int,
        # token_type: str,
        # id_token: str,
        # not_before_policy: int,
        # session_state: str,
        # scope: str
    ):
        self._api_url = Url.parse("https://iam.ebrains.eu/auth/realms/hbp/protocol/openid-connect")
        self.access_token = access_token
        self.refresh_token = refresh_token
        # self.expires_in = expires_in
        # self.refresh_expires_in = refresh_expires_in
        # self.token_type = token_type
        # self.id_token = id_token
        # self.not_before_policy = not_before_policy
        # self.session_state = session_state
        # self.scope = scope

    def _get(
        self,
        path: PurePosixPath,
        *,
        params: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
        https_verify: bool = True,
    ) -> JsonValue:
        url = self._api_url.joinpath(path).updated_with(search={})
        resp = requests.get(
            url.raw,
            params={**url.search, **(params or {})},
            headers={
                **(headers or {}),
                "Authorization": f"Bearer {self.access_token}",
            },
            verify=https_verify,
        )
        resp.raise_for_status()
        return resp.json()

    def is_valid(self) -> bool:
        #FIXME: maybe just validate signature + time ?
        try:
            self.get_userinfo()
            return True
        except requests.exceptions.HTTPError:
            return False

    def get_userinfo(self) -> JsonObject:
        return ensureJsonObject(self._get(PurePosixPath("userinfo")))
