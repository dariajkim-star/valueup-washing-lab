"""회사 IR 사이트에서 계획서 PDF 취득 — robots.txt를 코드가 강제로 확인한다.

■ 왜 이 경로인가
    DART 첨부 경로는 두 번 실증적으로 닫혔다: robots.txt가 뷰어·첨부·다운로드를 전부
    Disallow하고, 사람이 직접 받아봐도 첨부 PDF가 **존재하지 않았다**(뷰어가 주는 것은
    본문 통지문 HTML 하나뿐). "첨부된 계획을 참고하라"가 가리키는 실물은 회사 IR 페이지에
    있고, 그 주소는 공시의 '관련 웹페이지' 필드에 회사가 스스로 적어 두었다.

■ 크롤링이 아니다
    공시가 지목한 URL **하나만** 받는다. 링크를 따라다니지 않고, 사이트를 훑지 않는다.
    규제 공시가 "여기 있다"고 적은 주소를 그대로 여는 것이다.

■ robots.txt는 선택이 아니라 관문
    DART에서 배운 것: 짓기 전에 운영자 지시를 읽는다. 여기서는 그것을 **코드에** 넣었다 —
    `RobotsGate`가 도메인별 robots.txt를 받아 판정하고, 허용이 아니면 요청 자체를 만들지
    않는다. 사람이 한 번 확인하고 잊는 방식은 URL이 늘면 무너진다.
    robots.txt가 없으면(404) 명시적 금지가 없는 것으로 본다 — 표준 해석이다.

■ 예의
    도메인당 최소 간격을 두고(_MIN_INTERVAL), 우리를 식별하는 User-Agent를 보내며,
    파일 크기 상한을 둔다. 실패는 조용히 넘기지 않고 사유를 남긴다.
"""

from __future__ import annotations

import logging
import time
import urllib.robotparser as robotparser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# 우리를 식별한다 — 운영자가 로그에서 누구인지 알 수 있어야 한다.
USER_AGENT = "valueup-washing-lab/0.1 (research; +https://github.com/dariajkim-star/valueup-washing-lab)"
_TIMEOUT = 60
_MIN_INTERVAL = 1.0          # 같은 도메인 연속 요청 최소 간격(초)
_MAX_BYTES = 50 * 1024 * 1024  # 계획서 PDF 상한(실측 LG화학 2.9MB)


class RobotsDisallowed(Exception):
    """robots.txt가 금지한 URL. 요청을 만들지 않고 여기서 멈춘다."""


@dataclass
class FetchResult:
    url: str
    path: Path | None = None
    content_type: str | None = None
    size: int = 0
    error: str | None = None


class RobotsGate:
    """도메인별 robots.txt 판정(캐시). 허용이 아니면 요청을 막는다."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._cache: dict[str, robotparser.RobotFileParser | None] = {}

    def _parser(self, netloc: str, scheme: str) -> robotparser.RobotFileParser | None:
        if netloc in self._cache:
            return self._cache[netloc]
        url = f"{scheme}://{netloc}/robots.txt"
        parser: robotparser.RobotFileParser | None
        try:
            r = self._session.get(url, timeout=_TIMEOUT, headers={"User-Agent": USER_AGENT})
            if r.status_code == 200:
                parser = robotparser.RobotFileParser()
                parser.parse(r.text.splitlines())
            else:
                # robots.txt 없음 = 명시적 금지 없음(표준 해석)
                parser = None
        except requests.RequestException as e:
            # 받지 못했으면 **금지로 취급한다** — 모르는 채로 긁는 것보다 멈추는 게 낫다.
            logger.warning("robots.txt 취득 실패 %s: %s → 금지로 취급", netloc, type(e).__name__)
            parser = _DENY_ALL
        self._cache[netloc] = parser
        return parser

    def allows(self, url: str) -> bool:
        p = urlparse(url)
        parser = self._parser(p.netloc, p.scheme or "https")
        if parser is None:
            return True
        return parser.can_fetch(USER_AGENT, url)


def _deny_all() -> robotparser.RobotFileParser:
    parser = robotparser.RobotFileParser()
    parser.parse(["User-agent: *", "Disallow: /"])
    return parser


_DENY_ALL = _deny_all()


class IrSiteFetcher:
    """공시가 지목한 URL에서 PDF를 받는다(단건, 링크 추적 없음)."""

    def __init__(self, gate: RobotsGate | None = None) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._gate = gate or RobotsGate(self._session)
        self._last_call: dict[str, float] = {}

    def _wait(self, netloc: str) -> None:
        last = self._last_call.get(netloc)
        if last is not None:
            gap = time.monotonic() - last
            if gap < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - gap)
        self._last_call[netloc] = time.monotonic()

    def fetch_pdf(self, url: str, dest: Path) -> FetchResult:
        """URL이 PDF면 dest에 저장. 아니면 사유를 담아 반환(예외 대신 보고)."""
        result = FetchResult(url=url)
        if not self._gate.allows(url):
            result.error = "robots_disallowed"
            logger.info("robots.txt 금지 — 요청하지 않음: %s", url)
            return result

        netloc = urlparse(url).netloc
        self._wait(netloc)
        try:
            with self._session.get(url, timeout=_TIMEOUT, stream=True) as r:
                if r.status_code != 200:
                    result.error = f"http_{r.status_code}"
                    return result
                ctype = (r.headers.get("content-type") or "").split(";")[0].strip()
                result.content_type = ctype
                if "pdf" not in ctype.lower():
                    # 1단계는 **직링크 PDF만** 다룬다. IR 랜딩 페이지에서 PDF를 찾아내는
                    # 것은 링크 추적이므로 별도 결정 사항이다(지금은 하지 않는다).
                    result.error = f"not_pdf:{ctype or 'unknown'}"
                    return result
                dest.parent.mkdir(parents=True, exist_ok=True)
                size = 0
                with dest.open("wb") as f:
                    for chunk in r.iter_content(1024 * 256):
                        size += len(chunk)
                        if size > _MAX_BYTES:
                            f.close()
                            dest.unlink(missing_ok=True)
                            result.error = "too_large"
                            return result
                        f.write(chunk)
                result.path = dest
                result.size = size
        except requests.RequestException as e:
            result.error = f"request_error:{type(e).__name__}"
        return result
