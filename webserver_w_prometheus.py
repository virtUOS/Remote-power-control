#!/usr/bin/env python3

import http.server
import socketserver
import urllib.parse
import hashlib
import os
import time
import datetime
from zoneinfo import ZoneInfo
from periphery import GPIO
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
import base64

# total count of restarts
DEVICE_RESTART_TOTAL = Counter(
    "device_restart_total",
    "Total number of times the recorder has been restarted"
)

# Timestamp (epoch seconds) of the *last* restart
DEVICE_LAST_RESTART = Gauge(
    "device_last_restart_timestamp_seconds",
    "Unix timestamp of the most recent restart"
)

DEVICE_LAST_RESTART_INFO = Gauge(
    "device_last_restart_info",
    "Human‑readable timestamp of the most recent restart ",
    ["time"]
)


# Config
PIN = 55
GPIO_PIN = GPIO(PIN, "out")
GPIO_PIN.write(False)          

with open("config.txt", "r") as file:
    HOST = file.readline().strip()
    PORT = int(file.readline().strip())
    USERNAME = file.readline().strip()
    PASSWORD = file.readline().strip()
    METRICS_USERNAME = file.readline().strip()
    METRICS_PASSWORD = file.readline().strip()

# Simple token store (token -> expiry timestamp)
sessions = {}

#Metrics basic auth, base64 encodes/decodes text to ASCII
def check_basic_auth(headers):
    auth = headers.get("Authorization")
    if not auth:
        return False
    if not auth.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode()
        user, pw = decoded.split(":", 1)
        return hash_data(user) == METRICS_USERNAME and hash_data(pw) == METRICS_PASSWORD
    except:
        return False

def hash_data(data):
    return hashlib.sha3_256(data.encode()).hexdigest()

def generate_token():
    return hashlib.sha256(os.urandom(32)).hexdigest()

def is_valid_session(cookie_header):
    if not cookie_header:
        return False
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("token="):
            token = part[6:]
            if token in sessions and sessions[token] > time.time():
                return True
    return False

# Restart function 
def restart_capture_agent():
    # Record when the restart was requested
    now = time.time()
    DEVICE_LAST_RESTART.set(now)
    berlin_tz = ZoneInfo("Europe/Berlin")
    iso_time = datetime.datetime.fromtimestamp(now,tz=berlin_tz).isoformat()
    DEVICE_LAST_RESTART_INFO.labels(time=iso_time).set(1)

    # Increment the total‑restart counter
    DEVICE_RESTART_TOTAL.inc()

    GPIO_PIN.write(True)
   
    time.sleep(20)
    
    GPIO_PIN.write(False)

    return "Recorder is restarted!"

# HTML Pages
LOGIN_PAGE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login</title><style>
body{margin:0;background:#1a1a2e;display:flex;justify-content:center;
align-items:center;height:100vh;font-family:sans-serif;color:#eee}
.box{background:#16213e;padding:36px;border-radius:10px;width:280px}
h2{text-align:center;color:#e94560;margin:0 0 20px}
input{width:100%%;padding:10px;margin:0 0 12px;border:none;
border-radius:5px;background:#0f3460;color:#eee;box-sizing:border-box}
button{width:100%%;padding:10px;background:#e94560;border:none;
border-radius:5px;color:#fff;font-size:15px;cursor:pointer}
.err{background:#ff4444;padding:8px;border-radius:5px;
text-align:center;margin:0 0 12px;font-size:13px}
</style></head><body><div class="box"><h2>Login</h2>
%s
<form method="POST" action="/login">
<input name="username" placeholder="Username" required>
<input name="password" type="password" placeholder="Password" required>
<button type="submit">Sign In</button></form></div></body></html>"""

DASHBOARD_PAGE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard</title><style>
body{margin:0;background:#1a1a2e;display:flex;justify-content:center;
align-items:center;height:100vh;font-family:sans-serif;color:#eee}
.box{background:#16213e;padding:36px;border-radius:10px;
width:320px;text-align:center}
h2{color:#4ecca3;margin:0 0 24px}
#btn{padding:14px 36px;background:#4ecca3;border:none;border-radius:7px;
color:#1a1a2e;font-size:16px;font-weight:bold;cursor:pointer;
transition:background 0.3s}
#btn.active{background:#e94560;color:#fff}
#btn.active:hover{background:#c73652}
#res{margin:18px 0 0;padding:12px;background:#0f3460;border-radius:5px;
font-family:monospace;font-size:13px;display:none}
a{display:block;margin:18px 0 0;color:#e94560;font-size:13px}
</style></head><body><div class="box"><h2>Control Panel</h2>

<button id="btn" onclick="execute()">Restart</button>
<div id="res"></div>

%s
<a href="/logout">Logout</a></div>

<script>
function execute(){
    var btn = document.getElementById("btn");
    var res = document.getElementById("res");

    // clear previous result
    res.style.display = "none";
    res.textContent = "";

    // change colour & disable while restarting
    btn.classList.add("active");
    btn.disabled = true;
    btn.textContent = "Restarting...";

    // fire the POST request without a page reload
    fetch("/execute", {method: "POST"})
        .then(r => r.text())
        .then(text => {
            res.textContent = text;
            res.style.display = "block";
            btn.textContent = "Restart";
        });

    // Re‑enable after the 20 s restart window
    setTimeout(function(){
        btn.classList.remove("active");
        btn.disabled = false;
        btn.textContent = "Restart";
        res.style.display = "none";
    }, 20000);
}
</script>

</body></html>"""

# Handler
class Handler(http.server.BaseHTTPRequestHandler):
    
    def send_page(self, code, html):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def redirect(self, path, cookie=None):
        self.send_response(302)
        self.send_header("Location", path)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def do_GET(self):
        if self.path == "/metrics":
            if not check_basic_auth(self.headers):
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Metrics"')
                self.end_headers()
                return
            data = generate_latest()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(data)
            return
        
        logged_in = is_valid_session(self.headers.get("Cookie"))

        if self.path == "/dashboard":
            if not logged_in:
                return self.redirect("/")
            self.send_page(200, DASHBOARD_PAGE % "")

        elif self.path == "/logout":
            self.redirect("/", "token=; Max-Age=0")

        else:   
            if logged_in:
                return self.redirect("/dashboard")
            self.send_page(200, LOGIN_PAGE % "")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        params = urllib.parse.parse_qs(body)

        if self.path == "/login":
            user = params.get("username", [""])[0]
            pw   = params.get("password", [""])[0]
            if (hash_data(user) == USERNAME and
                hash_data(pw)   == PASSWORD):
                token = generate_token()
                sessions[token] = time.time() + 3600   # 1 hour session
                self.redirect("/dashboard",
                    f"token={token}; Path=/; Max-Age=3600")
            else:
                self.send_page(200,
                    LOGIN_PAGE % '<div class="err">Invalid credentials</div>')

        elif self.path == "/execute":
            if not is_valid_session(self.headers.get("Cookie")):
                return self.redirect("/")
            result = restart_capture_agent()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(result.encode())

        else:
            self.redirect("/")

    def log_message(self, fmt, *args):
        pass

def main():
    with socketserver.TCPServer((HOST, PORT), Handler) as s:
        print(f"Running on {HOST}:{PORT}")
        s.serve_forever()

if __name__ == "__main__":
    main()
