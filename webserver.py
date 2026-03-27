#!/usr/bin/env python3

import http.server
import socketserver
import urllib.parse
import hashlib
import os
import time
from periphery import GPIO

# Config
PIN = 55
GPIO_PIN = GPIO(PIN, "out")
GPIO_PIN.write(False)

with open("config.txt","r") as file:
    HOST = file.readline().strip()
    PORT = int(file.readline().strip())
    USERNAME = file.readline().strip()
    PASSWORD = file.read().strip()

# Simple token store (token -> expiry timestamp)
sessions = {}

def hash_data(data):
    data_hash = hashlib.sha3_256(data.encode())
    return data_hash.hexdigest()

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

# button restart function
def execute_action():
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

    // change color
    btn.classList.add("active");
    btn.disabled = true;
    btn.textContent = "Restarting...";

    // send request without reloading
    fetch("/execute", {method: "POST"})
        .then(function(r){ return r.text(); })
        .then(function(text){
            res.textContent = text;
            res.style.display = "block";
            btn.textContent = "Restart";
        });

    // revert after 20 seconds
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
        logged_in = is_valid_session(self.headers.get("Cookie"))

        if self.path == "/dashboard":
            if not logged_in:
                return self.redirect("/")
            self.send_page(200, DASHBOARD_PAGE % "")

        elif self.path == "/logout":
            self.redirect("/", "token=; Max-Age=0")

        else:  # "/" and everything else
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
            hashed_pw = hash_data(pw)
            hashed_user = hash_data(user)
            if hashed_user == USERNAME and hashed_pw == PASSWORD:
                token = generate_token()
                sessions[token] = time.time() + 3600  # 1h
                self.redirect("/dashboard",
                    f"token={token}; Path=/; Max-Age=3600")
            else:
                self.send_page(200, LOGIN_PAGE %
                    '<div class="err">Invalid credentials</div>')

        elif self.path == "/execute":
            if not is_valid_session(self.headers.get("Cookie")):
                return self.redirect("/")
            result = execute_action()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(result.encode())

        else:
            self.redirect("/")

    # suppress console log noise
    def log_message(self, fmt, *args):
        pass

def main():
    # starting server 
    with socketserver.TCPServer((HOST, PORT), Handler) as s:
        print(f"Running on {HOST}:{PORT}")
        s.serve_forever()

if __name__ == '__main__':
    main()

