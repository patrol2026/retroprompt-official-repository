
import os
import resource
import signal
import subprocess
import sys
import tempfile

from flask import Flask, request

app = Flask(__name__)
logger = app.logger


def _parse_mem(s):
    if not s:
        return None
    s = str(s).strip().lower()
    mult = 1
    if s.endswith("g"):
        mult, s = 1024 ** 3, s[:-1]
    elif s.endswith("m"):
        mult, s = 1024 ** 2, s[:-1]
    elif s.endswith("k"):
        mult, s = 1024, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def _preexec(mem_bytes):
    def _fn():
        os.setsid()
        if mem_bytes:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    return _fn


def _execute(
    code: str,
    lang: str = "python",
    stdin: str = "",
    version: str = None,
    timeout: int = 5,
    mem_limit: str = None,
    **kwargs,
):
    if lang != "python":
        raise ValueError(f"language '{lang}' is not supported by the local executor")

    mem_bytes = _parse_mem(mem_limit or os.environ.get("CODEEXEC_MEM_LIMIT"))

    with tempfile.TemporaryDirectory() as d:
        code_file = os.path.join(d, "code.py")
        with open(code_file, "w") as f:
            f.write(code)

        proc = subprocess.Popen(
            [sys.executable, "-u", code_file],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=_preexec(mem_bytes),
            cwd=d,
        )
        try:
            out, _ = proc.communicate(input=stdin.encode(), timeout=float(timeout))
            text = out.decode("utf-8", "replace")[:100000]
            return text + f"\nExit Code: {proc.returncode}\n"
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, _ = proc.communicate()
            text = (out.decode("utf-8", "replace") if out else "")[:100000]
            return text + "\nTimeout Error\n"


@app.route("/execute", methods=["POST"])
def execute():
    try:
        logger.info(f"Request: {request.json}")
        response = _execute(**request.json)
        logger.info(f"Response: {response}")
        return {"output": response}
    except ValueError as e:
        return {"error": str(e)}, 400
    except Exception as e:
        return {"error": str(e)}, 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5097, threaded=True)
