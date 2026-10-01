"""Ollama y SMTP aislados para probar los contenedores sin proveedores externos."""
import asyncio
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

mail_codes = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, data, content_type="application/json"):
        raw = data.encode() if isinstance(data, str) else json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/mail":
            self.send({"codes": mail_codes})
        else:
            self.send({"version": "test", "models": []})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body.get("format") == "json":
            content = json.dumps({"intent": "explorar", "profile": "", "codes": ["O12"], "zones": [],
                                  "queries": ["oportunidad O12 turismo"], "depth": "media"})
            message = {"role": "assistant", "content": content}
        elif body.get("tools") and not any(m.get("role") == "tool" for m in body["messages"]):
            message = {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "ver_ficha", "arguments": {"codigo": "O12"}}}]}
        else:
            message = {"role": "assistant", "content": "O12: respuesta de integración con la guía de Invest Lavalleja."}
        result = {"model": body["model"], "created_at": "2026-10-01T00:00:00Z", "message": message, "done": True,
                  "done_reason": "stop", "total_duration": 1, "load_duration": 1, "prompt_eval_count": 1,
                  "prompt_eval_duration": 1, "eval_count": 1, "eval_duration": 1}
        if body.get("stream"):
            # Un mensaje de contenido/herramienta y un cierre, como Ollama NDJSON.
            first = {**result, "done": False}
            final = {**result, "message": {"role": "assistant", "content": ""}}
            self.send(json.dumps(first) + "\n" + json.dumps(final) + "\n", "application/x-ndjson")
        else:
            self.send(result)


async def smtp(reader, writer):
    async def answer(text):
        writer.write((text + "\r\n").encode())
        await writer.drain()
    await answer("220 local-test SMTP")
    try:
        while line := await reader.readline():
            command = line.decode().strip().upper()
            if command.startswith(("EHLO", "HELO")):
                await answer("250 local-test")
            elif command == "DATA":
                await answer("354 End with dot")
                data = bytearray()
                while part := await reader.readline():
                    if part == b".\r\n": break
                    data.extend(part)
                if code := re.search(rb"Tu c[o\xc3\xb3]+digo de acceso es: (\d{6})", data):
                    mail_codes.append(code.group(1).decode())
                else:
                    # SMTP puede usar quoted-printable para los caracteres UTF-8.
                    import email
                    message = email.message_from_bytes(bytes(data))
                    content = message.get_payload(decode=True).decode("utf-8")
                    mail_codes.append(re.search(r"acceso es: (\d{6})", content).group(1))
                await answer("250 queued locally")
            elif command == "QUIT":
                await answer("221 bye")
                break
            else:
                await answer("250 OK")
    finally:
        writer.close()
        await writer.wait_closed()


async def main():
    threading.Thread(target=ThreadingHTTPServer(("0.0.0.0", 11434), Handler).serve_forever, daemon=True).start()
    server = await asyncio.start_server(smtp, "0.0.0.0", 1025)
    async with server:
        await server.serve_forever()


asyncio.run(main())
