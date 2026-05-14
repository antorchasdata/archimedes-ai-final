#!/usr/bin/env python3
"""
Archimedes Chat Server
======================
Bridges the browser UI with the claude CLI via WebSocket.
Streams claude output token-by-token to the frontend.

Usage:
    python3 archimedes_chat.py
    → Opens http://localhost:8765 automatically
"""

import asyncio
import base64
import json
import mimetypes
import os
import signal
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import websockets

# ── Config ───────────────────────────────────────────────────────────────────
WS_PORT    = 8765
HTTP_PORT  = 8766
CLAUDE     = "/opt/homebrew/bin/claude"
SERVE_DIR  = Path(__file__).parent
PROJECT_DIR = Path(__file__).parent  # /Users/I519409/dev/archimedes-ai

# ── Active sessions: each browser tab gets its own claude process ─────────────
sessions: dict[str, asyncio.subprocess.Process] = {}


# ── WebSocket handler ────────────────────────────────────────────────────────
async def handle(websocket):
    session_id = id(websocket)
    print(f"[+] Client connected  (session {session_id})")

    # Default working directory is always the Archimedes project root
    session_cwd  = str(PROJECT_DIR)
    proc         = None
    temp_files   = []

    async def send(msg: dict):
        try:
            await websocket.send(json.dumps(msg))
        except Exception:
            pass

    try:
        async for raw in websocket:
            msg = json.loads(raw)
            kind = msg.get("type")

            # ── ping ────────────────────────────────────────────────────────
            if kind == "ping":
                await send({"type": "pong"})
                continue

            # ── set working directory ────────────────────────────────────────
            if kind == "set_cwd":
                path = os.path.expanduser(msg.get("path", "~"))
                if os.path.isdir(path):
                    session_cwd = path
                    await send({"type": "cwd", "path": session_cwd})
                else:
                    await send({"type": "error", "text": f"Directory not found: {path}"})
                continue

            # ── get cwd ──────────────────────────────────────────────────────
            if kind == "get_cwd":
                await send({"type": "cwd", "path": session_cwd})
                continue

            # ── send message to claude ────────────────────────────────────────
            if kind == "message":
                text        = msg.get("text", "").strip()
                attachments = msg.get("attachments", [])   # list of {name, mime, data_b64}

                if not text and not attachments:
                    continue

                # Write attachments to temp files and prepend their paths to the prompt
                attachment_refs = []
                for att in attachments:
                    suffix = mimetypes.guess_extension(att.get("mime", "")) or ""
                    tmp = tempfile.NamedTemporaryFile(
                        delete=False,
                        suffix=suffix,
                        prefix="archimedes_upload_"
                    )
                    tmp.write(base64.b64decode(att["data_b64"]))
                    tmp.close()
                    temp_files.append(tmp.name)
                    attachment_refs.append(tmp.name)

                # Build the full prompt
                if attachment_refs:
                    paths_str = " ".join(attachment_refs)
                    prompt = f"{paths_str}\n\n{text}" if text else paths_str
                else:
                    prompt = text

                await send({"type": "thinking"})

                # Stream claude output
                try:
                    proc = await asyncio.create_subprocess_exec(
                        CLAUDE,
                        "--print",
                        "--output-format", "stream-json",
                        "--verbose",
                        prompt,
                        cwd=session_cwd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )

                    full_text = ""
                    async for line in proc.stdout:
                        line = line.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        try:
                            evt = json.loads(line)
                        except json.JSONDecodeError:
                            # Plain text fallback
                            await send({"type": "delta", "text": line + "\n"})
                            full_text += line + "\n"
                            continue

                        etype = evt.get("type", "")

                        if etype == "assistant":
                            # Streamed assistant message
                            for block in evt.get("message", {}).get("content", []):
                                if block.get("type") == "text":
                                    chunk = block["text"]
                                    full_text += chunk
                                    await send({"type": "delta", "text": chunk})

                        elif etype == "result":
                            # Final result block
                            result_text = evt.get("result", "")
                            if result_text and result_text != full_text:
                                # Only send if we haven't already streamed it
                                if not full_text:
                                    full_text = result_text
                                    await send({"type": "delta", "text": result_text})

                        elif etype == "text":
                            chunk = evt.get("text", "")
                            full_text += chunk
                            await send({"type": "delta", "text": chunk})

                    await proc.wait()

                    # If nothing came through stdout, try stderr
                    if not full_text:
                        stderr_out = await proc.stderr.read()
                        err = stderr_out.decode("utf-8", errors="replace").strip()
                        if err:
                            await send({"type": "delta", "text": err})

                    await send({"type": "done"})

                except FileNotFoundError:
                    await send({"type": "error", "text": f"claude CLI not found at {CLAUDE}"})
                except Exception as e:
                    await send({"type": "error", "text": str(e)})
                finally:
                    # Clean temp files
                    for f in temp_files:
                        try:
                            os.unlink(f)
                        except Exception:
                            pass
                    temp_files.clear()
                    proc = None
                continue

            # ── interrupt running claude ─────────────────────────────────────
            if kind == "interrupt":
                if proc and proc.returncode is None:
                    proc.terminate()
                    await send({"type": "interrupted"})
                continue

    except websockets.exceptions.ConnectionClosedOK:
        pass
    except Exception as e:
        print(f"[!] Session {session_id} error: {e}")
    finally:
        if proc and proc.returncode is None:
            proc.terminate()
        for f in temp_files:
            try:
                os.unlink(f)
            except Exception:
                pass
        print(f"[-] Client disconnected (session {session_id})")


# ── Static file server (serves archimedes_chat.html) ─────────────────────────
class QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SERVE_DIR), **kwargs)

    def log_message(self, fmt, *args):
        pass   # suppress access logs


def run_http():
    server = HTTPServer(("127.0.0.1", HTTP_PORT), QuietHandler)
    server.serve_forever()


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    print(f"""
╔══════════════════════════════════════════════════════╗
║          Archimedes Chat Server                      ║
║  WebSocket : ws://localhost:{WS_PORT}                    ║
║  Interface : http://localhost:{HTTP_PORT}/archimedes_chat.html  ║
║  Press Ctrl+C to stop                                ║
╚══════════════════════════════════════════════════════╝
""")

    # Start HTTP server in background thread
    t = threading.Thread(target=run_http, daemon=True)
    t.start()

    # Open browser
    url = f"http://localhost:{HTTP_PORT}/archimedes_chat.html"
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    # Start WebSocket server
    async with websockets.serve(handle, "127.0.0.1", WS_PORT):
        await asyncio.Future()   # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[*] Server stopped.")
