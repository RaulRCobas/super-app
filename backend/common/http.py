"""
Sesión HTTP compartida para toda la ingesta.
Uso responsable: cabeceras de navegador real, reintentos con backoff exponencial,
pausa mínima entre peticiones al mismo host y timeout razonable. No subas la
concurrencia ni bajes RATE_LIMIT_SECONDS sin pensarlo -- el objetivo es no
generar carga perceptible en las webs de origen.
"""
import time
import random
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
RATE_LIMIT_SECONDS = 1.5  # pausa mínima entre peticiones al mismo host

_last_request_at = {}

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "es-ES,es;q=0.9",
        "Accept": "text/html,application/json,*/*;q=0.8",
    })
    retries = Retry(
        total=4, backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "PUT", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

def polite_get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    """GET con espaciado mínimo entre peticiones al mismo host + jitter."""
    host = url.split("/")[2]
    now = time.monotonic()
    wait = RATE_LIMIT_SECONDS - (now - _last_request_at.get(host, 0))
    if wait > 0:
        time.sleep(wait + random.uniform(0, 0.4))
    resp = session.get(url, timeout=20, **kwargs)
    _last_request_at[host] = time.monotonic()
    resp.raise_for_status()
    return resp
