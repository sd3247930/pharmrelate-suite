"""自签证书生成（仅用于本地自测与二期 WSS 预研）。

**这不是产品依赖**：生产环境的证书由部署方自己生成与轮换，
本模块只解决"在开发机上没有证书就没法验 WSS"这个问题。

生成的是带 SAN 的证书 —— 现代浏览器与 Android 都要求 SAN，
只写 CN 的证书会被直接拒绝，这是自签证书最常见的坑。
"""

from __future__ import annotations

import datetime as dt
import ipaddress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CertPaths:
    cert: Path
    key: Path


def generate_self_signed(
    directory: Path,
    *,
    common_name: str = "pharmrelate.local",
    days: int = 365,
    extra_hosts: list[str] | None = None,
) -> CertPaths:
    """生成一份自签证书与私钥。

    必须包含 SAN：只填 CN 的证书在 Android 7+ 与新版浏览器上会被拒绝。
    """

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    cert_path = directory / "pharmrelate.crt"
    key_path = directory / "pharmrelate.key"

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PharmRelate"),
        ]
    )

    hosts = ["localhost", common_name, *(extra_hosts or [])]
    san_entries: list[x509.GeneralName] = [x509.DNSName(host) for host in hosts]
    san_entries.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))

    now = dt.datetime.now(dt.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return CertPaths(cert=cert_path, key=key_path)


def server_ssl_context(cert: Path, key: Path):
    """服务端 SSL 上下文。"""

    import ssl

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert), keyfile=str(key))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def client_ssl_context(ca: Path, *, check_hostname: bool = True):
    """客户端 SSL 上下文：信任指定的自签 CA。

    `check_hostname=False` 仅供本机自测（用 127.0.0.1 连接时证书里的 SAN 可能不含它）；
    真实部署不应关闭主机名校验 —— 关掉等于放弃中间人防护。
    """

    import ssl

    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca))
    context.check_hostname = check_hostname
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context
