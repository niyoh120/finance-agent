"""请求帧构建与响应帧解析。

移植自 niyoh120/easy_tdx（固定提交 e374a0da2834119ac695c1083805d1b0a60967c2）
的 ``codec/frame.py``、``codec/mac_frame.py``，并按服务安全边界补充硬上限
与回显校验支持：

- 标准协议请求帧（12 字节起）：byte0=0x0C 帧头标识，bytes[1:5] 序列号，
  byte5 子命令标记，bytes[6:8] 声明长度，bytes[8:10] 解压长度，bytes[10:12] 命令码。
  各命令的字节模板与参考实现逐字节一致（在真实服务器验证过的常量）。
- MAC 协议请求帧（10 字节头）：``<BIBHH`` = head_flag + customize + version
  + 声明长度 + 解压长度；head_flag 标准 MAC=0x1C，MAC EX 服务器=0x01。
- 三类协议的响应帧统一为 16 字节头（``<IIIHH``）：magic=7654321，
  bytes[10:12] 回显请求 bytes[10:12]（标准命令码 / MAC msg_id）。

响应侧硬上限（本服务新增）：声明 body 长度与解压后长度均不得超过
``MAX_FRAME_BODY`` / ``MAX_UNZIPPED_BODY``，防止畸形帧导致内存放大。
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from ..errors import TdxDecodeError
from .primitives import require_bytes, unpack_from

#: 标准协议请求帧头标识。
HEAD_FLAG_STANDARD = 0x0C
#: MAC 协议请求帧头标识（MAC 行情服务器）。
HEAD_FLAG_MAC = 0x1C
#: MAC EX 服务器要求请求帧头标识为 0x01。
HEAD_FLAG_MAC_EX = 0x01

#: 响应帧固定头长度。
HEADER_SIZE = 16
_HEADER_FMT = "<IIIHH"
_MAGIC = 7654321  # 0x0074CBB1，协议魔数

#: 响应 body（压缩态）硬上限。正常最大页（1000 条证券列表）远小于该值。
MAX_FRAME_BODY = 4 * 1024 * 1024
#: 解压后 body 硬上限，防止 zip 炸弹式内存放大。
MAX_UNZIPPED_BODY = 16 * 1024 * 1024


@dataclass(frozen=True)
class FrameHeader:
    """16 字节响应帧头。"""

    magic: int
    seq_id: int  # ZipFlag(1B) + 请求 bytes 1-4 回显(3B)
    method: int  # 请求 bytes 10-12 回显(2B) + 前置字段
    zipsize: int
    unzipsize: int


def build_mac_request(msg_id: int, body: bytes, *, head_flag: int = HEAD_FLAG_MAC) -> bytes:
    """构建 MAC 族请求帧（10 字节头 + msg_id + body）。"""
    inner = struct.pack("<H", msg_id) + body
    header = struct.pack("<BIBHH", head_flag, 0, 1, len(inner), len(inner))
    return header + inner


def request_method_echo(frame: bytes) -> bytes:
    """取请求帧 bytes[10:12]，响应帧 method 字段应回显该值。

    标准帧 bytes[10:12] 为命令码，MAC 族帧 bytes[10:12] 为 msg_id。
    帧长不足 12 字节时返回空值（调用方跳过回显校验）。
    """
    if len(frame) < 12:
        return b""
    return bytes(frame[10:12])


def parse_header(buf: bytes) -> FrameHeader:
    """解析 16 字节响应帧头并校验魔数与声明长度上限。"""
    require_bytes(buf, 0, HEADER_SIZE, "frame header")
    magic, seq_id, method, zipsize, unzipsize = unpack_from(_HEADER_FMT, buf, 0, "frame header")
    if magic != _MAGIC:
        raise TdxDecodeError(f"frame header 魔数不符: {magic:#x}")
    if zipsize > MAX_FRAME_BODY:
        raise TdxDecodeError(f"frame body 声明长度超上限: {zipsize} > {MAX_FRAME_BODY}")
    if unzipsize > MAX_UNZIPPED_BODY:
        raise TdxDecodeError(f"frame 解压长度超上限: {unzipsize} > {MAX_UNZIPPED_BODY}")
    return FrameHeader(magic, seq_id, method, zipsize, unzipsize)


def decompress_body(header: FrameHeader, raw_body: bytes) -> bytes:
    """按需 zlib 解压 body，严格校验声明长度。"""
    if len(raw_body) != header.zipsize:
        raise TdxDecodeError(f"frame body 长度不符: header={header.zipsize}, actual={len(raw_body)}")
    if header.zipsize == header.unzipsize:
        body = raw_body
    else:
        try:
            body = zlib.decompress(raw_body)
        except zlib.error as e:
            raise TdxDecodeError(f"frame body zlib 解压失败: {e}") from e
    if len(body) != header.unzipsize:
        raise TdxDecodeError(f"frame body 解压长度不符: header={header.unzipsize}, actual={len(body)}")
    return body
