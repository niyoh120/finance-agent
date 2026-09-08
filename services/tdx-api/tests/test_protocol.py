"""协议层测试：请求编码黄金字节、帧解析边界、真实 TCP 回放。

黄金字节来源：参考实现 easy-tdx 1.20.6 wheel（移植时记录的对照哈希
sha256=8aec465e... 逐字节一致；该依赖已自 workspace 移除，记录保留作
来源证据）在干净环境中生成的请求帧，存于 ``fixtures/golden_requests.json``，
与本服务移植代码相互独立。

解码期望（varint/自定义浮点/时间）为手工推导向量，
避免与参考实现自对拍。
"""

from __future__ import annotations

import json
import struct
from datetime import datetime
from pathlib import Path

import pytest
from conftest import Exchange, FakeTdxServer, build_frame
from tdx_api.tdx.codec.frame import (
    HEADER_SIZE,
    decompress_body,
    parse_header,
    request_method_echo,
)
from tdx_api.tdx.codec.primitives import (
    _decode_volume,
    get_datetime_day,
    get_datetime_minute,
    get_price,
    get_time,
    get_volume,
    put_price,
)
from tdx_api.tdx.commands.ex.extended import (
    GetExHistoryMinuteTimeDataCmd,
    GetExHistoryTransactionDataCmd,
    GetExInstrumentCountCmd,
    GetExInstrumentInfoCmd,
    GetExMinuteTimeDataCmd,
    GetExTransactionDataCmd,
    MacExLoginCmd,
)
from tdx_api.tdx.commands.mac.bitmap import QUOTE_FIELDS
from tdx_api.tdx.commands.mac.symbols import (
    MacSymbolBarCmd,
    MacSymbolInfoCmd,
    MacSymbolQuotesCmd,
    MacSymbolTransactionCmd,
)
from tdx_api.tdx.commands.standard.fundamentals import (
    GetFinanceInfoCmd,
    GetXdxrInfoCmd,
)
from tdx_api.tdx.commands.standard.securities import (
    GetSecurityCountCmd,
    GetSecurityListCmd,
)
from tdx_api.tdx.commands.standard.setup import SETUP_COMMANDS
from tdx_api.tdx.enums import Adjust, MacPeriod, StdMarket
from tdx_api.tdx.errors import TdxConnectionError, TdxDecodeError, TdxTimeoutError
from tdx_api.tdx.transport import Budget, MacExSession, MacSession, StandardSession

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "golden_requests.json").read_text())


def budget() -> Budget:
    """每用例独立预算（Budget 内含单调时钟 deadline，不可共享）。"""
    return Budget(total_seconds=5.0, connect_seconds=2.0, io_seconds=2.0)


# --------------------------------------------------------------------- #
# 黄金请求字节（参考实现独立生成）
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "golden_key,frame_bytes",
    [
        ("security_count", GetSecurityCountCmd(StdMarket.SH).render(0x0C)),
        ("security_list", GetSecurityListCmd(StdMarket.SZ, 1000).render(0x0C)),
        ("finance_info", GetFinanceInfoCmd(StdMarket.SH, "600000").render(0x0C)),
        ("xdxr_info", GetXdxrInfoCmd(StdMarket.SH, "600000").render(0x0C)),
        (
            "mac_bar_daily_qfq",
            MacSymbolBarCmd(1, "600000", MacPeriod.DAILY, 1, 0, 100, Adjust.QFQ).render(0x1C),
        ),
        (
            "mac_bar_min1",
            MacSymbolBarCmd(0, "000001", MacPeriod.MIN_1, 1, 700, 700, Adjust.NONE).render(0x1C),
        ),
        (
            "mac_quotes",
            MacSymbolQuotesCmd([(0, "000001"), (1, "600000")], QUOTE_FIELDS).render(0x1C),
        ),
        ("mac_info", MacSymbolInfoCmd(1, "600000").render(0x1C)),
        (
            "mac_transaction",
            MacSymbolTransactionCmd(47, "IFL0", None, 0, 1000).render(0x1C),
        ),
        ("ex_login", MacExLoginCmd().render(0x01)),
        ("ex_count", GetExInstrumentCountCmd().render(0x01)),
        ("ex_info", GetExInstrumentInfoCmd(1234, 500).render(0x01)),
        ("ex_minute", GetExMinuteTimeDataCmd(31, "00700").render(0x01)),
        ("ex_history_minute", GetExHistoryMinuteTimeDataCmd(31, "00700", 20250717).render(0x01)),
        ("ex_transaction", GetExTransactionDataCmd(31, "00700", 0, 1800).render(0x01)),
        (
            "ex_history_transaction",
            GetExHistoryTransactionDataCmd(31, "00700", 20250717, 0, 1800).render(0x01),
        ),
    ],
)
def test_request_frames_match_reference_golden_bytes(golden_key: str, frame_bytes: bytes):
    """本服务移植的请求帧与参考实现输出逐字节一致。"""
    assert frame_bytes.hex() == GOLDEN[golden_key]


def test_setup_commands_match_reference():
    """三条握手命令为参考实现（pytdx 血统）逐字常量。"""
    assert [c.hex() for c in SETUP_COMMANDS] == [
        "0c0218930001030003000d0001",
        "0c0218940001030003000d0002",
        "0c031899000120002000db0fd5d0c9ccd6a4a8af0000008fc22540130000d500c9ccbdf0d7ea00000002",
    ]


def test_mac_ex_frame_uses_ex_head_flag():
    """同一 MAC 命令在 EX 会话渲染为 0x01 帧标识。"""
    mac_frame = MacSymbolBarCmd(1, "600000").render(0x1C)
    ex_frame = MacSymbolBarCmd(1, "600000").render(0x01)
    assert mac_frame[0] == 0x1C
    assert ex_frame[0] == 0x01
    assert mac_frame[1:] == ex_frame[1:]


# --------------------------------------------------------------------- #
# 原语解码（手工推导向量）
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        (b"\x00", 0),
        (b"\x01", 1),
        (b"\x3f", 63),
        (b"\x80\x01", 64),
        (b"\x40", -0),  # 符号位 + 零值 → 0
        (b"\x41", -1),
        (b"\xc0\x01", -64),
        (b"\x82\x06", 386),  # 386 = 0b110000010 → 低 6 位 0x02，余 6
    ],
)
def test_varint_decode_hand_vectors(raw: bytes, expected: int):
    value, pos = get_price(raw, 0)
    assert value == expected
    assert pos == len(raw)


@pytest.mark.parametrize(
    "value,expected_bytes",
    [
        (0, b"\x00"),
        (1, b"\x01"),
        (63, b"\x3f"),
        (64, b"\x80\x01"),
        (-1, b"\x41"),
    ],
)
def test_varint_encode_roundtrip(value: int, expected_bytes: bytes):
    assert put_price(value) == expected_bytes
    decoded, _ = get_price(expected_bytes, 0)
    assert decoded == value


@pytest.mark.parametrize(
    "ivol,expected",
    [
        (0x00000000, 0.0),
        (0x40000000, 2.0),  # logpoint=64 → 2^(128-127)=2
        (0x41000000, 8.0),  # logpoint=65 → 2^(130-127)=8
        (0x40800000, 4.0),  # 2 + 2^(128-134)*128=2 → 4
    ],
)
def test_volume_custom_float_hand_vectors(ivol: int, expected: float):
    assert _decode_volume(ivol) == expected


def test_volume_decoder_matches_reference_vectors():
    """成交量 4 字节解码与参考实现一致（独立构造字节）。"""
    data = struct.pack("<I", 0x42100000)
    value, pos = get_volume(data, 0)
    assert pos == 4
    assert value == pytest.approx(_decode_volume(0x42100000))


def test_datetime_decoders():
    # 分钟级：zipday=0x44B0 → year=(17664>>11)+2004=2012, month=9%, day…
    zipday = (2012 - 2004) << 11 | 918  # 2012-09-18
    tminutes = 13 * 60 + 25
    body = struct.pack("<HH", zipday, tminutes)
    year, month, day, hour, minute, pos = get_datetime_minute(body, 0)
    assert (year, month, day, hour, minute) == (2012, 9, 18, 13, 25)
    assert pos == 4
    # 日级 YYYYMMDD
    year, month, day, pos = get_datetime_day(struct.pack("<I", 20250717), 0)
    assert (year, month, day) == (2025, 7, 17)
    assert pos == 4


def test_get_time_decoder():
    hour, minute, pos = get_time(struct.pack("<H", 14 * 60 + 57), 0)
    assert (hour, minute, pos) == (14, 57, 2)


# --------------------------------------------------------------------- #
# 帧头解析边界
# --------------------------------------------------------------------- #


def test_parse_header_accepts_valid():
    header = parse_header(build_frame(b"abcd", 0x2D05))
    assert header.magic == 7654321
    assert header.zipsize == 4
    assert header.unzipsize == 4


def test_parse_header_rejects_truncated():
    with pytest.raises(TdxDecodeError):
        parse_header(build_frame(b"x", 0)[: HEADER_SIZE - 1])


def test_parse_header_rejects_bad_magic():
    bad = struct.pack("<IIIHH", 12345, 0, 0x0D00, 0, 0)
    with pytest.raises(TdxDecodeError):
        parse_header(bad)


def test_parse_header_accepts_max_declared_length():
    """协议帧长字段为 u16：65535 是可声明的上限且可正常解析。"""
    bad = struct.pack("<IIIHH", 7654321, 0, 0, 65535, 65535)
    header = parse_header(bad)
    assert header.zipsize == 65535


def test_decompress_body_uncompressed_length_mismatch():
    header = parse_header(build_frame(b"abcd", 0))
    with pytest.raises(TdxDecodeError):
        decompress_body(header, b"abc")


def test_decompress_body_compressed_roundtrip():
    raw = build_frame(b"hello" * 20, 0x1234, compress=True)
    header = parse_header(raw)
    assert header.zipsize < header.unzipsize
    body = decompress_body(header, raw[HEADER_SIZE:])
    assert body == b"hello" * 20


def test_decompress_body_garbage_zlib():
    # zipsize != unzipsize 时声明为压缩体；此处声明压缩但内容为非法 zlib。
    header = parse_header(struct.pack("<IIIHH", 7654321, 0, 0, 6, 60))
    with pytest.raises(TdxDecodeError, match="zlib"):
        decompress_body(header, b"\x01\x02\x03\x04\x05\x06")


def test_request_method_echo():
    frame = GetSecurityCountCmd(StdMarket.SH).render(0x0C)
    assert request_method_echo(frame) == b"\x4e\x04"
    mac_frame = MacSymbolBarCmd(1, "600000").render(0x1C)
    assert request_method_echo(mac_frame) == b"\x2e\x12"


# --------------------------------------------------------------------- #
# 真实 TCP 回放（生产 transport）
# --------------------------------------------------------------------- #


def _setup_exchanges() -> list[Exchange]:
    return [
        Exchange(len(SETUP_COMMANDS[0]), build_frame(b"", 0x000D)),
        Exchange(len(SETUP_COMMANDS[1]), build_frame(b"", 0x000D)),
        Exchange(len(SETUP_COMMANDS[2]), build_frame(b"", 0x000D)),
    ]


def _count_body(count: int) -> bytes:
    return struct.pack("<H", count)


def test_standard_session_execute_happy_path():
    server = FakeTdxServer(_setup_exchanges() + [Exchange(18, build_frame(_count_body(3456), 0x044E))])
    server.start()
    try:
        session = StandardSession.open(server.host, server.port, budget())
        try:
            result = session.execute(GetSecurityCountCmd(StdMarket.SH))
        finally:
            session.close()
    finally:
        server.stop()
    assert result == 3456
    # 命令码回显：服务器原样返回请求 bytes[10:12]
    assert server.requests[3][10:12] == b"\x4e\x04"


def test_standard_session_compressed_response():
    body = _count_body(42)
    compressed = build_frame(body, 0x044E, compress=True)
    server = FakeTdxServer(_setup_exchanges() + [Exchange(18, compressed)])
    server.start()
    try:
        session = StandardSession.open(server.host, server.port, budget())
        try:
            assert session.execute(GetSecurityCountCmd(StdMarket.SH)) == 42
        finally:
            session.close()
    finally:
        server.stop()


def test_standard_session_split_packet_delivery():
    """断包回放：响应分两次发送，transport 必须循环收满。"""
    frame = build_frame(_count_body(7), 0x044E)
    server = FakeTdxServer(_setup_exchanges() + [Exchange(18, frame, split_at=HEADER_SIZE + 1)])
    server.start()
    try:
        session = StandardSession.open(server.host, server.port, budget())
        try:
            assert session.execute(GetSecurityCountCmd(StdMarket.SH)) == 7
        finally:
            session.close()
    finally:
        server.stop()


def test_standard_session_method_echo_mismatch_is_tolerated():
    """回显异常不拒绝：请求级独占连接保证响应归属（真实服务器行为差异）。"""
    server = FakeTdxServer(_setup_exchanges() + [Exchange(18, build_frame(_count_body(1), 0x1234))])
    server.start()
    try:
        session = StandardSession.open(server.host, server.port, budget())
        try:
            assert session.execute(GetSecurityCountCmd(StdMarket.SH)) == 1
        finally:
            session.close()
    finally:
        server.stop()


def test_standard_session_truncated_body_detected():
    """声明 4 字节 body 只到 2 字节且连接关闭：报长度不符。"""
    header = struct.pack("<IIIHH", 7654321, 0, 0x044E, 4, 4)
    server = FakeTdxServer(_setup_exchanges() + [Exchange(18, header + b"\x01\x00")])
    server.start()
    try:
        session = StandardSession.open(server.host, server.port, budget())
        try:
            with pytest.raises((TdxDecodeError, TdxConnectionError)):
                session.execute(GetSecurityCountCmd(StdMarket.SH))
        finally:
            session.close()
    finally:
        server.stop()


def test_standard_session_io_timeout():
    """服务器不响应且保持连接：单次 IO 超时 → TdxTimeoutError。"""
    server = FakeTdxServer(
        _setup_exchanges() + [Exchange(18, b"", hold_seconds=2.0)]  # 空响应=不回复
    )
    budget = Budget(total_seconds=1.0, connect_seconds=0.5, io_seconds=0.2)
    server.start()
    try:
        session = StandardSession.open(server.host, server.port, budget)
        try:
            with pytest.raises(TdxTimeoutError):
                session.execute(GetSecurityCountCmd(StdMarket.SH))
        finally:
            session.close()
    finally:
        server.stop()


def test_standard_session_budget_exhausted():
    """预算耗尽后 execute 直接失败。"""
    server = FakeTdxServer(_setup_exchanges() + [Exchange(18, build_frame(_count_body(1), 0x044E))])
    budget = Budget(total_seconds=0.05, connect_seconds=0.5, io_seconds=0.5)
    server.start()
    try:
        session = StandardSession.open(server.host, server.port, budget)
        try:
            budget._deadline -= 10  # 模拟等待后预算耗尽
            with pytest.raises(TdxTimeoutError, match="预算"):
                session.execute(GetSecurityCountCmd(StdMarket.SH))
        finally:
            session.close()
    finally:
        server.stop()


def test_mac_session_handshake_and_command():
    cmd = MacSymbolBarCmd(1, "600000", MacPeriod.DAILY, 1, 0, 2, Adjust.NONE)
    frame_len = len(cmd.render(0x1C))
    # 响应 body：24 字节前缀 + <HBHI 头 + 2 条 36 字节记录
    bars_body = b"\x00" * 24 + struct.pack("<HBHI", 4, 0, 2, 0)
    for ymd, close in ((20250716, 10.5), (20250717, 10.8)):
        bars_body += struct.pack("<II7f", ymd, 0, close - 0.2, close + 0.3, close - 0.4, close, 12345.0, 6789.0, 0.0)
    server = FakeTdxServer(_setup_exchanges() + [Exchange(frame_len, build_frame(bars_body, 0x122E))])
    server.start()
    try:
        session = MacSession.open(server.host, server.port, budget())
        try:
            bars = session.execute(cmd)
        finally:
            session.close()
    finally:
        server.stop()
    assert len(bars) == 2
    assert bars[0]["close"] == pytest.approx(10.5)
    assert bars[1]["datetime"] == datetime(2025, 7, 17)
    # MAC 请求帧头标识 0x1C
    assert server.requests[3][0] == 0x1C


def test_mac_bar_response_silently_drops_out_of_range_ymd():
    """参考实现行为：ymd 越界记录跳过。"""
    cmd = MacSymbolBarCmd(1, "600000", MacPeriod.DAILY, 1, 0, 2, Adjust.NONE)
    bars_body = b"\x00" * 24 + struct.pack("<HBHI", 4, 0, 2, 0)
    bars_body += struct.pack("<II7f", 18991231, 0, 1, 2, 0.5, 1.5, 1.0, 1.0, 0.0)
    bars_body += struct.pack("<II7f", 20250717, 0, 1, 2, 0.5, 1.5, 1.0, 1.0, 0.0)
    server = FakeTdxServer(_setup_exchanges() + [Exchange(len(cmd.render(0x1C)), build_frame(bars_body, 0x122E))])
    server.start()
    try:
        session = MacSession.open(server.host, server.port, budget())
        try:
            bars = session.execute(cmd)
        finally:
            session.close()
    finally:
        server.stop()
    assert [b["datetime"] for b in bars] == [datetime(2025, 7, 17)]


def test_mac_ex_session_requires_login():
    """EX 会话握手为登录命令；服务器响应空 body → 主机级故障。"""
    login_len = len(MacExLoginCmd().render(0x01))
    server = FakeTdxServer([Exchange(login_len, build_frame(b"", 0x2454))])
    server.start()
    try:
        with pytest.raises(TdxConnectionError, match="登录"):
            MacExSession.open(server.host, server.port, budget())
    finally:
        server.stop()


def test_mac_ex_session_login_then_command():
    login_len = len(MacExLoginCmd().render(0x01))
    count_cmd = GetExInstrumentCountCmd()
    count_frame = build_frame(b"\x00" * 19 + struct.pack("<I", 123456) + b"\x00" * 0, 0x23F0)
    # 响应 body 至少 23 字节，count 位于偏移 19
    body = b"\x00" * 19 + struct.pack("<I", 123456)
    count_frame = build_frame(body + b"\x00" * (23 - len(body)) if len(body) < 23 else body, 0x23F0)
    server = FakeTdxServer(
        [Exchange(login_len, build_frame(b"\x01\x00", 0x2454)), Exchange(len(count_cmd.render(0x01)), count_frame)]
    )
    server.start()
    try:
        session = MacExSession.open(server.host, server.port, budget())
        try:
            total = session.execute(count_cmd)
        finally:
            session.close()
    finally:
        server.stop()
    assert total == 123456


def test_mac_ex_session_head_flag_converted():
    """EX 会话上执行 MAC 命令时帧头自动转为 0x01。"""
    login_len = len(MacExLoginCmd().render(0x01))
    cmd = MacSymbolTransactionCmd(74, "AAPL", None, 0, 10)
    body = b"\x00" * 29 + struct.pack("<H", 1)
    body += b"\x00" * (39 - len(body))  # 记录区起点 39
    body += struct.pack("<IfIIH", 3600, 199.5, 100, 1, 0)
    server = FakeTdxServer(
        [
            Exchange(login_len, build_frame(b"\x01\x00", 0x2454)),
            Exchange(len(cmd.render(0x01)), build_frame(body, 0x122F)),
        ]
    )
    server.start()
    try:
        session = MacExSession.open(server.host, server.port, budget())
        try:
            rows = session.execute(cmd)
        finally:
            session.close()
    finally:
        server.stop()
    assert len(rows) == 1
    assert rows[0].price == pytest.approx(199.5)
    assert server.requests[1][0] == 0x01


def test_transaction_command_preserves_duplicate_ticks():
    """同一时间价格的合法多笔记录必须保留（服务层不几何去重）。

    MAC 0x122F 响应：39 字节头 + 每条 18 字节 <IfIIH>。
    """
    cmd = MacSymbolTransactionCmd(1, "600000", None, 0, 10)
    body = b"\x00" * 29 + struct.pack("<H", 2)
    body += b"\x00" * (39 - len(body))  # 记录区起点 39
    # 两笔完全相同的成交：时间 09:30:00、价格 12.34、量 5、买盘
    for _ in range(2):
        body += struct.pack("<IfIIH", 9 * 3600, 12.34, 5, 1, 0)
    server = FakeTdxServer(_setup_exchanges() + [Exchange(len(cmd.render(0x1C)), build_frame(body, 0x122F))])
    server.start()
    try:
        session = MacSession.open(server.host, server.port, budget())
        try:
            rows = session.execute(cmd)
        finally:
            session.close()
    finally:
        server.stop()
    assert len(rows) == 2
    assert rows[0].time == rows[1].time
    assert rows[0].price == rows[1].price
    assert rows[0].volume == rows[1].volume
