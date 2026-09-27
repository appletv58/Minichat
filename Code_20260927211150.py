# -*- coding: utf-8 -*-
"""
MiniChat 単体版（このファイル1つだけで動きます）

追加ライブラリ不要。画面もアイコンも全部この中に入っています。

  * 合言葉（パスワード）付きの部屋
  * 写真の送受信
  * 同じ人は同じアカウントのまま（再接続しても名前が変わらない）

起動:  python minichat.py
"""
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

PORT = int(os.environ.get("PORT", 8888))
HISTORY_MAX = 200
IMAGE_MAX = 900 * 1024      # 1枚あたりの上限（base64文字数・約900KB）
IMAGE_KEEP = 25             # 履歴に残す画像の枚数（サーバーのメモリを 25MB 以下に保つため）
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

clients = {}        # {socket: nick}
sock_cid = {}       # {socket: client_id}
known = {}          # {client_id: nick}  同じ人を記憶する
lock = threading.Lock()
history = deque(maxlen=HISTORY_MAX)

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, maximum-scale=1">
<title>MiniChat</title>
<meta name="theme-color" content="#0f1115">
<link rel="manifest" href="/manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="MiniChat">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="icon" href="/icon-192.png">
<style>
  :root{
    --bg:#0f1115; --panel:#171a21; --line:#262b36;
    --me:#2f6fed; --other:#232733; --txt:#e8eaed; --sub:#9aa3b2;
  }
  *{box-sizing:border-box; -webkit-tap-highlight-color:transparent}
  html,body{height:100%}
  body{
    margin:0; background:var(--bg); color:var(--txt);
    font:15px/1.5 -apple-system,"Hiragino Sans","Noto Sans JP",system-ui,sans-serif;
    display:flex; flex-direction:column;
  }
  header{
    padding:10px 14px; background:var(--panel); border-bottom:1px solid var(--line);
    display:flex; align-items:center; gap:8px; position:sticky; top:0; z-index:5;
    padding-top:calc(10px + env(safe-area-inset-top));
  }
  header h1{font-size:16px; margin:0; font-weight:600}
  #status{font-size:12px; color:var(--sub)}
  #me{
    font-size:12px; font-weight:600; padding:3px 10px; border-radius:12px;
    background:var(--other); cursor:pointer; max-width:34%;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  }
  #users{
    font-size:12px; color:var(--sub); margin-left:auto; text-align:right;
    max-width:38%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  }

  #gate{
    position:fixed; inset:0; background:var(--bg); z-index:20;
    display:flex; align-items:center; justify-content:center; padding:20px;
    overflow-y:auto;
  }
  #gate .box{width:100%; max-width:360px; text-align:center}
  #gate h2{margin:0 0 6px; font-size:22px}
  #gate p{margin:0 0 16px; color:var(--sub); font-size:13px}
  #gate input{
    width:100%; padding:12px 14px; border-radius:12px; font-size:16px; margin-bottom:8px;
    border:1px solid var(--line); background:var(--panel); color:var(--txt);
  }
  #gate button{width:100%; margin-top:10px; padding:12px}
  #err{color:#ff6b6b; font-size:13px; min-height:18px}
  #again{font-size:12px; color:var(--sub); margin-top:10px; display:none}
  #again span{color:#8ab4f8; text-decoration:underline; cursor:pointer}

  #log{
    flex:1; overflow-y:auto; padding:14px; display:flex; flex-direction:column; gap:10px;
    -webkit-overflow-scrolling:touch;
  }
  .row{display:flex; gap:8px; max-width:86%; align-items:flex-end}
  .row.me{flex-direction:row-reverse; align-self:flex-end}
  .row.other{align-self:flex-start}
  .av{
    width:32px; height:32px; border-radius:50%; flex:none;
    display:flex; align-items:center; justify-content:center;
    font-size:13px; font-weight:700; color:#fff; margin-bottom:16px;
  }
  .col{display:flex; flex-direction:column; max-width:calc(100% - 42px)}
  .me .col{align-items:flex-end}
  .who{font-size:11px; color:var(--sub); margin:0 4px 3px}
  .bubble{
    padding:9px 13px; border-radius:16px; word-break:break-word;
    white-space:pre-wrap; font-size:15px;
  }
  .me .bubble{background:var(--me); border-bottom-right-radius:4px}
  .other .bubble{background:var(--other); border-bottom-left-radius:4px}
  .bubble.img{padding:3px; background:var(--other); line-height:0}
  .me .bubble.img{background:var(--me)}
  .bubble.img img{
    width:100%; max-width:220px; border-radius:13px; display:block; cursor:pointer;
  }
  .time{font-size:10px; color:#6b7280; margin:3px 6px 0}
  .sys{
    align-self:center; font-size:11px; color:var(--sub);
    background:var(--panel); padding:3px 10px; border-radius:10px;
  }

  form{
    display:flex; gap:7px; padding:9px 10px; background:var(--panel);
    border-top:1px solid var(--line); align-items:center;
    padding-bottom:calc(9px + env(safe-area-inset-bottom));
  }
  #pic{
    flex:none; width:42px; height:42px; border-radius:50%; border:0;
    background:var(--other); color:var(--txt); font-size:19px; padding:0;
    display:flex; align-items:center; justify-content:center; cursor:pointer;
  }
  #text{
    flex:1; padding:11px 14px; border-radius:20px; font-size:16px;
    border:1px solid var(--line); background:#11141a; color:var(--txt);
  }
  #text:focus{outline:none; border-color:var(--me)}
  #send{
    flex:none; padding:11px 16px; border:0; border-radius:20px;
    font-size:15px; font-weight:600; background:var(--me); color:#fff; cursor:pointer;
  }
  button:active{opacity:.75}
  button:disabled{opacity:.4; cursor:not-allowed}
  button.ghost{background:transparent; border:1px solid var(--line); color:var(--sub); font-weight:400}

  #lightbox{
    position:fixed; inset:0; background:rgba(0,0,0,.92); z-index:50; display:none;
    align-items:center; justify-content:center; padding:16px; cursor:pointer;
  }
  #lightbox img{max-width:100%; max-height:100%; border-radius:8px}
  #lightbox.show{display:flex}

  #sending{
    position:fixed; left:50%; bottom:80px; transform:translateX(-50%);
    background:#000c; border-radius:14px; padding:8px 16px; font-size:13px;
    z-index:40; display:none;
  }
</style>
</head>
<body>

<header>
  <h1>MiniChat</h1>
  <span id="status">接続中…</span>
  <span id="me" style="display:none" title="名前を変える"></span>
  <span id="users"></span>
</header>

<div id="log"></div>

<form id="form" autocomplete="off">
  <button id="pic" type="button" title="写真を送る">📷</button>
  <input id="text" placeholder="メッセージ…" maxlength="2000" disabled>
  <button id="send" type="submit" disabled>送信</button>
</form>
<input id="file" type="file" accept="image/*" style="display:none">

<div id="gate">
  <div class="box">
    <h2>MiniChat へようこそ</h2>
    <p id="gatesub">ニックネームと合言葉を入れてください</p>
    <input id="nick" placeholder="名前（例）たろう" maxlength="20" autocomplete="off">
    <input id="pass" type="password" placeholder="合言葉" autocomplete="off">
    <div id="err"></div>
    <button id="enter" type="button">参加する</button>
    <div id="again">別の名前で参加する場合は<span id="reset">こちら</span></div>
    <button id="install" type="button" class="ghost" style="display:none">📱 ホーム画面に追加</button>
    <p id="ioshint" style="display:none;margin-top:14px">
      iPhoneの方：Safari下の「共有」→「ホーム画面に追加」でアプリになります
    </p>
  </div>
</div>

<div id="lightbox"><img id="lbimg" alt=""></div>
<div id="sending">送信中…</div>

<script>
const $ = id => document.getElementById(id);
const log = $('log'), form = $('form'), text = $('text'), send = $('send');
const gate = $('gate'), nickInput = $('nick'), passInput = $('pass');
const statusEl = $('status'), usersEl = $('users'), errEl = $('err');

/* ---------- アカウントの記憶（同じ人として扱うため） ---------- */
const KEY_ID = 'mc_cid', KEY_NICK = 'mc_nick', KEY_PASS = 'mc_pass';

function getCID(){
  let v = null;
  try { v = localStorage.getItem(KEY_ID); } catch(e) {}
  if (!v){
    v = 'c' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    try { localStorage.setItem(KEY_ID, v); } catch(e) {}
  }
  return v;
}
const CID = getCID();

let savedNick = null, savedPass = null;
try {
  savedNick = localStorage.getItem(KEY_NICK);
  savedPass = localStorage.getItem(KEY_PASS);
} catch(e) {}

let ws = null, myNick = null, myPass = null, retry = 0, heartbeat = null;
let autoJoined = false;

if (savedNick){
  nickInput.value = savedNick;
  $('again').style.display = 'block';
}
if (savedPass) passInput.value = savedPass;

function clearAccount(){
  try {
    localStorage.removeItem(KEY_NICK);
    localStorage.removeItem(KEY_PASS);
    localStorage.removeItem(KEY_ID);
  } catch(e) {}
  location.reload();
}
$('reset').addEventListener('click', clearAccount);

/* ---------- 色（同じ名前なら常に同じ色） ---------- */
function colorFor(name){
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
  return 'hsl(' + h + ',58%,52%)';
}

function connect(){
  statusEl.textContent = '接続中…';
  ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');

  ws.onopen = () => {
    retry = 0;
    statusEl.textContent = '接続OK';
    // 保存済みなら自動で入室し直す（毎回入力しなくていい）
    if (savedNick && savedPass){
      myNick = savedNick; myPass = savedPass; autoJoined = true;
      ws.send(JSON.stringify({type:'join', nick:savedNick, pass:savedPass, cid:CID}));
    } else if (myNick){
      ws.send(JSON.stringify({type:'join', nick:myNick, pass:myPass || '', cid:CID}));
    }
    clearInterval(heartbeat);
    heartbeat = setInterval(() => {
      if (ws && ws.readyState === 1) ws.send(JSON.stringify({type:'ping'}));
    }, 25000);
  };

  ws.onclose = () => {
    statusEl.textContent = '切断（再接続中…）';
    text.disabled = send.disabled = true;
    clearInterval(heartbeat);
    retry++;
    setTimeout(connect, Math.min(retry * 1000, 8000));
  };

  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.type === 'welcome'){
      myNick = m.nick;
      try {
        localStorage.setItem(KEY_NICK, myNick);
        if (myPass) localStorage.setItem(KEY_PASS, myPass);
        localStorage.setItem(KEY_ID, m.cid || CID);
      } catch(err) {}
      gate.style.display = 'none';
      clearTimeout(gateTimer);
      errEl.textContent = '';
      const meEl = $('me');
      meEl.textContent = myNick;
      meEl.style.background = colorFor(myNick);
      meEl.style.display = 'block';
      text.disabled = send.disabled = false;
      log.innerHTML = '';
      m.history.forEach(add);
      usersEl.textContent = m.users.join('、');
      scroll();
    } else if (m.type === 'denied'){
      errEl.textContent = '合言葉が違います';
      gate.style.display = 'flex';
      $('again').style.display = 'block';
      passInput.value = '';
      passInput.focus();
      try { localStorage.removeItem(KEY_PASS); } catch(err) {}
      savedPass = null; myPass = null;
    } else if (m.type === 'say' || m.type === 'system' || m.type === 'image'){
      add(m); scroll();
    } else if (m.type === 'users'){
      usersEl.textContent = m.users.join('、');
    }
  };
}

function add(m){
  const el = document.createElement('div');
  if (m.type === 'system'){
    el.className = 'sys';
    el.textContent = m.text;
  } else if (m.type === 'image'){
    const mine = m.nick === myNick;
    el.className = 'row ' + (mine ? 'me' : 'other');
    const av = document.createElement('div');
    av.className = 'av';
    av.style.background = colorFor(m.nick);
    av.textContent = (m.nick || '?').slice(0, 1);
    const col = document.createElement('div');
    col.className = 'col';
    const who = document.createElement('div');
    who.className = 'who';
    who.textContent = mine ? '自分' : m.nick;
    const bub = document.createElement('div');
    bub.className = 'bubble img';
    const img = document.createElement('img');
    img.src = m.data;
    img.alt = '画像';
    img.addEventListener('click', () => {
      $('lbimg').src = m.data;
      $('lightbox').classList.add('show');
    });
    bub.appendChild(img);
    const tm = document.createElement('div');
    tm.className = 'time';
    tm.textContent = m.time || '';
    col.appendChild(who); col.appendChild(bub); col.appendChild(tm);
    el.appendChild(av); el.appendChild(col);
  } else {
    const mine = m.nick === myNick;
    el.className = 'row ' + (mine ? 'me' : 'other');
    const av = document.createElement('div');
    av.className = 'av';
    av.style.background = colorFor(m.nick);
    av.textContent = (m.nick || '?').slice(0, 1);
    const col = document.createElement('div');
    col.className = 'col';
    const who = document.createElement('div');
    who.className = 'who';
    who.textContent = mine ? '自分' : m.nick;
    const bub = document.createElement('div');
    bub.className = 'bubble';
    bub.textContent = m.text;
    const tm = document.createElement('div');
    tm.className = 'time';
    tm.textContent = m.time || '';
    col.appendChild(who); col.appendChild(bub); col.appendChild(tm);
    el.appendChild(av); el.appendChild(col);
  }
  log.appendChild(el);
}

function scroll(){ log.scrollTop = log.scrollHeight; }

form.addEventListener('submit', e => {
  e.preventDefault();
  const t = text.value.trim();
  if (!t || !ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({type:'say', text:t}));
  text.value = '';
});

/* ---------- 画像送信 ---------- */
$('pic').addEventListener('click', () => $('file').click());
$('file').addEventListener('change', async e => {
  const f = e.target.files && e.target.files[0];
  e.target.value = '';
  if (!f) return;
  if (!ws || ws.readyState !== 1) return;
  if (f.size > 25 * 1024 * 1024){ alert('写真が大きすぎます（25MBまで）'); return; }

  $('sending').style.display = 'block';
  try {
    const data = await shrink(f);
    ws.send(JSON.stringify({type:'image', data:data}));
  } catch(err) {
    alert('この写真は送れませんでした');
  }
  $('sending').style.display = 'none';
});

/* 25MB の大きな写真も、送れる大きさまで自動で圧縮する */
function shrink(file){
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onerror = () => reject(new Error('read'));
    fr.onload = () => {
      const im = new Image();
      im.onerror = () => reject(new Error('decode'));
      im.onload = () => {
        try {
          // 大きすぎる画像は段階的に縮小（iPhone の巨大写真対策）
          let src = im;
          let sw = im.width, sh = im.height;
          while (sw * sh > 20 * 1000 * 1000){
            const step = document.createElement('canvas');
            step.width = Math.max(1, Math.round(sw / 2));
            step.height = Math.max(1, Math.round(sh / 2));
            step.getContext('2d').drawImage(src, 0, 0, step.width, step.height);
            src = step; sw = step.width; sh = step.height;
          }

          const TARGET = 700 * 1024;   // 送るサイズの目安
          let maxSide = 1600, q = 0.78, out = '';
          for (let i = 0; i < 7; i++){
            const s = Math.min(1, maxSide / Math.max(sw, sh));
            const w = Math.max(1, Math.round(sw * s));
            const h = Math.max(1, Math.round(sh * s));
            const cv = document.createElement('canvas');
            cv.width = w; cv.height = h;
            const cx = cv.getContext('2d');
            cx.fillStyle = '#fff'; cx.fillRect(0, 0, w, h);
            cx.drawImage(src, 0, 0, w, h);
            out = cv.toDataURL('image/jpeg', q);
            if (out.length <= TARGET) break;
            maxSide = Math.round(maxSide * 0.75);
            q = Math.max(0.42, q - 0.1);
          }
          resolve(out);
        } catch(err){
          reject(err);
        }
      };
      im.src = fr.result;
    };
    fr.readAsDataURL(file);
  });
}

$('lightbox').addEventListener('click', () => $('lightbox').classList.remove('show'));

/* ---------- 入室 ---------- */
function enter(){
  const n = nickInput.value.trim();
  const p = passInput.value;
  if (!n) { nickInput.focus(); return; }
  if (!p) { errEl.textContent = '合言葉を入れてください'; passInput.focus(); return; }
  myNick = n; myPass = p;
  errEl.textContent = '';
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({type:'join', nick:n, pass:p, cid:CID}));
  else connect();
}
$('enter').addEventListener('click', enter);
[nickInput, passInput].forEach(el => {
  el.addEventListener('keydown', e => { if (e.key === 'Enter') enter(); });
});

/* ---------- PWA ---------- */
if ('serviceWorker' in navigator){
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
let deferredPrompt = null;
const installBtn = $('install');
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  deferredPrompt = e;
  installBtn.style.display = 'block';
});
installBtn.addEventListener('click', async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  await deferredPrompt.userChoice;
  deferredPrompt = null;
  installBtn.style.display = 'none';
});
const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent) && !window.MSStream;
const isStandalone = window.navigator.standalone === true ||
                     window.matchMedia('(display-mode: standalone)').matches;
if (isIOS && !isStandalone) $('ioshint').style.display = 'block';

/* ---------- 自動で入り直す ---------- */
let gateTimer = null;
// 6秒たっても入室できなければ、入力画面を出す（固まって見えるのを防ぐ）
gateTimer = setTimeout(() => {
  if (!$('me').style.display || $('me').style.display === 'none'){
    gate.style.display = 'flex';
  }
}, 6000);

// ヘッダーの名前をタップ → 名前を変える画面
$('me').addEventListener('click', () => {
  nickInput.value = myNick || '';
  gate.style.display = 'flex';
  $('again').style.display = 'block';
});

connect();
// 保存済みなら gate を出さずに待つ（拒否されたら自動で出る）
if (savedNick && savedPass) gate.style.display = 'none';
</script>
</body>
</html>
"""

SW_JS = r"""const CACHE = 'minichat-v3';
const SHELL = ['/', '/manifest.json', '/icon-192.png', '/icon-512.png', '/apple-touch-icon.png'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  if (new URL(req.url).pathname === '/ws') return;
  e.respondWith(
    fetch(req).then(res => {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
      return res;
    }).catch(() => caches.match(req).then(r => r || caches.match('/')))
  );
});
"""

MANIFEST = r"""{
  "name": "MiniChat",
  "short_name": "MiniChat",
  "description": "MiniChat - simple realtime chat",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "orientation": "portrait",
  "background_color": "#0f1115",
  "theme_color": "#0f1115",
  "lang": "ja",
  "icons": [
    {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
    {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
    {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
  ]
}
"""

ICON_192 = "iVBORw0KGgoAAAANSUhEUgAAAMAAAADACAYAAABS3GwHAAAE2UlEQVR4nO3d23XbVhCGUUgrFUSFOJ05pUSdRYU4LTgPkRxa5gV3YObf+9mGsHDmwwEpLvFpOJkvX799P/oc2M7b68vT0edw6dCTMewMw7FR7P6DDT337B3Dbj/M4DPFXiFs/kMMPktsHcJmBzf4rGmrEFY/qMFnS2uH8LzmwQw/W1t7xlapyeBzhDV2g8U7gOHnKGvM3qIADD9HWzqDswMw/JzFklmcFYDh52zmzuTkAAw/ZzVnNicFYPg5u6kzOjoAw08VU2Z1VACGn2rGzuzDAAw/VY2Z3VU/CgHV3A3A3Z/qHs3wzQAMP13cm2WPQES7GoC7P93cmmk7ANF+CcDdn66uzbYdgGg/BeDuT3efZ9wOQLQfAbj7k+Jy1u0ARBMA0Z6HweMPeT5m3g5ANAEQTQBEEwDRnrwAJpkdgGgCIJoAiPbb0Sewh7//+v3oUyjrjz//OfoUNtX2RbChX1/HGNoFYPC31ymEVq8BDP8+Ol3nFjtApwWppvpuUH4HMPzHqn79SwdQ/eJ3UXkdygZQ+aJ3VHU9ygYAaygZQNW7TXcV16VcABUvcpJq61MuAFhTqQCq3V1SVVqnUgHA2gRAtDIBVNpWqbNeZQKALQiAaAIgmgCIJgCiCYBoAiCaAIgmAKIJgGgCIJoAiCYAogmAaAIgmgCIJgCiCYBoAiCaAIgmAKIJgGgR3xI5x7VvPlnzT31UP34XZb4iaa/FG/OVP0vOpfrxp6jw9UkegS6MXbC5C1v9+B0J4N3UoUj7910JgGgCGM77yHGW43cmAKIJgGgCIJoAiCaAYf4vhsb+v+rH70wARBPAu6l3w7R/35UALpzlkeOsx+/Ih+FuqP5pzTN8GrTCL9oEwGYqBOARiGgCIJoAiCYAogmAaAIgmgCIJgCiCYBoAiCaAIgmAKIJgGgCIJoAiCYAogmAaAIgmgCIJgCiCYBoAiCaAIgmAKIJgGgCIFqZACr8mT3+V2W9ygQAWxAA0UoFUGVbTVdpnUoFAGsrF0Clu0uiautTLoBhqHeRU1Rcl5IBwFrKBlDxbtNZ1fUoG8Aw1L3o3VReh9IBDEPti99B9etf5lsix/BNkvupPvgfyu8Al7osytl1us6tdoBLdoP1dRr8D20DuCSG+ToO/aWIAB5ZGkj3Iems1WuAIxj+2gRANAEs4O5fnwBmMvw9CGAGw9+HACYy/L0IYALD348AiCaAkdz9exLACIa/LwE8YPh7E8Adhr8/Adxg+DMI4ArDn0MARBPAJ+7+WQRwwfDnEcA7w59JAIPhTyYAoj2/vb48HX0ScIS315cnOwDRBEA0ARBNAER7Hob/XgwcfSKwp4+ZtwMQTQBE+xGAxyBSXM66HYBoPwVgF6C7zzNuByDaLwHYBejq2mzbAYh2NQC7AN3cmmk7ANFuBmAXoIt7s3x3BxAB1T2aYY9ARHsYgF2AqsbM7qgdQARUM3ZmRz8CiYAqpszqpNcAIuDsps7o5BfBIuCs5szmrHeBRMDZzJ3J2W+DioCzWDKLi34PIAKOtnQGF/8iTAQcZY3ZW3V4v3z99n3N48E1a950V/0ohN2Ara09Y5sNrN2ANW11c938ji0Eltj6qWK3RxYhMMVej9O7P7MLgXv2fh156ItWMTAMx755crp3bUTR29neKfwXTDOfNJhdp/sAAAAASUVORK5CYII="
ICON_512 = "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"
APPLE_ICON = "iVBORw0KGgoAAAANSUhEUgAAALQAAAC0CAYAAAA9zQYyAAAEm0lEQVR4nO3d7VEkNxSGUUE5AhMIzgyHYjIzgeAU8A+bLZadj+7p1rTuq3N+bwmV+uGOYGqZhzaA55f3j6P3wHZvr08PR+/hkA0IeA5HBH63Lyjiud0r7q5fRMSc0jPuLgsLmSV6hP2494JiZqkerez2HSJktthrWu8yocXMVns1tOm7Qsj0sGVa3zyhxUwvW9q6KWgx09utja0OWszcyy2trQpazNzb2uYWBy1mjrKmvUVBi5mjLW3watBiZhRLWtz9rW840sWgTWdGc63Js0GLmVFdatOVgygngzadGd25Rn8JWsxUcapVVw6i/BS06Uw135s1oYkiaKL8CNp1g6q+tmtCE0XQRHlszXWD+j4bNqGJImiiCJooD+7PJDGhiSJoogiaKIImym9Hb6CXv//6/egtDO+PP/85egu7i/oth4hvlxJ3RNBC3k/1sMvfocW8r+rnWTro6oc/qsrnWjboyodeQdXzLRl01cOupuI5lwu64iFXVu28SwVd7XBTVDr3MkFXOtREVc6/TNCwRImgq0yHdBWeQ4mgYSlBE2X4oCu8zM1k9OcxfNCwhqCJImiiCJoogiaKoIkiaKIImiiCJoqgiSJoogiaKIImiqCJImiiCJoogiaKoIkiaKIImiiCJkrsZ6ysceqv1u/1v5t7rd1zz5VNP6HPfQTDHh/N0GvtnnuubuqgrwWwJZBea/fcc4Jpg1764G8JpNfaPfecYsqge4XUc+2ee04yZdDkEjRRBE0UQRNlyqDXvgGx5t/3WrvnnpNMGXRr/ULquXbPPaeYNujWrj/4LWH0WrvnnhNMHXRr5wPYI4xea/fcc3UPzy/vH0dv4hIPaTwjv2kz/YQmi6CJImiiCJoogiaKoIkiaKIImiiCJoqgiSJoogiaKIImiqCJImiiCJoogiaKoIkiaKIImiiCJoqgiSJoogiaKIImyvBBj/xXemY0+vMYPmhYQ9BEKRH06C9zs6jwHEoEDUuVCbrCdEhW5fzLBN1anUNNU+ncSwXdWq3DTVDtvMsF3Vq9Q66q4jmXDLq1moddSdXzLRt0a3UPfXSVz7V00K3VPvwRVT/P4T8Faw2fmHW76iF/igr6K3FflxLxV7FBX7Il9sQIkpS/Q9+TmMcn6IXEXIOgFxBzHYK+Qsy1CJoogr7AdK5H0GeIuSZBnyDmugT9jZhrEzRRBP2F6VyfoP8n5gyCbmJOMn3QYs4yfdBkmTpo0znPtEGLOdOUQYs515RBk+vx7fXp4ehNwB7eXp8eTGiiCJoogibKY2v/3T2O3ghs8dmwCU0UQRPlR9CuHVT1tV0TmiiCJspPQbt2UM33Zk1oovwStClNFadaPTmhRc3ozjXqykGUs0Gb0ozqUpsXJ7SoGc21Jl05iHI1aFOaUSxpcdGEFjVHW9rg4iuHqDnKmvZW3aFFzb2tbW71D4Wi5l5uae2m33KImt5ubezmX9uJml62tLVLlM8v7x97rMPc9hiSu7yxYlqz1V4N7R6iac0aew/D3d/6Nq1ZqkcrXeMzrTml59C72zQV99zu9cp9yPVA3HM44vo5xH1X4BlG+PnpX10bfWxWni+KAAAAAElFTkSuQmCC"


# ---------------- 合言葉 ----------------

def setup_passphrase():
    if "MINICHAT_PASS" in os.environ:
        return os.environ.get("MINICHAT_PASS", "").strip()
    try:
        if sys.stdin and sys.stdin.isatty():
            print("-" * 52)
            print("  この部屋の「合言葉」を決めてください。")
            print("  例: hanabi2026      ※空のままなら合言葉なし")
            print("-" * 52)
            return input("  合言葉 > ").strip()
    except Exception:
        pass
    return ""


PASSPHRASE = ""


# ---------------- 基本の道具 ----------------

def now_hm():
    return time.strftime("%H:%M")


def roster():
    with lock:
        return sorted(clients.values())


def ws_send(sock, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    n = len(data)
    head = b"\x81"
    if n < 126:
        head += struct.pack("!B", n)
    elif n < 65536:
        head += struct.pack("!BH", 126, n)
    else:
        head += struct.pack("!BQ", 127, n)
    try:
        sock.sendall(head + data)
        return True
    except Exception:
        return False


def ws_recv(sock):
    def rd(n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    b1, b2 = rd(2)
    opcode = b1 & 0x0F
    masked = b2 & 0x80
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", rd(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", rd(8))[0]
    mask = rd(4) if masked else b""
    data = rd(length) if length else b""
    if masked:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return opcode, data


def broadcast(payload, except_sock=None):
    with lock:
        socks = list(clients.keys())
    dead = []
    for s in socks:
        if s is except_sock:
            continue
        if not ws_send(s, payload):
            dead.append(s)
    if dead:
        with lock:
            for s in dead:
                clients.pop(s, None)
                sock_cid.pop(s, None)


def trim_images():
    """履歴に残る画像が多くなりすぎないように、古いものから削る"""
    idx = [i for i, m in enumerate(history) if m.get("type") == "image"]
    while len(idx) > IMAGE_KEEP:
        i = idx.pop(0)
        try:
            del history[i]
        except Exception:
            pass
        idx = [j - 1 if j > i else j for j in idx]


# ---------------- メッセージ処理 ----------------

def handle(sock, msg):
    kind = msg.get("type")

    if kind == "ping":
        return

    if kind == "join":
        if PASSPHRASE and (msg.get("pass") or "") != PASSPHRASE:
            ws_send(sock, {"type": "denied"})
            print("  [!] 合言葉が違う入室をブロックしました")
            return

        cid = (msg.get("cid") or "").strip()[:64]
        want = (msg.get("nick") or "").strip()[:20] or "名無し"

        with lock:
            # 同じ人が繋ぎ直した時は、前と同じ名前を使う（2が付かない）
            if cid and cid in known:
                nick = known[cid]
                # 名前欄を書き換えていたら「改名」とみなす
                if want and want != nick:
                    if want not in clients.values():
                        nick = want
                        known[cid] = nick
            else:
                nick = want
                base, i = nick, 2
                while nick in clients.values():
                    nick = "%s%d" % (base, i)
                    i += 1
                if cid:
                    known[cid] = nick

            # 同じ人が二重に繋いでいたら、古い方を切る
            old = None
            for s, c in list(sock_cid.items()):
                if c == cid and s is not sock:
                    old = s
                    break
            if old is not None:
                clients.pop(old, None)
                sock_cid.pop(old, None)
                try:
                    old.close()
                except Exception:
                    pass

            clients[sock] = nick
            if cid:
                sock_cid[sock] = cid

        ws_send(sock, {"type": "welcome", "nick": nick, "cid": cid,
                       "history": list(history), "users": roster()})
        broadcast({"type": "users", "users": roster()})
        notice = {"type": "system", "text": "%s さんが入室しました" % nick,
                  "time": now_hm()}
        history.append(notice)
        broadcast(notice)
        print("  [+] %s が入室（現在 %d 人）" % (nick, len(clients)))
        return

    with lock:
        nick = clients.get(sock)
    if not nick:
        return

    if kind == "say":
        text = (msg.get("text") or "").strip()
        if not text:
            return
        if len(text) > 2000:
            text = text[:2000]
        payload = {"type": "say", "nick": nick, "text": text, "time": now_hm()}
        history.append(payload)
        broadcast(payload)
        return

    if kind == "image":
        data = (msg.get("data") or "").strip()
        if not data.startswith("data:image/"):
            return
        if len(data) > IMAGE_MAX:
            ws_send(sock, {"type": "system", "text": "写真が大きすぎます",
                           "time": now_hm()})
            return
        payload = {"type": "image", "nick": nick, "data": data,
                   "time": now_hm()}
        history.append(payload)
        trim_images()
        broadcast(payload)
        print("  [pic] %s が写真を送信" % nick)
        return


def chat_loop(sock):
    try:
        while True:
            opcode, data = ws_recv(sock)
            if opcode == 0x8:
                break
            if opcode == 0x9:
                try:
                    sock.sendall(b"\x8a\x00")
                except Exception:
                    pass
                continue
            if opcode != 0x1:
                continue
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            handle(sock, msg)
    except Exception:
        pass
    finally:
        with lock:
            nick = clients.pop(sock, None)
            sock_cid.pop(sock, None)
        try:
            sock.close()
        except Exception:
            pass
        if nick:
            broadcast({"type": "users", "users": roster()})
            notice = {"type": "system",
                      "text": "%s さんが退出しました" % nick, "time": now_hm()}
            history.append(notice)
            broadcast(notice)
            print("  [-] %s が退出（現在 %d 人）" % (nick, len(clients)))


# ---------------- HTTP ----------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MiniChat"

    def log_message(self, fmt, *args):
        pass

    def reply(self, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if "://" in path:
            try:
                path = urlsplit(path).path or "/"
            except Exception:
                path = "/"
        if not path.startswith("/"):
            path = "/" + path

        if path.rstrip("/") == "/ws":
            self.upgrade_ws()
            return

        name = os.path.basename(path.rstrip("/"))
        if name in ("", "index.html", "index.htm"):
            return self.reply("text/html; charset=utf-8", INDEX_HTML)
        if name == "manifest.json":
            return self.reply("application/json; charset=utf-8", MANIFEST)
        if name == "sw.js":
            return self.reply("text/javascript; charset=utf-8", SW_JS)
        if name == "icon-192.png":
            return self.reply("image/png", base64.b64decode(ICON_192))
        if name == "icon-512.png":
            return self.reply("image/png", base64.b64decode(ICON_512))
        if name in ("apple-touch-icon.png", "favicon.ico"):
            return self.reply("image/png", base64.b64decode(APPLE_ICON))
        return self.reply("text/html; charset=utf-8", INDEX_HTML)

    def upgrade_ws(self):
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_error(400)
            return
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        self.wfile.write((
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode())
        self.wfile.flush()
        self.close_connection = True
        chat_loop(self.connection)


# ---------------- ネットワーク ----------------

def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def all_ips():
    ips = []
    try:
        import subprocess
        out = subprocess.run(["ipconfig"], capture_output=True, text=True,
                             shell=True).stdout
        for line in out.splitlines():
            if "IPv4" in line and ":" in line:
                ip = line.split(":")[-1].strip()
                if ip and ip != "127.0.0.1":
                    ips.append(ip)
    except Exception:
        pass
    if not ips:
        ip = local_ip()
        if ip != "127.0.0.1":
            ips.append(ip)
    seen, uniq = set(), []
    for ip in ips:
        if ip not in seen:
            seen.add(ip)
            uniq.append(ip)
    return uniq


def start_server():
    global PORT
    for p in [PORT, 8080, 8000, 80]:
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", p), Handler)
            PORT = p
            return srv
        except OSError:
            continue
    raise SystemExit("\n[エラー] ポートを開けませんでした。")


if __name__ == "__main__":
    PASSPHRASE = setup_passphrase()
    server = start_server()
    server.daemon_threads = True

    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "port.txt"), "w") as f:
            f.write(str(PORT))
    except Exception:
        pass

    print("")
    print("=" * 52)
    print("  MiniChat 起動しました！（写真つき・1ファイル版）")
    print("=" * 52)
    if PASSPHRASE:
        print("  合言葉      : %s" % PASSPHRASE)
    else:
        print("  合言葉      : なし（誰でも入れます）")
    print("-" * 52)
    print("  このパソコン  : http://127.0.0.1:%d" % PORT)
    print("  スマホで開くURL（同じWi-Fi限定）:")
    for ip in all_ips():
        print("     http://%s:%d" % (ip, PORT))
    print("-" * 52)
    print("  終了するとき  : Ctrl + C")
    print("=" * 52)
    print("")
    print("  （参加・退出・写真送信がここに表示されます）")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了しました")
