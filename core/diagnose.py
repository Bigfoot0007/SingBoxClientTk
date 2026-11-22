"""Node diagnostics — three-state verdict: healthy / stale params / offline.

Runs an isolated sing-box instance on a temp port with the node under
test, probes HTTPS through it, then classifies failures from the log:

- TCP unreachable                        -> offline        (node down / IP changed)
- "reality verification failed"          -> stale_params   (server rotated keys;
                                                             re-subscribe for new pbk/sid)
- probe succeeded                        -> healthy        (reports latency)
- anything else                          -> error          (raw log tail)

Safe to run while connected: uses its own process, config and port.
"""
import os
import socket
import subprocess
import time
import urllib.request

from .config import ConfigGenerator
from .nogui import nogui_kwargs


class NodeDiagnostics:
    def __init__(self, binary: str, workdir: str, diag_port: int = 17890):
        self.binary = binary
        self.workdir = workdir
        self.diag_port = diag_port

    def run(self, node: dict) -> dict:
        steps = []
        host = node.get("server", "")
        try:
            port = int(node.get("port", 443))
        except (TypeError, ValueError):
            return {"verdict": "error", "detail": "端口无效", "steps": steps}

        # 1) TCP reachability
        try:
            with socket.create_connection((host, port), timeout=5):
                steps.append(f"TCP {host}:{port} 可达")
        except OSError as e:
            steps.append(f"TCP {host}:{port} 不可达: {e}")
            return {"verdict": "offline",
                    "detail": "节点离线(端口不通)。服务器可能已下线,或 IP/端口已变更。",
                    "steps": steps}

        # 2) isolated sing-box + HTTPS probe through it
        gen = ConfigGenerator()
        cfg = gen.generate([node], node.get("id"), ConfigGenerator.ROUTING_ALL)
        cfg["inbounds"][0]["listen_port"] = self.diag_port
        cfg_path = os.path.join(self.workdir, "diagnose.json")
        log_path = os.path.join(self.workdir, "diagnose.log")
        gen.save(cfg, cfg_path)

        verdict = "error"
        detail = ""
        logf = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            [self.binary, "-D", self.workdir, "run", "-c", cfg_path],
            stdout=logf, stderr=logf, **nogui_kwargs())
        try:
            time.sleep(2)
            if proc.poll() is not None:
                return {"verdict": "error",
                        "detail": "sing-box 启动失败:\n" + self._tail(log_path),
                        "steps": steps}
            t0 = time.time()
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({
                    "http": f"http://127.0.0.1:{self.diag_port}",
                    "https": f"http://127.0.0.1:{self.diag_port}"}))
            try:
                resp = opener.open("https://www.google.com/generate_204",
                                   timeout=12)
                latency = time.time() - t0
                steps.append(f"HTTPS 探测成功 "
                             f"(HTTP {resp.getcode()}, {latency:.1f}s)")
                return {"verdict": "healthy",
                        "detail": "节点健康:Reality 握手与转发正常。",
                        "steps": steps, "latency": latency}
            except Exception as e:
                steps.append(f"HTTPS 探测失败: {e}")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            logf.close()

        # 3) classify from the sing-box log
        log = self._tail(log_path, 12)
        if "reality verification failed" in log:
            verdict = "stale_params"
            detail = ("端口开放、服务器在运行,但 Reality 握手验证失败 —\n"
                      "服务端已轮换密钥,本地 pbk/sid 已过期。"
                      "请重新订阅获取新参数。")
        elif ("connection refused" in log or "i/o timeout" in log
                or "network is unreachable" in log):
            verdict = "offline"
            detail = "服务器拒绝连接或超时(服务停止 / 防火墙?)"
        else:
            verdict = "error"
            detail = "握手异常:\n" + log
        return {"verdict": verdict, "detail": detail, "steps": steps}

    @staticmethod
    def _tail(path: str, n: int = 6) -> str:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            return "\n".join(lines[-n:]) or "无输出"
        except OSError:
            return "无法读取日志"
