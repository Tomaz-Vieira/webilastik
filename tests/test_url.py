# pyright: strict

from pathlib import PurePosixPath
from webilastik.utility.url import Url, DataScheme, Protocol

def test_url_basics():
    raw = "precomputed://http://some.host.com/some/path?a=123&b=456#myhash"
    url = Url.parse(raw)
    assert url.datascheme == DataScheme.PRECOMPUTED
    assert url.protocol == Protocol.HTTP
    assert url.port == None
    assert url.path == PurePosixPath("/some/path")
    assert url.search == {"a": '123', "b": '456'}
    assert url.double_protocol_raw == raw

    url2 = url.updated_with(extra_search={"c": "456", "d": "789"})
    assert url2.search ==  {"a": '123', "b": '456', "c": "456", "d": "789"}
    assert url2.raw == "precomputed+http://some.host.com/some/path?a=123&b=456&c=456&d=789#myhash"

    url3 = Url.parse("http://some.host.com/some/path?a=123&b=%5B1%2C+2%2C+3%5D#myhash")
    assert url3.search["b"]== '[1, 2, 3]'
