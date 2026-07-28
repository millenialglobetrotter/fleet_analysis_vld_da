import json
import logging
import requests
from datetime import datetime, timedelta, timezone
import ast
import http.server
import socketserver
import threading
import random
import string
import os
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import mysql.connector
    from mysql.connector import Error
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    logging.warning("mysql-connector-python not found. Database features disabled.")

CONFIG_FILE = 'config.json'
PORT = int(os.environ.get('PORT', 8000))
MAX_WORKERS = 40
FUEL_PRICE_PER_LITER = 99  # Updated fuel price in INR

IST_OFFSET = timedelta(hours=5, minutes=30)

DATA_STORE = {"success": [], "failed": [], "total_eligible": 0}
VLD_DATA_STORE = {"success": [], "failed": [], "total_eligible": 0}
SESSIONS = {}
SESSION_LOCK = threading.Lock()
DATA_LOCK = threading.Lock()

AUTH_TOKEN_CACHE = {}
VLD_AUTH_TOKEN_CACHE = {}
TOKEN_EXPIRY_SECONDS = 25 * 60

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FLEET ANALYTICS</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap');
        :root {
            --bg:#f3f4f6;--bg2:#ffffff;--bg3:#f9fafb;--bg4:#e5e7eb;
            --border:#e5e7eb;--text:#111827;--text2:#4b5563;--text3:#9ca3af;
            --c:#0891b2;--cg:#059669;--cr:#dc2626;--co:#d97706;--cp:#9333ea;--cy:#ca8a04;--cb:#2563eb;
        }
        *{margin:0;padding:0;box-sizing:border-box}
        html,body{height:100%;overflow:hidden;font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text)}

        .modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:1000;display:none;align-items:center;justify-content:center;backdrop-filter:blur(2px)}
        .modal-overlay.show{display:flex}
        .modal{background:var(--bg2);width:90vw;height:85vh;border-radius:12px;box-shadow:0 20px 25px -5px rgba(0,0,0,0.1),0 10px 10px -5px rgba(0,0,0,0.04);display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--border)}
        .modal-header{padding:16px 20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;background:var(--bg3)}
        .modal-title{font-size:17.5px;font-weight:700;color:var(--c);text-transform:uppercase;letter-spacing:1px}
        .modal-body{flex:1;overflow:hidden;display:flex;padding:0}
        .filter-col{flex:1;border-right:1px solid var(--border);display:flex;flex-direction:column;min-width:200px}
        .filter-col:last-child{border-right:none}
        .filter-header{padding:10px 12px;background:var(--bg3);border-bottom:1px solid var(--border);font-size:12.5px;font-weight:600;color:var(--text3);font-family:'JetBrains Mono',monospace;text-transform:uppercase;letter-spacing:0.5px;display:flex;justify-content:space-between;align-items:center}
        .filter-search-wrap{padding:6px 8px;border-bottom:1px solid var(--border);background:var(--bg2)}
        .filter-search{width:100%;padding:5px 8px;font-size:12.5px;font-family:'JetBrains Mono',monospace;border:1px solid var(--border);border-radius:4px;background:var(--bg3);color:var(--text);outline:none;transition:border .15s}
        .filter-search:focus{border-color:var(--c)}
        .filter-search::placeholder{color:var(--text3)}
        .filter-list{flex:1;overflow-y:auto;padding:4px}
        .filter-item{padding:6px 10px;font-size:13.5px;color:var(--text2);cursor:pointer;border-radius:4px;margin-bottom:2px;display:flex;align-items:center; gap: 8px; transition:background 0.1s}
        .filter-item:hover{background:var(--bg4)}
        .filter-item.selected{background:rgba(8,145,178,0.1);color:var(--c);font-weight:500}
        .filter-item .check{width:14px;height:14px;border:1px solid var(--border);border-radius:3px;display:flex;align-items:center;justify-content:center;font-size:11.5px;color:white;transition:all 0.1s;flex-shrink:0}
        .filter-item.selected .check{background:var(--c);border-color:var(--c);content:'✓'}
        .modal-footer{padding:16px 20px;border-top:1px solid var(--border);display:flex;justify-content:flex-end;gap:12px;background:var(--bg2)}

        #loginPage{display:flex;align-items:center;justify-content:center;height:100vh;background:linear-gradient(135deg,#f3f4f6 0%,#e5e7eb 100%)}
        .login-card{background:var(--bg2);padding:40px;border-radius:12px;box-shadow:0 10px 25px rgba(0,0,0,0.1);width:350px;text-align:center;border:1px solid var(--border)}
        .login-logo{font-size:25.5px;font-weight:800;color:var(--c);letter-spacing:1px;margin-bottom:24px;text-transform:uppercase}
        .login-input{width:100%;padding:12px;margin-bottom:16px;border:1px solid var(--border);border-radius:6px;font-size:15.5px;outline:none;transition:border .2s}
        .login-input:focus{border-color:var(--c)}
        .btn-login{width:100%;background:var(--c);color:#fff;border:none;padding:12px;border-radius:6px;font-size:15.5px;font-weight:600;cursor:pointer;transition:opacity .2s}
        .btn-login:hover{opacity:0.9}
        .error-msg{color:var(--cr);font-size:13.5px;margin-top:10px;min-height:18px}
        #appPage{display:none;height:100%;flex-direction:column}

        .hdr{height:auto;min-height:56px;background:var(--bg2);border-bottom:1px solid var(--border);padding:12px 24px;display:flex;flex-direction:column;gap:10px;position:relative;z-index:100;flex-shrink:0;box-shadow:0 1px 2px rgba(0,0,0,0.05)}
        .hdr-top{display:flex;align-items:center;justify-content:space-between}
        .logo-text{font-family:'Arial',sans-serif;font-size:21.5px;font-weight:800;letter-spacing:1px;color:var(--c);text-transform:uppercase}
        .hdr-right{display:flex;align-items:center;gap:12px}
        .hdr-pill{font-family:'JetBrains Mono',monospace;font-size:12.5px;padding:4px 12px;border-radius:20px;background:var(--bg3);border:1px solid var(--border);color:var(--text2)}
        .hdr-pill b{color:var(--c)}
        .control-panel{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;background:var(--bg3);padding:10px;border-radius:8px;border:1px solid var(--border);flex:1}
        .cp-group{display:flex;flex-direction:column;gap:4px;flex:1;position:relative;min-width:300px}
        .cp-label{font-size:11.5px;font-family:'JetBrains Mono',monospace;color:var(--text3);text-transform:uppercase;font-weight:600}
        input[type="text"].dr-input{font-family:'JetBrains Mono',monospace;font-size:13.5px;padding:6px 10px;border:1px solid var(--border);border-radius:4px;background:var(--bg2);color:var(--text);outline:none;width:100%;cursor:pointer}
        input:focus{border-color:var(--c)}
        .btn-primary{background:var(--c);color:#fff;border:none;padding:6px 16px;border-radius:6px;font-size:13.5px;font-weight:600;cursor:pointer;transition:opacity .2s;font-family:'JetBrains Mono',monospace;white-space:nowrap}
        .btn-primary:hover{opacity:0.9}
        .btn-primary:disabled{opacity:0.5;cursor:not-allowed}
        .btn-secondary{background:var(--bg2);color:var(--text);border:1px solid var(--border);padding:6px 16px;border-radius:6px;font-size:13.5px;font-weight:600;cursor:pointer;transition:all .2s;font-family:'JetBrains Mono',monospace;white-space:nowrap}
        .btn-secondary:hover{border-color:var(--c);color:var(--c)}
        .btn-logout{font-size:13.5px;color:var(--text3);text-decoration:underline;cursor:pointer;border:none;background:none}

        .proj-tabs{display:flex;background:var(--bg2);border-bottom:1px solid var(--border);flex-shrink:0}
        .proj-tab{padding:12px 28px;font-size:13.5px;font-family:'JetBrains Mono',monospace;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;background:transparent;border:none;border-bottom:2px solid transparent;color:var(--text3);cursor:pointer;transition:all .15s}
        .proj-tab:hover{color:var(--text)}
        .proj-tab.active{color:var(--c);border-bottom-color:var(--c)}
        .proj-page{display:none;flex:1;min-height:0;flex-direction:column;overflow:hidden}
        .proj-page.active{display:flex}

        .layout{display:grid;grid-template-columns:280px 1fr;flex:1;min-height:0; overflow:hidden}
        .sidebar{background:var(--bg2);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
        .stitle{font-family:'JetBrains Mono',monospace;font-size:11.5px;letter-spacing:1.5px;text-transform:uppercase;color:var(--text3);padding:16px 16px 6px;font-weight:600}
        .hint{font-size:12.5px;color:var(--text3);padding:0 16px 10px;font-style:italic}
        .sidebar-content-split{flex:1;display:flex;flex-direction:column;overflow:hidden}
        .sidebar-half{flex:1;display:flex;flex-direction:column;min-height:0;overflow:hidden}
        .file-list{flex:1;overflow-y:auto;padding:8px 10px}
        .file-list::-webkit-scrollbar{width:4px}
        .file-list::-webkit-scrollbar-thumb{background:var(--bg4);border-radius:3px}
        .fbtn{width:100%;text-align:left;background:transparent;border:1px solid transparent;color:var(--text2);padding:8px 10px;border-radius:6px;font-size:12.5px;cursor:pointer;transition:all .1s;margin-bottom:2px;display:flex;align-items:center;gap:8px}
        .fbtn:hover{background:var(--bg3);color:var(--text)}
        .fbtn.sel{background:rgba(8,145,178,0.08);border-color:var(--c);color:var(--c);font-weight:600}
        .fbtn-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px}
        .fbtn-score{font-family:'JetBrains Mono',monospace;font-size:12.5px;color:var(--text3);background:var(--bg);padding:1px 6px;border-radius:9px;flex-shrink:0}
        .fbtn.sel .fbtn-score{color:var(--c);background:rgba(8,145,178,0.1)}
        .fbtn-all{font-weight:700;border-bottom:1px solid var(--border);margin-bottom:6px;padding-bottom:8px}
        .clear-btn{width:100%;text-align:left;background:transparent;border:1px solid var(--border);color:var(--text3);padding:6px 10px;border-radius:6px;font-size:11.5px;font-family:'JetBrains Mono',monospace;cursor:pointer;transition:all .14s;margin-top:4px}
        .clear-btn:hover{border-color:var(--cr);color:var(--cr);background:rgba(220,38,38,0.05)}

        .main{padding:20px;overflow-y:auto;display:flex;flex-direction:column;gap:16px; height: 100%}
        .main::-webkit-scrollbar{width:6px}
        .main::-webkit-scrollbar-thumb{background:var(--bg4);border-radius:4px}

        .kpi-row{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
        .kcard{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:16px;position:relative;overflow:hidden;transition:border-color .2s;box-shadow:0 1px 2px rgba(0,0,0,0.03)}
        .kcard::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--accent,var(--c))}
        .kcard:hover{border-color:var(--accent,var(--c))}
        .kcard-label{font-family:'JetBrains Mono',monospace;font-size:11.5px;letter-spacing:0.5px;text-transform:uppercase;color:var(--text3);margin-bottom:6px}
        .kcard-val{font-size:23.5px;font-weight:700;line-height:1;color:var(--text)}
        .kcard-sub{font-size:12.5px;color:var(--text2);margin-top:4px}
        
        .insight-card{background:linear-gradient(135deg,#ffffff 0%,#f9fafb 100%);border:1px solid var(--border);border-left:4px solid var(--co);border-radius:8px;padding:16px;display:flex;flex-direction:column;gap:8px;box-shadow:0 2px 4px rgba(0,0,0,0.04)}
        .insight-title{font-size:12.5px;font-family:'JetBrains Mono',monospace;color:var(--text3);text-transform:uppercase;letter-spacing:0.5px;font-weight:600}
        .insight-val{font-size:21.5px;font-weight:700;color:var(--text)}
        .insight-desc{font-size:12.5px;color:var(--text2);line-height:1.4}

        .score-row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
        .scard{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:16px;display:flex;gap:16px;align-items:center}
        .scard-info{flex:1;min-width:0}
        .scard-title{font-size:11.5px;color:var(--text3);text-transform:uppercase;letter-spacing:0.5px;font-family:'JetBrains Mono',monospace;margin-bottom:4px}
        .scard-val{font-size:25.5px;font-weight:700;font-family:'JetBrains Mono',monospace;color:var(--text)}
        .scard-file{font-size:12.5px;color:var(--text2);margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
        .grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
        .icard{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:16px;box-shadow:0 1px 2px rgba(0,0,0,0.03);display:flex;flex-direction:column}
        .ict{font-family:'JetBrains Mono',monospace;font-size:11.5px;letter-spacing:0.5px;text-transform:uppercase;color:var(--text3);margin-bottom:12px;display:flex;align-items:center;gap:6px}
        .ict .dot{width:6px;height:6px;border-radius:50%}
        .rlist{display:flex;flex-direction:column;gap:6px;overflow-y:auto;padding-right:4px}
        .rlist::-webkit-scrollbar{width:3px}
        .rlist::-webkit-scrollbar-thumb{background:var(--bg4)}
        .ritem{display:flex;justify-content:space-between;align-items:center;padding:4px 6px;background:var(--bg3);border-radius:4px;border-left:2px solid transparent; font-size: 14.5px;}
        .ritem span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text2); max-width:65%; text-align:left;}
        .ritem span:last-child{font-family:'JetBrains Mono',monospace;font-weight:600; text-align:right;}

        .ir{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid var(--bg4); cursor: pointer; user-select: none; transition: background 0.2s;}
        .ir:last-child{margin-bottom:0;padding-bottom:0;border-bottom:none}
        .ir:hover{background:var(--bg3)}
        .ir-l{font-size:13.5px;color:var(--text2); display:flex; align-items: center; gap: 6px;}
        .ir-icon{font-size:11.5px; transition: transform 0.2s; opacity: 0.5;}
        .ir.expanded .ir-icon{transform: rotate(180deg); opacity: 1;}
        .ir-v{font-family:'JetBrains Mono',monospace;font-size:13.5px;font-weight:600;color:var(--text)}
        .ir-v.g{color:var(--cg)}.ir-v.w{color:var(--co)}.ir-v.b{color:var(--cr)}

        .drill-down{display:none; padding: 8px 12px; background: var(--bg3); border-radius: 6px; margin-top: -8px; margin-bottom: 12px; border: 1px solid var(--border); animation: fadeIn 0.3s ease;}
        @keyframes fadeIn{from{opacity:0;transform:translateY(-5px)}to{opacity:1;transform:translateY(0)}}
        .drill-down-row{display:flex; justify-content:space-between; font-size:12.5px; padding:4px 0; border-bottom:1px solid var(--bg4); flex-direction: column; gap: 2px;}
        .drill-down-row:last-child{border:none}
        .drill-down-row span:first-child{word-wrap:break-word;word-break:break-all; color: var(--text2); font-size: 11.5px;}
        .drill-down-v{font-family:'JetBrains Mono',monospace; font-weight:600; color:var(--c); align-self: flex-end;}

        .drill-down-row.clickable { cursor: pointer; border-radius: 4px; padding: 4px; border-bottom: 1px solid var(--border); margin-bottom: 2px; background: var(--bg2); }
        .drill-down-row.clickable:hover { background: var(--border); }
        .drill-down-row.clickable span:first-child { color: var(--c); text-decoration: underline; }

        .sec-lbl{font-family:'JetBrains Mono',monospace;font-size:12.5px;letter-spacing:1px;text-transform:uppercase;color:var(--text3);padding:4px 0;border-bottom:1px solid var(--border);margin-top:8px;margin-bottom:8px}
        .pbar-track{height:4px;background:var(--bg3);border-radius:2px;overflow:hidden;margin-top:4px}
        .pbar-fill{height:100%;border-radius:2px;transition:width .5s ease}
        .gear-row{display:flex;align-items:center;gap:8px;margin-bottom:6px}
        .gear-row:last-child{margin-bottom:0}
        .gear-lbl{width:80px;font-family:'JetBrains Mono',monospace;font-size:11.5px;color:var(--text2);text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .gear-track{flex:1;height:6px;background:var(--bg3);border-radius:3px;overflow:hidden}
        .gear-fill{height:100%;border-radius:3px;transition:width .5s}
        .gear-km{width:60px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:11.5px;color:var(--text)}
        .waste-row{display:flex;align-items:center;gap:8px;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid var(--bg4)}
        .waste-row:last-child{margin-bottom:0;padding-bottom:0;border-bottom:none}
        .waste-label{font-size:13.5px;color:var(--text2);min-width:110px}
        .waste-bar-track{flex:1;height:6px;background:var(--bg3);border-radius:3px;overflow:hidden}
        .waste-bar-fill{height:100%;border-radius:3px;transition:width .5s}
        .waste-val{font-family:'JetBrains Mono',monospace;font-size:12.5px;font-weight:600;min-width:60px;text-align:right;color:var(--text)}
        .top-waster-card{background:var(--bg3);border-radius:6px;padding:10px;margin-bottom:8px;border-left:3px solid var(--cr); cursor: pointer; transition: background 0.2s; position: relative;}
        .top-waster-card:hover{background:var(--bg4)}
        .top-waster-id{font-family:'JetBrains Mono',monospace;font-size:11.5px;font-weight:700;color:var(--cr);margin-bottom:6px;word-wrap:break-word;word-break:break-all;}
        .top-waster-detail{font-size:11.5px;color:var(--text2);display:flex;justify-content:space-between;padding:2px 0}
        .top-waster-detail span:last-child{font-family:'JetBrains Mono',monospace;font-weight:600;color:var(--text)}
        .waster-breakdown{display:none; margin-top:8px; padding-top:8px; border-top:1px dashed var(--border)}
        .waster-breakdown-row{display:flex; justify-content:space-between; font-size:11.5px; margin-bottom:2px}
        .btn-compare{width:100%;margin-top:8px;background:var(--c);color:#fff;border:none;padding:5px 10px;border-radius:5px;font-size:11.5px;font-family:'JetBrains Mono',monospace;font-weight:700;cursor:pointer;letter-spacing:0.5px;transition:opacity .2s}
        .view-toggle-bar{display:none;align-items:center;gap:0;background:var(--bg2);border:1px solid var(--border);border-radius:8px;overflow:hidden;flex-shrink:0;box-shadow:0 1px 3px rgba(0,0,0,0.06)}
        .view-toggle-bar.show{display:flex}
        .vtab{flex:1;padding:7px 18px;font-size:12.5px;font-family:'JetBrains Mono',monospace;font-weight:600;letter-spacing:0.5px;border:none;background:transparent;color:var(--text3);cursor:pointer;transition:all .18s;text-transform:uppercase;white-space:nowrap}
        .vtab:hover{color:var(--text);background:var(--bg3)}
        .vtab.active{background:var(--c);color:#fff}
        .vtab:not(:last-child){border-right:1px solid var(--border)}
        #vtabClose,#vtabCloseVld{border-radius:0 8px 8px 0}
        .vtab-label{display:flex;align-items:center;gap:6px;justify-content:center}
        .btn-compare:hover{opacity:0.85}
        .leaderboard-row{display:flex;align-items:center;justify-content:space-between;padding:4px 6px;background:var(--bg3);border-radius:4px;border-left:2px solid transparent;font-size:13.5px;margin-bottom:4px}
        .leaderboard-row span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text2);max-width:60%;text-align:left}
        .leaderboard-row .lboard-score{font-family:'JetBrains Mono',monospace;font-weight:600;text-align:right}
        .leaderboard-row .lboard-cmp{font-size:10.5px;font-family:'JetBrains Mono',monospace;padding:2px 6px;border-radius:3px;background:var(--c);color:#fff;cursor:pointer;flex-shrink:0;margin-left:6px;border:none;transition:opacity .2s}
        .leaderboard-row .lboard-cmp:hover{opacity:0.85}
        .empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:400px;color:var(--text3);gap:16px;border:1px dashed var(--border);border-radius:12px;background:var(--bg2)}
        .loader{position:fixed;inset:0;background:rgba(255,255,255,.85);z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;opacity:0;pointer-events:none;transition:opacity .25s}
        .loader.show{opacity:1;pointer-events:auto}
        .spin{width:28px;height:28px;border:3px solid var(--border);border-top-color:var(--c);border-radius:50%;animation:sp .7s linear infinite}
        @keyframes sp{to{transform:rotate(360deg)}}
        .toast{position:fixed;top:70px;right:24px;background:var(--bg2);border:1px solid var(--cg);border-radius:8px;padding:10px 20px;font-size:12.5px;color:var(--cg);z-index:9998;transform:translateX(120%);transition:transform .3s;font-family:'JetBrains Mono',monospace;box-shadow:0 4px 12px rgba(0,0,0,0.1);max-width:400px;word-wrap:break-word}
        .toast.err{border-color:var(--cr);color:var(--cr)}
        .toast.show{transform:translateX(0)}

        #cmpContent,#cmpContentVld{height:100%;display:none;flex-direction:column;overflow:hidden;}
        .cmp-wrap{display:grid;grid-template-columns:1fr 1fr;height:100%;overflow:hidden}
        .cmp-col{overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}
        .cmp-col::-webkit-scrollbar{width:4px}
        .cmp-col::-webkit-scrollbar-thumb{background:var(--bg4);border-radius:3px}
        .cmp-col:first-child{border-right:1px solid var(--border)}
        .cmp-header{font-family:'JetBrains Mono',monospace;font-size:12.5px;font-weight:700;color:var(--c);padding:8px 10px;background:rgba(8,145,178,0.06);border:1px solid rgba(8,145,178,0.2);border-radius:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis; text-align: left; display: flex; align-items: center; justify-content: flex-start;}
        .cmp-score-row{display:flex;gap:10px}
        .cmp-score-box{flex:1;background:var(--bg3);border-radius:6px;padding:10px;text-align:center}
        .cmp-score-lbl{font-size:10.5px;font-family:'JetBrains Mono',monospace;color:var(--text3);text-transform:uppercase;margin-bottom:4px}
        .cmp-score-val{font-size:27.5px;font-weight:700;font-family:'JetBrains Mono',monospace}

        .dr-pop{position:absolute;top:calc(100% + 6px);left:0;background:var(--bg2);border:1px solid var(--border);border-radius:10px;box-shadow:0 12px 28px rgba(0,0,0,.15);z-index:500;display:none;padding:14px;width:560px}
        .dr-pop.show{display:block}
        .dr-cals{display:flex;gap:18px}
        .dr-cal{flex:1}
        .dr-cal-hdr{display:flex;align-items:center;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:13.5px;font-weight:700;margin-bottom:8px}
        .dr-cal-nav{background:none;border:none;cursor:pointer;color:var(--text2);font-size:15.5px;padding:2px 6px;border-radius:4px}
        .dr-cal-nav:hover{background:var(--bg3)}
        .dr-cal-nav.hidden{visibility:hidden}
        .dr-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}
        .dr-dow{font-size:10.5px;color:var(--text3);text-align:center;font-family:'JetBrains Mono',monospace;padding:2px 0}
        .dr-day{font-size:12.5px;text-align:center;padding:5px 0;border-radius:5px;cursor:pointer;color:var(--text)}
        .dr-day:hover{background:var(--bg3)}
        .dr-day.muted{color:var(--text3);opacity:.45}
        .dr-day.in-range{background:rgba(8,145,178,0.12)}
        .dr-day.range-start,.dr-day.range-end{background:var(--c);color:#fff;font-weight:700}
        .dr-times{display:flex;gap:14px;margin-top:12px;padding-top:12px;border-top:1px solid var(--border)}
        .dr-time-group{flex:1}
        .dr-time-label{font-size:11.5px;font-family:'JetBrains Mono',monospace;color:var(--text3);text-transform:uppercase;margin-bottom:4px}
        .dr-time-input{width:100%;font-family:'JetBrains Mono',monospace;font-size:13.5px;padding:6px 8px;border:1px solid var(--border);border-radius:5px;background:var(--bg3)}
        .dr-actions{display:flex;justify-content:space-between;align-items:center;margin-top:12px}
    </style>
</head>
<body>
    <div id="loginPage">
        <div class="login-card">
            <div class="login-logo">FLEET ANALYTICS</div>
            <input type="text" id="lUser" class="login-input" placeholder="Client ID" autocomplete="off">
            <input type="password" id="lPass" class="login-input" placeholder="Client Secret">
            <button class="btn-login" id="btnLogin" onclick="attemptLogin()">SIGN IN</button>
            <div class="error-msg" id="lError"></div>
        </div>
    </div>

    <div id="appPage">
        <div class="hdr">
            <div class="hdr-top">
                <div class="logo"><div class="logo-text">FLEET ANALYTICS</div></div>
                <div class="hdr-right">
                    <div class="hdr-pill"><b id="hTotalVehicles">0</b> Total Eligible</div>
                    <div class="hdr-pill"><b id="hFileCountDA">0</b> DA Vehicles</div>
                    <div class="hdr-pill"><b id="hFileCountVld">0</b> VLD Vehicles</div>
                    <button class="btn-logout" onclick="logout()">Logout</button>
                </div>
            </div>
            <div class="control-panel">
                <div class="cp-group">
                    <div class="cp-label">Select Date Range (IST)</div>
                    <input type="text" class="dr-input" id="rangeInput" readonly onclick="datePicker.toggle()">
                    <div id="rangePop"></div>
                </div>
                <button class="btn-secondary" id="btnFilter" onclick="openFilterModal()">Filter Vehicles (0)</button>
                <button class="btn-primary" id="btnFetch" onclick="runAnalysisAll()">FETCH DATA</button>
            </div>
        </div>

        <div class="proj-tabs">
            <button class="proj-tab active" id="projTabDA" onclick="switchProject('da')">Driver Analytics</button>
            <button class="proj-tab" id="projTabVLD" onclick="switchProject('vld')">Vehicle Load Detection</button>
        </div>

        <div class="proj-page active" id="pageDA">
            <div class="layout">
                <div class="sidebar">
                    <div class="stitle">Vehicle Ids</div>
                    <div class="hint">Ctrl+Click to select multiple</div>
                    <div class="sidebar-content-split">
                        <div class="sidebar-half">
                            <div class="file-list" id="fileList"></div>
                        </div>
                        <div style="border-top:1px solid var(--border);flex-shrink:0"></div>
                        <div class="sidebar-half">
                            <div class="stitle" style="padding:10px 16px 6px;color:var(--cr);margin-top:0">No Data / Errors</div>
                            <div class="rlist" id="failedList"></div>
                        </div>
                    </div>
                    <div style="padding:10px">
                        <button class="clear-btn" id="clearBtn">&#x2715; Clear All Vehicles</button>
                    </div>
                </div>

                <div id="mainPanel" class="main">
                    <div id="viewToggleBar" class="view-toggle-bar">
                        <button class="vtab active" id="vtabAgg" onclick="setViewMode('agg')"><span class="vtab-label">&#9634; Aggregate</span></button>
                        <button class="vtab" id="vtabCmp" onclick="setViewMode('cmp')"><span class="vtab-label">&#8942; Compare</span></button>
                        <button id="vtabClose" onclick="closeCompareView()" title="Back to previous view" style="flex:0;padding:7px 12px;font-size:14.5px;font-family:'JetBrains Mono',monospace;font-weight:700;border:none;border-left:1px solid var(--border);background:transparent;color:var(--text3);cursor:pointer;transition:all .15s;line-height:1" onmouseover="this.style.background='rgba(220,38,38,0.08)';this.style.color='var(--cr)'" onmouseout="this.style.background='transparent';this.style.color='var(--text3)'">&#x2715;</button>
                    </div>
                    <div id="emptyState" class="empty">
                        <div style="font-size:41.5px;opacity:.2">&#128194;</div>
                        <div>No data loaded</div>
                        <div style="font-size:13.5px">Select a date range, filter vehicles and click 'FETCH DATA' to begin analysis</div>
                    </div>
                    <div id="aggContent" style="display:none;flex-direction:column;gap:16px">
                        <div class="kpi-row">
                            <div class="kcard" style="--accent:var(--c)"><div class="kcard-label">Total Distance</div><div class="kcard-val" id="kTotalDist">&#8212;</div><div class="kcard-sub">all selected trips</div></div>
                            <div class="kcard" style="--accent:var(--co)"><div class="kcard-label">Total Fuel</div><div class="kcard-val" id="kTotalFuel">&#8212;</div><div class="kcard-sub">consumed</div></div>
                            <div class="kcard" style="--accent:var(--cp)"><div class="kcard-label">Avg Economy</div><div class="kcard-val" id="kAvgEcon">&#8212;</div><div class="kcard-sub">km per litre</div></div>
                        </div>
                        
                        <div class="sec-lbl">&#9889; FLEET INSIGHTS</div>
                        <div class="insight-card" style="border-left-color:var(--cr)">
                            <div class="insight-title">Total Wasted Fuel Cost</div>
                            <div class="insight-val" id="insightWasteCost">&#8212;</div>
                            <div class="insight-desc">Financial loss from idle, overspeed, coasting, and overrevving (Assumed ₹99/L).</div>
                        </div>

                        <div class="score-row">
                            <div class="scard">
                                <svg width="60" height="60" viewBox="0 0 64 64">
                                    <circle cx="32" cy="32" r="25" fill="none" stroke="var(--border)" stroke-width="5"/>
                                    <circle id="driverArc" cx="32" cy="32" r="25" fill="none" stroke="var(--cg)" stroke-width="5" stroke-dasharray="0 157" stroke-linecap="round" transform="rotate(-90 32 32)" style="transition:stroke-dasharray .6s ease"/>
                                    <text x="32" y="36" text-anchor="middle" font-family="JetBrains Mono,monospace" font-size="12.5" fill="var(--cg)" id="driverArcLbl">&#8212;</text>
                                </svg>
                                <div class="scard-info"><div class="scard-title">Avg Driver Score</div><div class="scard-val" id="topDriverScore" style="color:var(--cg)">&#8212;</div><div class="scard-file">Average of selected</div></div>
                            </div>
                            <div class="scard">
                                <svg width="60" height="60" viewBox="0 0 64 64">
                                    <circle cx="32" cy="32" r="25" fill="none" stroke="var(--border)" stroke-width="5"/>
                                    <circle id="fuelArc" cx="32" cy="32" r="25" fill="none" stroke="var(--cg)" stroke-width="5" stroke-dasharray="0 157" stroke-linecap="round" transform="rotate(-90 32 32)" style="transition:stroke-dasharray .6s ease"/>
                                    <text x="32" y="36" text-anchor="middle" font-family="JetBrains Mono,monospace" font-size="12.5" fill="var(--cg)" id="fuelArcLbl">&#8212;</text>
                                </svg>
                                <div class="scard-info"><div class="scard-title">Avg Fuel Score</div><div class="scard-val" id="topFuelScore" style="color:var(--cg)">&#8212;</div><div class="scard-file">Average of selected</div></div>
                            </div>
                        </div>
                        <div class="sec-lbl">&#9656; SCORES LEADERBOARD</div>
                        <div class="grid2">
                            <div class="icard"><div class="ict"><span class="dot" style="background:var(--cg)"></span>Top 3 Driver Scores</div><div class="rlist" id="topDriverList"></div></div>
                            <div class="icard"><div class="ict"><span class="dot" style="background:var(--cr)"></span>Bottom 3 Driver Scores</div><div class="rlist" id="botDriverList"></div></div>
                        </div>
                        <div class="grid2">
                            <div class="icard"><div class="ict"><span class="dot" style="background:var(--cg)"></span>Top 3 Fuel Scores</div><div class="rlist" id="topFuelList"></div></div>
                            <div class="icard"><div class="ict"><span class="dot" style="background:var(--cr)"></span>Bottom 3 Fuel Scores</div><div class="rlist" id="botFuelList"></div></div>
                        </div>
                        <div class="sec-lbl">&#9656; MODEL ANALYTICS</div>
                        <div class="grid2">
                            <div class="icard"><div class="ict"><span class="dot" style="background:var(--c)"></span>Avg Fuel Economy by Model (km/L)</div><div id="modelEconChart"></div></div>
                            <div class="icard"><div class="ict"><span class="dot" style="background:var(--cr)"></span>Total Fuel Waste by Model (L)</div><div id="modelWasteChart"></div></div>
                        </div>
                        <div class="sec-lbl">&#9656; FUEL ANALYSIS</div>
                        <div class="grid3">
                            <div class="icard">
                                <div class="ict"><span class="dot" style="background:var(--cg)"></span>Efficiency</div>
                                <div class="ir" style="cursor:default"><span class="ir-l">Fuel per 100 km</span><span class="ir-v" id="iFuelPer100">&#8212;</span></div>
                                <div class="ir" style="cursor:default"><span class="ir-l">Best Economy Trip</span><span class="ir-v g" id="iBestEcon">&#8212;</span></div>
                                <div class="ir" style="cursor:default"><span class="ir-l">Worst Economy Trip</span><span class="ir-v b" id="iWorstEcon">&#8212;</span></div>
                            </div>
                            <div class="icard">
                                <div class="ict"><span class="dot" style="background:var(--cr)"></span>Fuel Waste Sources</div>
                                <div class="waste-row"><span class="waste-label">Idle</span><div class="waste-bar-track"><div class="waste-bar-fill" id="wBarIdle" style="background:var(--cr);width:0%"></div></div><span class="waste-val" id="wValIdle">&#8212;</span></div>
                                <div class="waste-row"><span class="waste-label">Overspeed</span><div class="waste-bar-track"><div class="waste-bar-fill" id="wBarOver" style="background:var(--co);width:0%"></div></div><span class="waste-val" id="wValOver">&#8212;</span></div>
                                <div class="waste-row"><span class="waste-label">Coasting</span><div class="waste-bar-track"><div class="waste-bar-fill" id="wBarCoast" style="background:var(--cb);width:0%"></div></div><span class="waste-val" id="wValCoast">&#8212;</span></div>
                                <div class="waste-row"><span class="waste-label">Overrev</span><div class="waste-bar-track"><div class="waste-bar-fill" id="wBarRev" style="background:var(--cy);width:0%"></div></div><span class="waste-val" id="wValRev">&#8212;</span></div>
                                <div class="waste-row" style="border-bottom:none; margin-bottom:0; background:transparent; padding-top:8px;"><span class="waste-label" style="font-weight:700">Total Waste</span><span class="waste-val b" id="iTotalWaste">&#8212;</span><span class="waste-val" id="iWastePct" style="margin-left:auto; min-width:auto; padding-left:10px;">&#8212;</span></div>
                            </div>
                            <div class="icard"><div class="ict"><span class="dot" style="background:var(--cr)"></span>Top 2 Fuel Wasters</div><div id="topWastersList"></div></div>
                        </div>
                        <div class="grid3" style="margin-top:0">
                            <div class="icard" style="grid-column:span 3">
                                <div class="ict"><span class="dot" style="background:var(--cb)"></span>Usage Ratios</div>
                                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px">
                                    <div class="ir" style="flex-direction:column;align-items:flex-start;border:none;gap:4px; cursor: default"><span class="ir-l">Idle / Engine ON</span><span class="ir-v" id="iIdleRatio">&#8212;</span></div>
                                    <div class="ir" style="flex-direction:column;align-items:flex-start;border:none;gap:4px; cursor: default"><span class="ir-l">Wrong Gear / Dist</span><span class="ir-v" id="iWrongGearPct">&#8212;</span></div>
                                    <div class="ir" style="flex-direction:column;align-items:flex-start;border:none;gap:4px; cursor: default"><span class="ir-l">Overspeed / Dist</span><span class="ir-v" id="iOverPct">&#8212;</span></div>
                                </div>
                            </div>
                        </div>
                        <div class="sec-lbl">&#9656; SAFETY EVENTS (Click to drill down)</div>
                        <div class="grid2">
                            <div class="icard">
                                <div class="ict"><span class="dot" style="background:var(--cr)"></span>Harsh Events</div>
                                <div class="ir" id="rowHarshBrake" onclick="toggleDrillDown(this)"><span class="ir-l">Harsh Braking <span class="ir-icon">&#9660;</span></span><span class="ir-v" id="iHarshBrake">&#8212;</span></div>
                                <div id="dd_Harsh_Braking" class="drill-down"></div>
                                <div class="ir" id="rowHarshAcc" onclick="toggleDrillDown(this)"><span class="ir-l">Harsh Acceleration <span class="ir-icon">&#9660;</span></span><span class="ir-v" id="iHarshAcc">&#8212;</span></div>
                                <div id="dd_Harsh_Acceleration" class="drill-down"></div>
                                <div class="ir" id="rowHarshCorn" onclick="toggleDrillDown(this)"><span class="ir-l">Harsh Cornering <span class="ir-icon">&#9660;</span></span><span class="ir-v" id="iHarshCorn">&#8212;</span></div>
                                <div id="dd_Harsh_Cornering" class="drill-down"></div>
                                <div class="ir" style="cursor:default"><span class="ir-l">Total Harsh</span><span class="ir-v b" id="iTotalHarsh">&#8212;</span></div>
                            </div>
                            <div class="icard">
                                <div class="ict"><span class="dot" style="background:var(--co)"></span>Braking Events</div>
                                <div class="ir" id="rowModBrake" onclick="toggleDrillDown(this)"><span class="ir-l">Moderate Braking <span class="ir-icon">&#9660;</span></span><span class="ir-v" id="iModBrake">&#8212;</span></div>
                                <div id="dd_Moderate_Braking" class="drill-down"></div>
                            </div>
                        </div>
                        <div class="sec-lbl">&#9656; SPEED PROFILE</div>
                        <div class="grid3">
                            <div class="icard">
                                <div class="ict"><span class="dot" style="background:var(--co)"></span>Speed Stats</div>
                                <div class="ir" style="cursor:default"><span class="ir-l">Maximum Speed</span><span class="ir-v" id="iMaxSpeed">&#8212;</span></div>
                                <div class="ir" style="cursor:default"><span class="ir-l">Avg Speed</span><span class="ir-v" id="iAvgSpd">&#8212;</span></div>
                                <div class="ir" id="rowOverspeed" onclick="toggleDrillDown(this)"><span class="ir-l">Overspeed Distance <span class="ir-icon">&#9660;</span></span><span class="ir-v w" id="iOverSpd">&#8212;</span></div>
                                <div id="dd_Overspeed" class="drill-down"></div>
                                <div class="ir" id="rowCoasting" onclick="toggleDrillDown(this)"><span class="ir-l">Coasting Distance <span class="ir-icon">&#9660;</span></span><span class="ir-v g" id="iCoasting">&#8212;</span></div>
                                <div id="dd_Coasting" class="drill-down"></div>
                            </div>
                            <div class="icard" style="grid-column:span 2">
                                <div class="ict"><span class="dot" style="background:var(--cr)"></span>High Speed Events (&gt; 60 km/h)</div>
                                <div style="font-size:13.5px;color:var(--text2);margin-bottom:8px">Trips recording maximum speeds above 60 km/h</div>
                                <div class="rlist" id="highSpeedList"></div>
                            </div>
                        </div>
                        <div class="sec-lbl">&#9656; ENGINE &amp; DRIVETRAIN</div>
                        <div class="grid3">
                            <div class="icard">
                                <div class="ict"><span class="dot" style="background:var(--cb)"></span>Engine Time</div>
                                <div class="ir" style="cursor:default"><span class="ir-l">Engine ON</span><span class="ir-v g" id="iEngOn">&#8212;</span></div>
                                <div class="ir" style="cursor:default"><span class="ir-l">Engine OFF</span><span class="ir-v" id="iEngOff">&#8212;</span></div>
                                <div class="ir" style="cursor:default"><span class="ir-l">Idle Duration</span><span class="ir-v w" id="iIdleTime">&#8212;</span></div>
                                <div class="ir" style="cursor:default"><span class="ir-l">Data Loss Duration</span><span class="ir-v w" id="iDataLoss">&#8212;</span></div>
                            </div>
                            <div class="icard">
                                <div class="ict"><span class="dot" style="background:var(--cp)"></span>Start / Stop</div>
                                <div class="ir" style="cursor:default"><span class="ir-l">Engine Start Count</span><span class="ir-v" id="iStartCnt">&#8212;</span></div>
                                <div class="ir" style="cursor:default"><span class="ir-l">Engine Stop Count</span><span class="ir-v" id="iStopCnt">&#8212;</span></div>
                                <div class="ir" style="cursor:default"><span class="ir-l">MIL Error Distance</span><span class="ir-v w" id="iMilError">&#8212;</span></div>
                            </div>
                            <div class="icard">
                                <div class="ict"><span class="dot" style="background:var(--cy)"></span>Clutch &amp; Gear Wear</div>
                                <div class="ir" id="rowWrongGear" onclick="toggleDrillDown(this)"><span class="ir-l">Wrong Gear Distance <span class="ir-icon">&#9660;</span></span><span class="ir-v w" id="iWrongGear">&#8212;</span></div>
                                <div id="dd_Wrong_Gear" class="drill-down"></div>
                            </div>
                        </div>
                        <div class="sec-lbl">&#9656; GEAR DISTRIBUTION</div>
                        <div class="icard"><div class="ict"><span class="dot" style="background:var(--c)"></span>Distance per Gear</div><div id="gearBars"></div></div>
                    </div>
                    <div id="cmpContent" style="display:none"></div>
                </div>
            </div>
        </div>

        <div class="proj-page" id="pageVLD">
            <div class="layout">
                <div class="sidebar">
                    <div class="stitle">Vehicle Ids</div>
                    <div class="hint">Ctrl+Click to select multiple</div>
                    <div class="sidebar-content-split">
                        <div class="sidebar-half"><div class="file-list" id="fileListVld"></div></div>
                        <div style="border-top:1px solid var(--border);flex-shrink:0"></div>
                        <div class="sidebar-half">
                            <div class="stitle" style="padding:10px 16px 6px;color:var(--cr);margin-top:0">No Data / Errors</div>
                            <div class="rlist" id="failedListVld"></div>
                        </div>
                    </div>
                    <div style="padding:10px"><button class="clear-btn" id="clearBtnVld">&#x2715; Clear All Vehicles</button></div>
                </div>

                <div id="mainPanelVld" class="main">
                    <div id="viewToggleBarVld" class="view-toggle-bar">
                        <button class="vtab active" id="vtabAggVld" onclick="setVldViewMode('agg')"><span class="vtab-label">&#9634; Aggregate</span></button>
                        <button class="vtab" id="vtabCmpVld" onclick="setVldViewMode('cmp')"><span class="vtab-label">&#8942; Compare</span></button>
                        <button id="vtabCloseVld" onclick="closeCompareViewVld()" title="Back to previous view" style="flex:0;padding:7px 12px;font-size:14.5px;font-family:'JetBrains Mono',monospace;font-weight:700;border:none;border-left:1px solid var(--border);background:transparent;color:var(--text3);cursor:pointer;transition:all .15s;line-height:1" onmouseover="this.style.background='rgba(220,38,38,0.08)';this.style.color='var(--cr)'" onmouseout="this.style.background='transparent';this.style.color='var(--text3)'">&#x2715;</button>
                    </div>
                    <div id="emptyStateVld" class="empty">
                        <div style="font-size:41.5px;opacity:.2">&#128663;</div>
                        <div>No data loaded</div>
                        <div style="font-size:13.5px">Select a date range, filter vehicles and click 'FETCH DATA' to begin analysis</div>
                    </div>
                    <div id="aggContentVld" style="display:none;flex-direction:column;gap:16px">
                        <div class="kpi-row">
                            <div class="kcard" style="--accent:var(--c)"><div class="kcard-label">Total Distance</div><div class="kcard-val" id="vTotalDist">&#8212;</div><div class="kcard-sub">all selected vehicles</div></div>
                            <div class="kcard" style="--accent:var(--cg)"><div class="kcard-label">Avg Distance / Vehicle</div><div class="kcard-val" id="vAvgDistVeh">&#8212;</div><div class="kcard-sub">across selected</div></div>
                            <div class="kcard" style="--accent:var(--cp)"><div class="kcard-label">Loaded Distance %</div><div class="kcard-val" id="vProductivity">&#8212;</div><div class="kcard-sub">Full + Part Load &divide; Total</div></div>
                        </div>
                        
                        <div class="sec-lbl">&#9889; FLEET INSIGHTS</div>
                        <div class="grid2">
                            <div class="insight-card" style="border-left-color:var(--co)">
                                <div class="insight-title">Deadhead Distance</div>
                                <div class="insight-val" id="vldInsightDeadhead">&#8212;</div>
                                <div class="insight-desc">Total distance driven with no revenue-generating load.</div>
                            </div>
                            <div class="insight-card" style="border-left-color:var(--cg)">
                                <div class="insight-title">Most Efficient Model</div>
                                <div class="insight-val" id="vldInsightBestModel">&#8212;</div>
                                <div class="insight-desc" id="vldInsightBestModelDesc">Model with the highest loaded distance percentage.</div>
                            </div>
                        </div>

                        <div class="sec-lbl">&#9656; MODEL ANALYTICS</div>
                        <div class="grid2">
                            <div class="icard"><div class="ict"><span class="dot" style="background:var(--c)"></span>Loaded Distance by Model (km)</div><div id="vldModelDistChart"></div></div>
                            <div class="icard"><div class="ict"><span class="dot" style="background:var(--cg)"></span>Loaded % by Model</div><div id="vldModelPctChart"></div></div>
                        </div>
                        <div class="sec-lbl">&#9656; DISTANCE BY LOAD STATE</div>
                        <div class="grid3">
                            <div class="icard">
                                <div class="ict"><span class="dot" style="background:var(--text3)"></span>No Load</div>
                                <div class="kcard-val" id="vNoLoadDist">&#8212;</div>
                                <div class="pbar-track"><div class="pbar-fill" id="vNoLoadBar" style="background:var(--text3);width:0%"></div></div>
                                <div class="kcard-sub" id="vNoLoadPct">&#8212;</div>
                            </div>
                            <div class="icard">
                                <div class="ict"><span class="dot" style="background:var(--cy)"></span>Part Load</div>
                                <div class="kcard-val" id="vPartLoadDist">&#8212;</div>
                                <div class="pbar-track"><div class="pbar-fill" id="vPartLoadBar" style="background:var(--cy);width:0%"></div></div>
                                <div class="kcard-sub" id="vPartLoadPct">&#8212;</div>
                            </div>
                            <div class="icard">
                                <div class="ict"><span class="dot" style="background:var(--co)"></span>Full Load</div>
                                <div class="kcard-val" id="vFullLoadDist">&#8212;</div>
                                <div class="pbar-track"><div class="pbar-fill" id="vFullLoadBar" style="background:var(--co);width:0%"></div></div>
                                <div class="kcard-sub" id="vFullLoadPct">&#8212;</div>
                            </div>
                        </div>
                        <div class="sec-lbl">&#9656; PRODUCTIVITY INSIGHT</div>
                        <div class="icard">
                            <div class="ict"><span class="dot" style="background:var(--cp)"></span>Distance-based productivity</div>
                            <div class="ir" style="cursor:default"><span class="ir-l">Loaded Distance (Part + Full)</span><span class="ir-v g" id="vLoadedDist">&#8212;</span></div>
                            <div class="ir" style="cursor:default"><span class="ir-l">Unloaded / No-Load Distance</span><span class="ir-v" id="vUnloadedDist">&#8212;</span></div>
                            <div class="ir" style="cursor:default"><span class="ir-l">Avg Distance / Day</span><span class="ir-v" id="vAvgPerDay">&#8212;</span></div>
                        </div>
                        <div class="sec-lbl">&#9656; PER-VEHICLE BREAKDOWN</div>
                        <div class="icard">
                            <div class="ict"><span class="dot" style="background:var(--c)"></span>Selected Vehicles</div>
                            <div class="rlist" id="vldPerVehicleList" style="max-height:340px"></div>
                        </div>
                    </div>
                    <div id="cmpContentVld" style="display:none"></div>
                </div>
            </div>
        </div>
    </div>

    <!-- Filter Modal -->
    <div class="modal-overlay" id="filterModal">
        <div class="modal">
            <div class="modal-header">
                <div class="modal-title">Select Vehicles</div>
                <div>
                    <button class="btn-secondary" style="margin-right:8px;font-size:11.5px;padding:4px 8px;" onclick="syncRegistry()">Sync Registry</button>
                    <button class="btn-secondary" style="font-size:11.5px;padding:4px 8px;" onclick="closeFilterModal()">&#x2715;</button>
                </div>
            </div>
            <div class="modal-body">
                <div class="filter-col">
                    <div class="filter-header">Make <span class="count" id="countMake">0</span></div>
                    <div class="filter-search-wrap"><input type="text" class="filter-search" id="searchMake" placeholder="Search make..." oninput="renderFilterLists()"></div>
                    <div class="filter-list" id="listMake"></div>
                </div>
                <div class="filter-col">
                    <div class="filter-header">Model <span class="count" id="countModel">0</span></div>
                    <div class="filter-search-wrap"><input type="text" class="filter-search" id="searchModel" placeholder="Search model..." oninput="renderFilterLists()"></div>
                    <div class="filter-list" id="listModel"></div>
                </div>
                <div class="filter-col">
                    <div class="filter-header">Variant <span class="count" id="countVariant">0</span></div>
                    <div class="filter-search-wrap"><input type="text" class="filter-search" id="searchVariant" placeholder="Search variant..." oninput="renderFilterLists()"></div>
                    <div class="filter-list" id="listVariant"></div>
                </div>
                <div class="filter-col">
                    <div class="filter-header">SubSystem Vehicle ID <span class="count" id="countVehicle">0</span></div>
                    <div class="filter-search-wrap" style="display:flex;gap:6px;align-items:center">
                        <input type="text" class="filter-search" id="searchVehicle" placeholder="Search subsystem vehicle ID..." oninput="renderFilterLists()" style="flex:1">
                        <button id="btnSelectAllVehicles" onclick="toggleSelectAllVehicles()" style="font-size:10.5px;font-family:'JetBrains Mono',monospace;padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);color:var(--text2);cursor:pointer;white-space:nowrap;flex-shrink:0" title="Select / Deselect all visible vehicles">All</button>
                    </div>
                    <div class="filter-list" id="listVehicle"></div>
                </div>
            </div>
            <div class="modal-footer">
                <div style="font-size:12.5px;color:var(--text2);margin-right:auto" id="selectionSummary">0 selected</div>
                <button class="btn-secondary" onclick="clearFilters()">Clear</button>
                <button class="btn-primary" onclick="applyFilters()">Apply Selection</button>
            </div>
        </div>
    </div>

    <div class="loader" id="loader"><div class="spin"></div><div style="font-size:12.5px;color:var(--text2);font-family:'JetBrains Mono',monospace">Processing...</div></div>
    <div class="toast" id="toast"></div>

<script>
const FUEL_PRICE = 99;

function pad2(n){return String(n).padStart(2,'0')}
function fmt12(d){
    let h=d.getHours(),m=d.getMinutes(),s=d.getSeconds();
    const ap=h>=12?'PM':'AM'; let h12=h%12; if(h12===0) h12=12;
    return `${h12}:${pad2(m)}:${pad2(s)} ${ap}`;
}
function fmtDate(d){return `${d.getMonth()+1}/${d.getDate()}/${d.getFullYear()}`}
function parseTimeStr(str,baseDate){
    const m=str.trim().match(/^(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)$/i);
    const d=new Date(baseDate);
    if(!m){return d}
    let h=parseInt(m[1],10); const min=parseInt(m[2],10), sec=parseInt(m[3],10);
    const ap=m[4].toUpperCase();
    if(ap==='PM' && h!==12) h+=12;
    if(ap==='AM' && h===12) h=0;
    d.setHours(h,min,sec,0);
    return d;
}

class DateRangePicker{
    constructor(inputId,popId,onChange){
        this.input=document.getElementById(inputId);
        this.pop=document.getElementById(popId);
        this.onChange=onChange;
        const now=new Date();
        this.start=new Date(now.getFullYear(),now.getMonth(),now.getDate(),0,0,0);
        this.end=new Date(now.getFullYear(),now.getMonth(),now.getDate(),23,59,59);
        this.viewMonth=new Date(now.getFullYear(),now.getMonth(),1);
        this.picking='start';
        this.render();
        this.updateInput();
        this.pop.addEventListener('click', (e)=>{ e.stopPropagation(); });
        document.addEventListener('click',(e)=>{
            if(!this.pop.contains(e.target) && e.target!==this.input){ this.pop.classList.remove('show'); }
        });
    }
    toggle(){ this.pop.classList.toggle('show'); if(this.pop.classList.contains('show')) this.render(); }
    updateInput(){ this.input.value = `${fmtDate(this.start)}, ${fmt12(this.start)} \u2013 ${fmtDate(this.end)}, ${fmt12(this.end)}`; if(this.onChange) this.onChange(this.start,this.end); }
    monthGrid(monthDate){
        const y=monthDate.getFullYear(), m=monthDate.getMonth();
        const first=new Date(y,m,1); const startDow=first.getDay();
        const daysInMonth=new Date(y,m+1,0).getDate();
        const cells=[];
        for(let i=0;i<startDow;i++){ const dd=new Date(y,m,1-(startDow-i)); cells.push({date:dd,muted:true}); }
        for(let d=1;d<=daysInMonth;d++){ cells.push({date:new Date(y,m,d),muted:false}); }
        while(cells.length%7!==0){ const last=cells[cells.length-1].date; cells.push({date:new Date(last.getFullYear(),last.getMonth(),last.getDate()+1),muted:true}); }
        return cells;
    }
    sameDay(a,b){ return a.getFullYear()===b.getFullYear() && a.getMonth()===b.getMonth() && a.getDate()===b.getDate(); }
    dayClass(d){
        let cls='dr-day';
        if(this.sameDay(d,this.start)) cls+=' range-start';
        else if(this.sameDay(d,this.end)) cls+=' range-end';
        else if(d>this.start && d<this.end) cls+=' in-range';
        return cls;
    }
    renderCal(monthDate,showPrevNav,showNextNav){
        const cells=this.monthGrid(monthDate);
        const dows=['S','M','T','W','T','F','S'];
        let html=`<div class="dr-cal-hdr">
            <button class="dr-cal-nav ${showPrevNav?'':'hidden'}" onclick="datePicker.shiftMonth(-1)">&#8249;</button>
            <span>${monthDate.toLocaleString('default',{month:'long'})} ${monthDate.getFullYear()}</span>
            <button class="dr-cal-nav ${showNextNav?'':'hidden'}" onclick="datePicker.shiftMonth(1)">&#8250;</button>
        </div><div class="dr-grid">`;
        dows.forEach(dw=>html+=`<div class="dr-dow">${dw}</div>`);
        cells.forEach(c=>{
            html+=`<div class="${this.dayClass(c.date)}${c.muted?' muted':''}" onclick="datePicker.pickDay(${c.date.getFullYear()},${c.date.getMonth()},${c.date.getDate()})">${c.date.getDate()}</div>`;
        });
        html+='</div>';
        return html;
    }
    shiftMonth(n){ this.viewMonth=new Date(this.viewMonth.getFullYear(),this.viewMonth.getMonth()+n,1); this.render(); }
    pickDay(y,m,d){
        const picked=new Date(y,m,d);
        if(this.picking==='start'){
            this.start=new Date(y,m,d,this.start.getHours(),this.start.getMinutes(),this.start.getSeconds());
            this.end=new Date(y,m,d,this.end.getHours(),this.end.getMinutes(),this.end.getSeconds());
            this.picking='end';
        } else {
            let s=this.start, e=new Date(y,m,d,this.end.getHours(),this.end.getMinutes(),this.end.getSeconds());
            if(e<s){ const tmp=s; s=e; e=tmp; }
            this.start=s; this.end=e;
            this.picking='start';
        }
        this.render(); this.updateInput();
    }
    setStartTime(str){ this.start=parseTimeStr(str,this.start); this.updateInput(); }
    setEndTime(str){ this.end=parseTimeStr(str,this.end); this.updateInput(); }
    render(){
        const nextMonth=new Date(this.viewMonth.getFullYear(),this.viewMonth.getMonth()+1,1);
        this.pop.className='dr-pop'+(this.pop.classList.contains('show')?' show':'');
        this.pop.innerHTML=`
            <div class="dr-cals">
                <div class="dr-cal">${this.renderCal(this.viewMonth,true,false)}</div>
                <div class="dr-cal">${this.renderCal(nextMonth,false,true)}</div>
            </div>
            <div class="dr-times">
                <div class="dr-time-group"><div class="dr-time-label">Start time</div><input type="text" class="dr-time-input" value="${fmt12(this.start)}" onchange="datePicker.setStartTime(this.value)"></div>
                <div class="dr-time-group"><div class="dr-time-label">End time</div><input type="text" class="dr-time-input" value="${fmt12(this.end)}" onchange="datePicker.setEndTime(this.value)"></div>
            </div>
            <div class="dr-actions">
                <button class="btn-secondary" style="font-size:11.5px;padding:4px 10px" onclick="datePicker.setToday()">Today</button>
                <button class="btn-primary" onclick="datePicker.pop.classList.remove('show')">Done</button>
            </div>`;
    }
    setToday(){
        const now=new Date();
        this.start=new Date(now.getFullYear(),now.getMonth(),now.getDate(),0,0,0);
        this.end=new Date(now.getFullYear(),now.getMonth(),now.getDate(),23,59,59);
        this.viewMonth=new Date(now.getFullYear(),now.getMonth(),1);
        this.render(); this.updateInput();
    }
}

let datePicker;
let days=[], selected={}, selectAll=true, nextId=0, viewMode='agg';
let prevSelection=null;
let vldDays=[], vldSelected={}, vldSelectAll=true, vldNextId=0, vldViewMode='agg'; let vldPrevSelection=null;

let allVehicles=[];
let selectedVehicleIds=new Set();
let filterState={makes:new Set(),models:new Set(),variants:new Set()};

function getUnique(arr, key){ return [...new Set(arr.map(item=>item[key]))].sort(); }
function getSearchVal(id){ return (document.getElementById(id)||{}).value||''; }

window.addEventListener('DOMContentLoaded',()=>{
    datePicker=new DateRangePicker('rangeInput','rangePop');
    checkSession();
});

function switchProject(p){
    document.getElementById('projTabDA').classList.toggle('active',p==='da');
    document.getElementById('projTabVLD').classList.toggle('active',p==='vld');
    document.getElementById('pageDA').classList.toggle('active',p==='da');
    document.getElementById('pageVLD').classList.toggle('active',p==='vld');
}

async function checkSession(){
    try{
        const r=await fetch('/api/check-session');
        const d=await r.json();
        document.getElementById('loginPage').style.display=d.logged_in?'none':'flex';
        document.getElementById('appPage').style.display=d.logged_in?'flex':'none';
        if(d.logged_in){ loadVehicleFilters(); }
    }catch(e){console.error(e)}
}
async function attemptLogin(){
    const clientId=document.getElementById('lUser').value.trim();
    const clientSecret=document.getElementById('lPass').value.trim();
    if(!clientId||!clientSecret){document.getElementById('lError').textContent='Enter Client ID and Secret';return}
    const btn=document.getElementById('btnLogin');
    btn.disabled=true; btn.textContent='Authenticating...';
    document.getElementById('lError').textContent='';
    try{
        const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client_id:clientId,client_secret:clientSecret})});
        const d=await r.json();
        if(d.success) window.location.reload();
        else document.getElementById('lError').textContent=d.message||'Authentication failed';
    }catch(e){document.getElementById('lError').textContent='Server error'}
    finally{btn.disabled=false; btn.textContent='SIGN IN';}
}
async function logout(){await fetch('/api/logout',{method:'POST'});window.location.reload()}

async function loadVehicleFilters(){
    try{
        const r=await fetch('/api/da/vehicles/filters');
        if(!r.ok) throw new Error('Failed to load filters');
        allVehicles=await r.json();
        renderFilterLists();
    }catch(e){ console.error(e); showToast('Error loading vehicle filters',true); }
}

async function syncRegistry(){
    try{
        showToast('Syncing vehicle registry (DA + VLD)...', false);
        const r=await fetch('/api/registry/sync', {method:'POST'});
        if(r.ok){
            await loadVehicleFilters();
            showToast('Sync Complete');
        } else { showToast('Sync Failed', true); }
    }catch(e){ showToast('Sync Error', true); }
}

function renderFilterLists(){
    const searchMake=getSearchVal('searchMake').toLowerCase();
    const searchModel=getSearchVal('searchModel').toLowerCase();
    const searchVariant=getSearchVal('searchVariant').toLowerCase();
    const searchVehicle=getSearchVal('searchVehicle').toLowerCase();

    const makeArr=Array.from(filterState.makes);
    const modelArr=Array.from(filterState.models);
    const variantArr=Array.from(filterState.variants);

    const allMakes=getUnique(allVehicles,'make').filter(m=>!searchMake||m.toLowerCase().includes(searchMake));
    let visAfterMake=allVehicles;
    if(makeArr.length) visAfterMake=visAfterMake.filter(v=>makeArr.includes(v.make));
    const allModels=getUnique(visAfterMake,'model').filter(m=>!searchModel||m.toLowerCase().includes(searchModel));
    let visAfterModel=visAfterMake;
    if(modelArr.length) visAfterModel=visAfterModel.filter(v=>modelArr.includes(v.model));
    const allVariants=getUnique(visAfterModel,'variant').filter(v=>!searchVariant||v.toLowerCase().includes(searchVariant));
    let visibleVehicles=visAfterModel;
    if(variantArr.length) visibleVehicles=visibleVehicles.filter(v=>variantArr.includes(v.variant));
    const vehicleList=visibleVehicles.filter(v=>!searchVehicle||v.sub_system_vehicle_id.toLowerCase().includes(searchVehicle));

    document.getElementById('listMake').innerHTML=allMakes.map(m=>`<div class="filter-item ${filterState.makes.has(m)?'selected':''}" onclick="toggleFilter('make', '${m.replace(/'/g,"\\'")}')"><div class="check">${filterState.makes.has(m)?'&#x2713;':''}</div>${m}</div>`).join('')||'<div style="padding:10px;color:#999;font-size:12.5px">No results</div>';
    document.getElementById('countMake').textContent=allMakes.length;

    document.getElementById('listModel').innerHTML=allModels.map(m=>`<div class="filter-item ${filterState.models.has(m)?'selected':''}" onclick="toggleFilter('model', '${m.replace(/'/g,"\\'")}')"><div class="check">${filterState.models.has(m)?'&#x2713;':''}</div>${m}</div>`).join('')||`<div style="padding:10px;color:#999;font-size:12.5px">${makeArr.length?'No results':'Select a Make'}</div>`;
    document.getElementById('countModel').textContent=allModels.length;

    document.getElementById('listVariant').innerHTML=allVariants.map(v=>`<div class="filter-item ${filterState.variants.has(v)?'selected':''}" onclick="toggleFilter('variant', '${v.replace(/'/g,"\\'")}')"><div class="check">${filterState.variants.has(v)?'&#x2713;':''}</div>${v}</div>`).join('')||`<div style="padding:10px;color:#999;font-size:12.5px">${modelArr.length?'No results':'Select a Model'}</div>`;
    document.getElementById('countVariant').textContent=allVariants.length;

    document.getElementById('listVehicle').innerHTML=vehicleList.map(v=>{
        const sel=selectedVehicleIds.has(v.sub_system_vehicle_id);
        return `<div class="filter-item ${sel?'selected':''}" onclick="toggleVehicle('${v.sub_system_vehicle_id.replace(/'/g,"\\'")}')"><div class="check">${sel?'&#x2713;':''}</div>${v.sub_system_vehicle_id}</div>`;
    }).join('')||`<div style="padding:10px;color:#999;font-size:12.5px">${(variantArr.length||modelArr.length||makeArr.length)?'No results':'Select a Variant'}</div>`;
    document.getElementById('countVehicle').textContent=vehicleList.length;

    const btn=document.getElementById('btnSelectAllVehicles');
    if(btn){
        const allSel=vehicleList.length>0 && vehicleList.every(v=>selectedVehicleIds.has(v.sub_system_vehicle_id));
        btn.textContent=allSel?'None':'All';
        btn.style.borderColor=allSel?'var(--c)':'var(--border)';
        btn.style.color=allSel?'var(--c)':'var(--text2)';
    }
    updateSelectionSummary();
}

function toggleSelectAllVehicles(){
    const searchVehicle=getSearchVal('searchVehicle').toLowerCase();
    const makeArr=Array.from(filterState.makes), modelArr=Array.from(filterState.models), variantArr=Array.from(filterState.variants);
    let vis=allVehicles;
    if(makeArr.length) vis=vis.filter(v=>makeArr.includes(v.make));
    if(modelArr.length) vis=vis.filter(v=>modelArr.includes(v.model));
    if(variantArr.length) vis=vis.filter(v=>variantArr.includes(v.variant));
    const vehicleList=vis.filter(v=>!searchVehicle||v.sub_system_vehicle_id.toLowerCase().includes(searchVehicle));
    const allSelected=vehicleList.every(v=>selectedVehicleIds.has(v.sub_system_vehicle_id));
    if(allSelected) vehicleList.forEach(v=>selectedVehicleIds.delete(v.sub_system_vehicle_id));
    else vehicleList.forEach(v=>selectedVehicleIds.add(v.sub_system_vehicle_id));
    renderFilterLists();
}
function toggleFilter(type,val){
    const s=type==='make'?filterState.makes:(type==='model'?filterState.models:filterState.variants);
    if(s.has(val)) s.delete(val); else s.add(val);
    renderFilterLists();
}
function toggleVehicle(id){
    if(selectedVehicleIds.has(id)) selectedVehicleIds.delete(id); else selectedVehicleIds.add(id);
    renderFilterLists();
}
function clearFilters(){
    filterState.makes.clear(); filterState.models.clear(); filterState.variants.clear(); selectedVehicleIds.clear();
    ['searchMake','searchModel','searchVariant','searchVehicle'].forEach(id=>{const el=document.getElementById(id); if(el) el.value='';});
    renderFilterLists();
}
function updateSelectionSummary(){
    document.getElementById('selectionSummary').textContent=`${selectedVehicleIds.size} vehicles selected`;
}
function openFilterModal(){
    document.getElementById('filterModal').classList.add('show');
    if(allVehicles.length===0) loadVehicleFilters();
    else renderFilterLists();
}
function closeFilterModal(){
    document.getElementById('filterModal').classList.remove('show');
    document.getElementById('btnFilter').textContent=`Filter Vehicles (${selectedVehicleIds.size})`;
}
function applyFilters(){ closeFilterModal(); }

function parseJsonToDay(raw,filename){
    let data=null;
    try{ data=typeof raw==='string'?JSON.parse(raw):(typeof raw==='object'&&raw!==null?raw:null); }catch(e){return null}
    if(!data) return null;
    const ins=data.Score_And_Insights||{},met=data.Metrics_Data||{};
    if(Array.isArray(ins)&&ins[0]===false) return null;
    function gv(o,k,fb=0){if(!o||!o[k])return fb;const i=o[k];return(typeof i==='object'&&i.value!==undefined)?i.value:fb}
    function gt(o,k,fb='00:00:00'){if(!o||!o[k])return fb;const i=o[k];return(typeof i==='object'&&i.value!==undefined)?i.value:fb}
    const gearData=gv(met,'Gear_Detection',{});
    return{
        _id:nextId++,
        date_label:filename.replace('.json','').replace(/_/g,' '),
        source:filename,
        driver_score:parseFloat(ins.Driver_Score||0),
        fuel_score:parseFloat(ins.Fuel_Score||0),
        stats:{
            distance_km:parseFloat(gv(met,'Distance_Travelled')),
            avg_speed:parseFloat(gv(met,'Average_Speed')),
            max_speed:parseFloat(gv(met,'Maximum_Speed')),
            total_fuel_l:parseFloat(gv(met,'Total_Fuel_Consumed')),
            fuel_economy:parseFloat(gv(met,'Fuel_Economy')),
            harsh_acc:parseFloat(gv(met,'Harsh_Acceleration')),
            harsh_brake:parseFloat(gv(met,'Harsh_Braking')),
            harsh_corner:parseFloat(gv(met,'Harsh_Cornering')),
            mod_brake:parseFloat(gv(met,'Moderate_Braking')),
            wrong_gear_km:parseFloat(gv(met,'Distance_Travelled_in_Wrong_Gear')),
            overspeed_km:parseFloat(gv(met,'Overspeeding_Distance')),
            coasting_km:parseFloat(gv(met,'Coasting_Distance')),
            idle_fuel_l:parseFloat(gv(met,'Additional_Fuel_Consumed_During_Engine_Idling')),
            overspeed_fuel_l:parseFloat(gv(met,'Additional_Fuel_Consumed_During_Overspeed')),
            coasting_fuel_l:parseFloat(gv(met,'Additional_Fuel_Consumed_During_Coasting', 0)),
            overrev_fuel_l:parseFloat(gv(met,'Additional_Fuel_Consumption_During_Engine_Overreving')),
            mil_error_km:parseFloat(gv(met,'MIL_Error')),
            idle_time:gt(met,'Engine_Idling_Duration'),
            overrev_time:gt(met,'Engine_Overreving_Duration'),
            engine_on:gt(met,'Engine_ON_Time'),
            engine_off:gt(met,'Engine_OFF_Time'),
            data_loss:gt(met,'Data_Loss_Duration'),
            start_count:parseFloat(gv(met,'Engine_Start_Count')),
            stop_count:parseFloat(gv(met,'Engine_Stop_Count')),
            gear_dist:(gearData&&typeof gearData==='object')?gearData:{}
        }
    };
}

async function runAnalysisAll(){
    if(selectedVehicleIds.size===0){ showToast('Please select at least one vehicle', true); return; }
    const btn=document.getElementById('btnFetch'),loader=document.getElementById('loader');
    btn.disabled=true; loader.classList.add('show');

    const vehicleIds = Array.from(selectedVehicleIds);
    const p = datePicker;
    const startLocal = `${p.start.getFullYear()}-${pad2(p.start.getMonth()+1)}-${pad2(p.start.getDate())} ${pad2(p.start.getHours())}:${pad2(p.start.getMinutes())}:${pad2(p.start.getSeconds())}`;
    const endLocal = `${p.end.getFullYear()}-${pad2(p.end.getMonth()+1)}-${pad2(p.end.getDate())} ${pad2(p.end.getHours())}:${pad2(p.end.getMinutes())}:${pad2(p.end.getSeconds())}`;
    const startLocalISO = `${p.start.getFullYear()}-${pad2(p.start.getMonth()+1)}-${pad2(p.start.getDate())}T${pad2(p.start.getHours())}:${pad2(p.start.getMinutes())}:${pad2(p.start.getSeconds())}`;
    const endLocalISO = `${p.end.getFullYear()}-${pad2(p.end.getMonth()+1)}-${pad2(p.end.getDate())}T${pad2(p.end.getHours())}:${pad2(p.end.getMinutes())}:${pad2(p.end.getSeconds())}`;

    let daOk=false, vldOk=false, daErr='', vldErr='';

    try {
        const [daRes, vldRes] = await Promise.all([
            fetch('/api/da/fetch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({start_ist_local:startLocal,end_ist_local:endLocal,vehicle_ids:vehicleIds})}),
            fetch('/api/vld/fetch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({start_ist_local:startLocalISO,end_ist_local:endLocalISO,vehicle_ids:vehicleIds})})
        ]);

        try {
            const daResult = await daRes.json();
            if(!daRes.ok) throw new Error(daResult.message||'DA Fetch failed');
            processDAResult(daResult);
            daOk = true;
        } catch(e) { daErr = e.message; console.error('DA Error:', e); }

        try {
            const vldResult = await vldRes.json();
            if(!vldRes.ok) throw new Error(vldResult.message||'VLD Fetch failed');
            processVLDResult(vldResult);
            vldOk = true;
        } catch(e) { vldErr = e.message; console.error('VLD Error:', e); }

        if(daOk && vldOk) showToast('Analysis Complete: DA '+days.length+' vehicles, VLD '+vldDays.length+' vehicles loaded');
        else if(daOk) showToast('DA complete, VLD failed: '+vldErr, true);
        else if(vldOk) showToast('VLD complete, DA failed: '+daErr, true);
        else showToast('Both failed: DA='+daErr+', VLD='+vldErr, true);
    } catch(e) {
        console.error(e);
        showToast(e.message, true);
    } finally {
        btn.disabled=false;
        loader.classList.remove('show');
    }
}

function processDAResult(result){
    document.getElementById('hTotalVehicles').textContent=result.total_eligible||0;
    days=[]; selectAll=true; selected={}; nextId=0;
    const allFailed=[...result.failed];
    result.success.forEach(item=>{
        const d=parseJsonToDay(item.data,item.sub_system_vehicle_id);
        if(d) days.push(d);
        else allFailed.push({sub_system_vehicle_id:item.sub_system_vehicle_id, reason:'No score/metrics data in API response'});
    });
    const fl=document.getElementById('failedList');
    if(allFailed.length){
        fl.innerHTML=allFailed.map((f,i)=>{
            const vid=f.sub_system_vehicle_id||'Unknown', reason=f.reason||'Unknown error';
            return '<div class="ir" onclick="toggleDrillDown(this)" style="padding:4px 6px;margin-bottom:2px;border-radius:4px;background:var(--bg3);border-left:2px solid var(--cr);cursor:pointer">'
                +'<span class="ir-l" style="color:var(--text2);font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:75%">'+vid+' <span class="ir-icon" style="font-size:10.5px">&#9660;</span></span>'
                +'<span style="font-size:10.5px;color:var(--cr);font-family:JetBrains Mono,monospace;font-weight:600">ERR</span></div>'
                +'<div id="fdd_'+i+'" class="drill-down" style="margin-top:-2px;margin-bottom:4px">'
                +'<div class="drill-down-row"><span>SubSystem Vehicle ID</span><span class="drill-down-v" style="color:var(--text);word-break:break-all;font-size:11.5px">'+vid+'</span></div>'
                +'<div class="drill-down-row"><span>Reason</span><span class="drill-down-v" style="color:var(--cr);word-break:break-all;white-space:normal;text-align:left;font-size:11.5px">'+reason+'</span></div></div>';
        }).join('');
    } else {
        fl.innerHTML='<div style="font-size:11.5px;color:var(--text3);padding:4px">All vehicles fetched successfully</div>';
    }
    document.getElementById('hFileCountDA').textContent=days.length;
    refresh();
}

function processVLDResult(result){
    vldDays=[]; vldSelectAll=true; vldSelected={}; vldNextId=0;
    (result.success||[]).forEach(item => {
        vldDays.push({...item, _id: vldNextId++});
    });
    document.getElementById('hFileCountVld').textContent=vldDays.length;
    const fl=document.getElementById('failedListVld');
    const failed=result.failed||[];
    fl.innerHTML=failed.length?failed.map(f=>`<div class="ritem" style="border-left-color:var(--cr)"><span>${f.sub_system_vehicle_id}</span><span style="color:var(--cr)">${(f.reason||'error').slice(0,24)}</span></div>`).join(''):'<div style="font-size:11.5px;color:var(--text3);padding:4px">All vehicles fetched successfully</div>';
    refreshVld();
}

function t2s(s){if(!s)return 0;const p=s.split(':').map(Number);return(p[0]*3600+(p[1]||0)*60+(p[2]||0))}
function s2t(s){s=Math.round(s);const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=s%60;return`${h}h:${m}m:${sec}s`}
function getSelIds(){return selectAll?days.map(d=>d._id):Object.keys(selected).map(Number)}
function getSelVldIds(){return vldSelectAll?vldDays.map(d=>d._id):Object.keys(vldSelected).map(Number)}
function set(id,val){const e=document.getElementById(id);if(e)e.textContent=val}
function showToast(msg,err){const t=document.getElementById('toast');t.textContent=msg;t.className=`toast${err?' err':''} show`;setTimeout(()=>t.classList.remove('show'),5000)}
function scColor(v,max){const r=v/(max||5);return r>=0.8?'var(--cg)':r>=0.5?'var(--co)':'var(--cr)'}
function animArc(id,score,max){ const arc=document.getElementById(id);if(!arc)return; const c=2*Math.PI*25,vis=Math.min(score,max); arc.style.strokeDasharray=`${(c*vis/max).toFixed(1)} ${c.toFixed(1)}`; }
function toggleDrillDown(row){ row.classList.toggle('expanded'); const dd=row.nextElementSibling; if(dd&&dd.classList.contains('drill-down')){ dd.style.display=dd.style.display==='block'?'none':'block'; } }

function renderGenericBarChart(containerId, data, unit, color) {
    const el = document.getElementById(containerId);
    if(!el) return;
    const maxVal = Math.max(...data.map(d=>d.val), 1);
    el.innerHTML = data.map(d => `
        <div class="gear-row">
            <span class="gear-lbl">${d.label}</span>
            <div class="gear-track"><div class="gear-fill" style="width:${(d.val/maxVal*100).toFixed(0)}%;background:${color}"></div></div>
            <span class="gear-km">${d.val.toFixed(1)} ${unit}</span>
        </div>
    `).join('') || '<div style="color:var(--text3);font-size:13.5px">No data</div>';
}

function renderFileList(){
    const el=document.getElementById('fileList');
    if(!days.length){el.innerHTML='<div style="padding:20px;color:var(--text3);font-size:12.5px;text-align:center">No files loaded</div>';return}
    const ss={};getSelIds().forEach(id=>ss[id]=true);
    let h=`<button class="fbtn fbtn-all${selectAll?' sel':''}" data-action="all"><span class="fbtn-name">All Vehicles</span><span class="fbtn-score">${days.length}</span></button>`;
    days.forEach(d=>{
        const sel=!!ss[d._id];
        h+=`<button class="fbtn${sel?' sel':''}" data-action="day" data-id="${d._id}"><span class="fbtn-name">${d.date_label}</span><span class="fbtn-score">D:${d.driver_score.toFixed(1)}</span></button>`;
    });
    el.innerHTML=h;
    el.querySelectorAll('.fbtn').forEach(btn=>{
        btn.addEventListener('click',function(e){
            if(this.getAttribute('data-action')==='all'){selectAll=true;selected={};}
            else{
                const id=Number(this.getAttribute('data-id'));
                if(e.ctrlKey||e.metaKey){selectAll=false;if(selected[id])delete selected[id];else selected[id]=true;if(!Object.keys(selected).length)selectAll=true}
                else{selectAll=false;selected={};selected[id]=true;}
            }
            const selectedCount=Object.keys(selected).length;
            if(selectedCount===2||selectedCount===3) viewMode='cmp'; else if(selectedCount===1) viewMode='agg';
            refresh();
        });
    });
    document.getElementById('clearBtn').onclick=()=>{days=[];selected={};selectAll=true;refresh();showToast('Cleared');};
}

function drillToVehicle(label){ const target=days.find(d=>d.date_label===label); if(target) selectSingleVehicle(target._id); }

function renderLeaderboards(sel,type){
    const key=type+'_score';
    const sorted=[...sel].sort((a,b)=>b[key]-a[key]);
    const top3=sorted.slice(0,3),bot3=sorted.slice(-3).reverse();
    function mkRows(arr,col){
        const ids=arr.map(d=>d._id);
        let html=arr.map(d=>`<div class="leaderboard-row" style="border-left-color:${col}"><span title="${d.date_label}">${d.date_label}</span><span class="lboard-score">${d[key].toFixed(1)}</span></div>`).join('');
        if(arr.length>=2){ const label=arr.length===3?'Compare All 3':'Compare'; html+=`<button class="btn-compare" onclick="compareVehicleIds([${ids.join(',')}])">&#9654; ${label}</button>`; }
        else if(arr.length===1){ html+=`<button class="btn-compare" onclick="selectSingleVehicle(${ids[0]})">&#9654; View Details</button>`; }
        return html;
    }
    document.getElementById(`top${type.charAt(0).toUpperCase()+type.slice(1)}List`).innerHTML=mkRows(top3,'var(--cg)');
    document.getElementById(`bot${type.charAt(0).toUpperCase()+type.slice(1)}List`).innerHTML=mkRows(bot3,'var(--cr)');
}

function renderTopWasters(sel){
    const topSel=sel.map(d=>{const s=d.stats;const total=s.idle_fuel_l+s.overspeed_fuel_l+s.coasting_fuel_l+s.overrev_fuel_l;return{_id:d._id,id:d.date_label,total,idle:s.idle_fuel_l,over:s.overspeed_fuel_l,coast:s.coasting_fuel_l, rev:s.overrev_fuel_l};}).sort((a,b)=>b.total-a.total).slice(0,2);
    const container=document.getElementById('topWastersList');
    if(!topSel.length||topSel[0].total===0){ container.innerHTML='<div style="font-size:12.5px;color:var(--text3)">No waste data</div>'; return; }
    let html=topSel.map((w,i)=>{
        const color=i===0?'var(--cr)':'var(--co)';
        return `<div class="top-waster-card" style="border-left-color:${color}" onclick="this.classList.toggle('expanded'); document.getElementById('wbd_${i}').style.display=this.classList.contains('expanded')?'block':'none'">
            <div class="top-waster-id" title="${w.id}">#${i+1} ${w.id}</div>
            <div class="top-waster-detail"><span>Total Wasted</span><span style="color:${color};font-weight:700">${w.total.toFixed(3)} L</span></div>
            <div class="waster-breakdown" id="wbd_${i}">
                <div class="waster-breakdown-row"><span>Idle Waste:</span> <span>${w.idle.toFixed(3)} L</span></div>
                <div class="waster-breakdown-row"><span>Overspeed Waste:</span> <span>${w.over.toFixed(3)} L</span></div>
                <div class="waster-breakdown-row"><span>Coasting Waste:</span> <span>${w.coast.toFixed(3)} L</span></div>
                <div class="waster-breakdown-row"><span>Overrev Waste:</span> <span>${w.rev.toFixed(3)} L</span></div>
            </div>
        </div>`;
    }).join('');
    if(topSel.length===2){ const ids=topSel.map(w=>w._id); html+=`<button class="btn-compare" style="margin-top:10px" onclick="compareVehicleIds([${ids.join(',')}])">&#9654; Compare These 2</button>`; }
    else if(topSel.length===1){ html+=`<button class="btn-compare" style="margin-top:10px" onclick="selectSingleVehicle(${topSel[0]._id})">&#9654; View Details</button>`; }
    container.innerHTML=html;
}

function renderAgg(sel){
    const n=sel.length;
    let totalDist=0,totalFuel=0,sumAvgSpd=0,hB=0,hA=0,hC=0,mB=0,wGear=0,overSpd=0,coast=0,
        idleSec=0,engOnSec=0,engOffSec=0,dataLossSec=0,startCnt=0,stopCnt=0,
        idleFuel=0,overspeedFuel=0,overrevFuel=0,coastingFuel=0,milErr=0,maxSpd=0,
        sumDriverScore=0,sumFuelScore=0;
    const gearTotals={};
    const hbList=[], haList=[], hcList=[], mbList=[], wrongGearList=[], coastingList=[], overspeedList=[];
    let bestEcon={val:-1,file:''},worstEcon={val:9999,file:''};

    const modelStats = {}; 

    sel.forEach(d=>{
        const s=d.stats;
        totalDist+=s.distance_km; totalFuel+=s.total_fuel_l; sumAvgSpd+=s.avg_speed;
        hB+=s.harsh_brake; hA+=s.harsh_acc; hC+=s.harsh_corner; mB+=s.mod_brake;
        wGear+=s.wrong_gear_km; overSpd+=s.overspeed_km; coast+=s.coasting_km;
        idleSec+=t2s(s.idle_time); engOnSec+=t2s(s.engine_on); engOffSec+=t2s(s.engine_off); dataLossSec+=t2s(s.data_loss);
        startCnt+=s.start_count; stopCnt+=s.stop_count;
        idleFuel+=s.idle_fuel_l;
        overspeedFuel+=s.overspeed_fuel_l; overrevFuel+=s.overrev_fuel_l; coastingFuel+=s.coasting_fuel_l; milErr+=s.mil_error_km;
        if(s.max_speed>maxSpd) maxSpd=s.max_speed;
        Object.keys(s.gear_dist).forEach(g=>gearTotals[g]=(gearTotals[g]||0)+parseFloat(s.gear_dist[g]||0));
        sumDriverScore+=d.driver_score; sumFuelScore+=d.fuel_score;
        if(s.harsh_brake>0) hbList.push({id:d.date_label, val:s.harsh_brake});
        if(s.harsh_acc>0) haList.push({id:d.date_label, val:s.harsh_acc});
        if(s.harsh_corner>0) hcList.push({id:d.date_label, val:s.harsh_corner});
        if(s.mod_brake>0) mbList.push({id:d.date_label, val:s.mod_brake});
        if(s.wrong_gear_km>0) wrongGearList.push({id:d.date_label, val:s.wrong_gear_km});
        if(s.coasting_km>0) coastingList.push({id:d.date_label, val:s.coasting_km});
        if(s.overspeed_km>0) overspeedList.push({id:d.date_label, val:s.overspeed_km});
        if(s.fuel_economy>0){ if(s.fuel_economy>bestEcon.val) bestEcon={val:s.fuel_economy,file:d.date_label}; if(s.fuel_economy<worstEcon.val) worstEcon={val:s.fuel_economy,file:d.date_label}; }

        const info = allVehicles.find(v => v.sub_system_vehicle_id === d.date_label);
        const model = info ? info.model : 'Unknown';
        if(!modelStats[model]) modelStats[model] = {dist:0, fuel:0, waste:0};
        modelStats[model].dist += s.distance_km;
        modelStats[model].fuel += s.total_fuel_l;
        modelStats[model].waste += s.idle_fuel_l + s.overspeed_fuel_l + s.coasting_fuel_l + s.overrev_fuel_l;
    });

    const populateDD=(id,list,unit='km')=>{
        const el=document.getElementById(id); if(!el) return;
        if(list.length===0){el.innerHTML='<div style="font-size:11.5px;color:var(--text3);font-style:italic">No events recorded</div>'; return}
        el.innerHTML=list.sort((a,b)=>b.val-a.val).slice(0,3).map(item=>`<div class="drill-down-row clickable" onclick="drillToVehicle('${item.id}')"><span>${item.id}</span><span class="drill-down-v">${item.val.toFixed(2)} ${unit}</span></div>`).join('');
    };
    populateDD('dd_Harsh_Braking', hbList, 'events');
    populateDD('dd_Harsh_Acceleration', haList, 'events');
    populateDD('dd_Harsh_Cornering', hcList, 'events');
    populateDD('dd_Moderate_Braking', mbList, 'events');
    populateDD('dd_Wrong_Gear', wrongGearList);
    populateDD('dd_Coasting', coastingList);
    populateDD('dd_Overspeed', overspeedList);

    const avgSpd=n?sumAvgSpd/n:0;
    const avgEcon=n?(totalFuel>0?totalDist/totalFuel:0):0;
    const avgDriver=n?sumDriverScore/n:0;
    const avgFuel=n?sumFuelScore/n:0;
    const totalHarsh=hB+hA+hC;
    const totalWaste=idleFuel+overspeedFuel+overrevFuel+coastingFuel;
    const wastePct=totalFuel>0?totalWaste/totalFuel*100:0;
    const idleRatio=engOnSec>0?idleSec/engOnSec*100:0;
    const fuelPer100=totalDist>0?totalFuel/totalDist*100:0;
    const maxWaste=Math.max(idleFuel,overspeedFuel,overrevFuel,coastingFuel)||1;

    const wasteCost = totalWaste * FUEL_PRICE;

    set('kTotalDist',`${totalDist.toFixed(1)} km`);
    set('kTotalFuel',`${totalFuel.toFixed(1)} L`);
    set('kAvgEcon',`${avgEcon.toFixed(1)} km/L`);
    
    set('insightWasteCost', `₹ ${wasteCost.toFixed(2)}`);

    set('topDriverScore',avgDriver.toFixed(1)); set('topFuelScore',avgFuel.toFixed(1));
    set('driverArcLbl',avgDriver.toFixed(1)); set('fuelArcLbl',avgFuel.toFixed(1));
    animArc('driverArc',avgDriver,5); animArc('fuelArc',avgFuel,5);
    renderLeaderboards(sel,'driver'); renderLeaderboards(sel,'fuel');
    renderTopWasters(sel);

    const econData = Object.keys(modelStats).map(m => ({label:m, val: modelStats[m].fuel > 0 ? modelStats[m].dist/modelStats[m].fuel : 0}));
    const wasteData = Object.keys(modelStats).map(m => ({label:m, val: modelStats[m].waste}));
    renderGenericBarChart('modelEconChart', econData, 'km/L', 'var(--c)');
    renderGenericBarChart('modelWasteChart', wasteData, 'L', 'var(--cr)');

    set('wValIdle',`${idleFuel.toFixed(3)} L`); set('wValOver',`${overspeedFuel.toFixed(3)} L`); set('wValRev',`${overrevFuel.toFixed(3)} L`); set('wValCoast',`${coastingFuel.toFixed(3)} L`);
    document.getElementById('wBarIdle').style.width=`${(idleFuel/maxWaste*100).toFixed(0)}%`;
    document.getElementById('wBarOver').style.width=`${(overspeedFuel/maxWaste*100).toFixed(0)}%`;
    document.getElementById('wBarRev').style.width=`${(overrevFuel/maxWaste*100).toFixed(0)}%`;
    document.getElementById('wBarCoast').style.width=`${(coastingFuel/maxWaste*100).toFixed(0)}%`;
    set('iTotalWaste',`${totalWaste.toFixed(3)} L`); set('iWastePct',`(${wastePct.toFixed(1)}%)`);
    set('iFuelPer100',`${fuelPer100.toFixed(2)} L/100km`);
    set('iBestEcon',bestEcon.file?`${bestEcon.val.toFixed(2)} km/L \u2014 ${bestEcon.file}`:'—');
    set('iWorstEcon',worstEcon.file&&worstEcon.val<9998?`${worstEcon.val.toFixed(2)} km/L \u2014 ${worstEcon.file}`:'—');
    set('iIdleRatio',`${idleRatio.toFixed(1)}%`);
    set('iWrongGearPct',`${totalDist>0?(wGear/totalDist*100).toFixed(1):'0'}%`);
    set('iOverPct',`${totalDist>0?(overSpd/totalDist*100).toFixed(1):'0'}%`); // FIX: Changed to .toFixed(1) for alignment
    set('iCoasting',`${coast.toFixed(2)} km`);
    set('iHarshBrake',hB); set('iHarshAcc',hA); set('iHarshCorn',hC);
    set('iModBrake',mB); set('iTotalHarsh',totalHarsh);
    set('iMaxSpeed',`${maxSpd.toFixed(0)} km/h`); set('iAvgSpd',`${avgSpd.toFixed(1)} km/h`); set('iOverSpd',`${overSpd.toFixed(2)} km`);
    
    const fastCars=sel.filter(d=>d.stats.max_speed>=60).sort((a,b)=>b.stats.max_speed-a.stats.max_speed);
    document.getElementById('highSpeedList').innerHTML=fastCars.length?fastCars.map(d=>`<div class="ritem" style="border-left-color:var(--cr)"><span>${d.date_label}</span><span>${d.stats.max_speed.toFixed(0)} km/h</span></div>`).join(''):'<div style="color:var(--text3);font-size:12.5px">No vehicles recorded speeds above 60 km/h</div>';
    
    set('iEngOn',s2t(engOnSec)); set('iEngOff',s2t(engOffSec)); set('iIdleTime',s2t(idleSec)); set('iDataLoss',s2t(dataLossSec));
    set('iStartCnt',Math.round(startCnt)); set('iStopCnt',Math.round(stopCnt)); set('iMilError',`${milErr.toFixed(2)} km`);
    const wgDistPct=totalDist>0?(wGear/totalDist*100).toFixed(1):'0';
    set('iWrongGear',`${wGear.toFixed(2)} km (${wgDistPct}%)`);
    const gKeys=Object.keys(gearTotals).sort();
    const gTotal=gKeys.reduce((a,g)=>a+gearTotals[g],0);
    const maxG=Math.max(...Object.values(gearTotals))||1;
    const gCols=['var(--cb)','var(--c)','var(--cg)','var(--cy)','var(--co)','var(--cp)'];
    document.getElementById('gearBars').innerHTML=gKeys.length?gKeys.map((g,i)=>{
        const p=(gearTotals[g]/maxG*100).toFixed(0);
        return`<div class="gear-row"><span class="gear-lbl" style="width:30px">${g.replace('Gear_','G')}</span><div class="gear-track"><div class="gear-fill" style="width:${p}%;background:${gCols[i%gCols.length]}"></div></div><span class="gear-km" style="width:60px;text-align:right">${gearTotals[g].toFixed(1)} km</span></div>`;
    }).join(''):'<div style="color:var(--text3);font-size:13.5px">No gear data</div>';
}

function renderComparison(vehicles){
    const cmp=document.getElementById('cmpContent');
    const gridCols = vehicles.length===3 ? 'grid-template-columns:1fr 1fr 1fr' : 'grid-template-columns:1fr 1fr';
    function colHtml(d){
        const s=d.stats;
        const econ=s.total_fuel_l>0?(s.distance_km/s.total_fuel_l).toFixed(1):'—';
        const fuelPer100=s.distance_km>0?(s.total_fuel_l/s.distance_km*100).toFixed(2):'—';
        const totalHarsh=s.harsh_brake+s.harsh_acc+s.harsh_corner;
        const idleSec=t2s(s.idle_time), engOnSec=t2s(s.engine_on);
        const idleRatio=engOnSec>0?(idleSec/engOnSec*100).toFixed(1):'0';
        const totalWaste=s.idle_fuel_l+s.overspeed_fuel_l+s.overrev_fuel_l+s.coasting_fuel_l;
        const wastePct=s.total_fuel_l>0?(totalWaste/s.total_fuel_l*100).toFixed(1):'0';
        const maxW=Math.max(s.idle_fuel_l,s.overspeed_fuel_l,s.overrev_fuel_l,s.coasting_fuel_l)||1;
        const dCol=scColor(d.driver_score,5),fCol=scColor(d.fuel_score,5);
        const wgPct=s.distance_km>0?(s.wrong_gear_km/s.distance_km*100).toFixed(1):'0';
        function ir(label,val,cls=''){return`<div class="ir" style="cursor:default"><span class="ir-l">${label}</span><span class="ir-v ${cls}">${val}</span></div>`}
        function wbar(label,val,color,max){ const pct=(val/max*100).toFixed(0); return`<div class="waste-row"><span class="waste-label" style="min-width:90px">${label}</span><div class="waste-bar-track"><div class="waste-bar-fill" style="background:${color};width:${pct}%"></div></div><span class="waste-val">${val.toFixed(3)} L</span></div>`; }
        let wasteHtml=wbar('Idle',s.idle_fuel_l,'var(--cr)',maxW)+wbar('Overspeed',s.overspeed_fuel_l,'var(--co)',maxW)+wbar('Overrev',s.overrev_fuel_l,'var(--cy)',maxW)+wbar('Coasting',s.coasting_fuel_l,'var(--cb)',maxW);
        wasteHtml+=`<div class="waste-row" style="border-bottom:none; margin-bottom:0; background:transparent; padding-top:8px;"><span class="waste-label" style="font-weight:700">Total Waste</span><span class="waste-val b">${totalWaste.toFixed(3)} L</span><span class="waste-val" style="margin-left:auto; min-width:auto; padding-left:10px;">(${wastePct}%)</span></div>`;
        return`<div class="cmp-col"><div class="cmp-header">${d.date_label}</div>
            <div class="icard"><div class="ict">Scores</div><div class="cmp-score-row"><div class="cmp-score-box"><div class="cmp-score-lbl">Driver</div><div class="cmp-score-val" style="color:${dCol}">${d.driver_score.toFixed(1)}</div><div style="font-size:11.5px;color:var(--text3)">/5</div></div><div class="cmp-score-box"><div class="cmp-score-lbl">Fuel</div><div class="cmp-score-val" style="color:${fCol}">${d.fuel_score.toFixed(1)}</div><div style="font-size:11.5px;color:var(--text3)">/5</div></div></div></div>
            <div class="icard"><div class="ict"><span class="dot" style="background:var(--c)"></span>Trip Summary</div>${ir('Distance',s.distance_km.toFixed(1)+' km')}${ir('Total Fuel',s.total_fuel_l.toFixed(1)+' L')}${ir('Fuel Economy',econ+' km/L')}${ir('Fuel per 100km',fuelPer100+' L/100km')}${ir('Avg Speed',s.avg_speed.toFixed(1)+' km/h')}${ir('Max Speed',s.max_speed.toFixed(0)+' km/h')}</div>
            <div class="icard"><div class="ict"><span class="dot" style="background:var(--cr)"></span>Safety Events</div>${ir('Harsh Braking',s.harsh_brake)}${ir('Harsh Acceleration',s.harsh_acc)}${ir('Harsh Cornering',s.harsh_corner)}${ir('Moderate Braking',s.mod_brake)}${ir('Total Harsh',totalHarsh,totalHarsh>5?'b':totalHarsh>2?'w':'g')}</div>
            <div class="icard"><div class="ict"><span class="dot" style="background:var(--co)"></span>Fuel Waste</div>${wasteHtml}</div>
            <div class="icard"><div class="ict"><span class="dot" style="background:var(--cb)"></span>Engine &amp; Drivetrain</div>${ir('Engine ON',s2t(engOnSec),'g')}${ir('Idle Duration',s2t(idleSec),'w')}${ir('Idle / Engine ON',idleRatio+'%')}${ir('Wrong Gear',s.wrong_gear_km.toFixed(2)+' km ('+wgPct+'%)','w')}${ir('Overspeed km',s.overspeed_km.toFixed(2)+' km','w')}${ir('Coasting km',s.coasting_km.toFixed(2)+' km','g')}${ir('MIL Error km',s.mil_error_km.toFixed(2)+' km','w')}</div></div>`;
    }
    cmp.innerHTML=`<div class="cmp-wrap" style="${gridCols};height:100%;overflow:hidden;display:grid">${vehicles.map(colHtml).join('')}</div>`;
}

function setViewMode(mode){ viewMode=mode; document.getElementById('vtabAgg').classList.toggle('active', mode==='agg'); document.getElementById('vtabCmp').classList.toggle('active', mode==='cmp'); refresh(); document.getElementById('mainPanel').scrollTop=0; }
function compareVehicleIds(ids){ prevSelection={selectAll, selected:{...selected}}; selectAll=false; selected={}; ids.forEach(id=>selected[id]=true); viewMode='cmp'; refresh(); document.getElementById('mainPanel').scrollTop=0; }
function selectSingleVehicle(id){ prevSelection={selectAll, selected:{...selected}}; selectAll=false; selected={}; selected[id]=true; viewMode='agg'; refresh(); document.getElementById('mainPanel').scrollTop=0; }
function closeCompareView(){ if(prevSelection){ selectAll=prevSelection.selectAll; selected=prevSelection.selected; prevSelection=null; } else { selectAll=true; selected={}; } viewMode='agg'; refresh(); document.getElementById('mainPanel').scrollTop=0; }

function refresh(){
    renderFileList();
    const hasData=days.length>0;
    const ids=getSelIds();
    const sel=days.filter(d=>ids.includes(d._id));
    const n=sel.length;
    const mainPanel=document.getElementById('mainPanel');
    mainPanel.style.padding='20px'; mainPanel.style.overflowY='auto'; mainPanel.style.display='flex'; mainPanel.style.flexDirection='column'; mainPanel.style.gap='16px';
    document.getElementById('emptyState').style.display=hasData?'none':'flex';
    document.getElementById('aggContent').style.display='none';
    document.getElementById('cmpContent').style.display='none';
    if(!hasData) return;
    const canToggle=(n===2||n===3)&&!selectAll;
    const hasClose=!!prevSelection;
    const toggleBar=document.getElementById('viewToggleBar');
    toggleBar.classList.toggle('show', canToggle||hasClose);
    document.getElementById('vtabAgg').style.display=canToggle?'':'none';
    document.getElementById('vtabCmp').style.display=canToggle?'':'none';
    document.getElementById('vtabClose').style.borderLeft=canToggle?'1px solid var(--border)':'none';
    document.getElementById('vtabClose').style.borderRadius=canToggle?'0 8px 8px 0':'8px';
    if(!canToggle&&!hasClose) viewMode='agg';
    document.getElementById('vtabAgg').classList.toggle('active', viewMode==='agg');
    document.getElementById('vtabCmp').classList.toggle('active', viewMode==='cmp');
    if(canToggle&&viewMode==='cmp'){
        mainPanel.style.padding='10px 10px 0 10px'; mainPanel.style.overflowY='hidden'; mainPanel.style.gap='8px';
        const cmpEl=document.getElementById('cmpContent'); cmpEl.style.flex='1'; cmpEl.style.minHeight='0'; cmpEl.style.display='flex';
        renderComparison(sel);
    } else {
        const cmpEl=document.getElementById('cmpContent'); cmpEl.style.flex=''; cmpEl.style.minHeight='';
        document.getElementById('aggContent').style.display='flex';
        renderAgg(sel);
    }
}

function renderFileListVld(){
    const el=document.getElementById('fileListVld');
    if(!vldDays.length){ el.innerHTML='<div style="padding:20px;color:var(--text3);font-size:12.5px;text-align:center">No vehicles loaded</div>'; return; }
    const ss={};getSelVldIds().forEach(id=>ss[id]=true);
    let h=`<button class="fbtn fbtn-all${vldSelectAll?' sel':''}" data-action="all"><span class="fbtn-name">All Vehicles</span><span class="fbtn-score">${vldDays.length}</span></button>`;
    vldDays.forEach(d=>{
        const sel=!!ss[d._id];
        h+=`<button class="fbtn${sel?' sel':''}" data-action="day" data-id="${d._id}"><span class="fbtn-name">${d.sub_system_vehicle_id}</span><span class="fbtn-score">${d.total_km.toFixed(0)}km</span></button>`;
    });
    el.innerHTML=h;
    el.querySelectorAll('.fbtn').forEach(btn=>{
        btn.addEventListener('click',function(e){
            if(this.getAttribute('data-action')==='all'){vldSelectAll=true;vldSelected={};}
            else{
                const id=Number(this.getAttribute('data-id'));
                if(e.ctrlKey||e.metaKey){vldSelectAll=false;if(vldSelected[id])delete vldSelected[id];else vldSelected[id]=true;if(!Object.keys(vldSelected).length)vldSelectAll=true}
                else{vldSelectAll=false;vldSelected={};vldSelected[id]=true;}
            }
            const selectedCount=Object.keys(vldSelected).length;
            if(selectedCount===2||selectedCount===3) vldViewMode='cmp'; else if(selectedCount===1) vldViewMode='agg';
            refreshVld();
        });
    });
    document.getElementById('clearBtnVld').onclick=()=>{ vldDays=[]; vldSelected={}; vldSelectAll=true; refreshVld(); showToast('Cleared'); };
}

function renderAggVld(sel){
    let totalDist=0,noLoad=0,partLoad=0,fullLoad=0,numDaysSpan=1;
    const p=datePicker;
    numDaysSpan=Math.max(1, Math.ceil((p.end-p.start)/86400000));
    
    const sortedSel = [...sel].sort((a,b) => b.total_km - a.total_km);
    
    const vldModelStats = {}; 

    sortedSel.forEach(d=>{ 
        totalDist+=d.total_km; noLoad+=d.no_load_km; partLoad+=d.part_load_km; fullLoad+=d.full_load_km;
        
        const info = allVehicles.find(v => v.sub_system_vehicle_id === d.sub_system_vehicle_id);
        const model = info ? info.model : 'Unknown';
        if(!vldModelStats[model]) vldModelStats[model] = {loaded:0, total:0};
        vldModelStats[model].loaded += d.part_load_km + d.full_load_km;
        vldModelStats[model].total += d.total_km;
    });
    
    const loaded=partLoad+fullLoad;
    const loadedPct=totalDist>0?(loaded/totalDist*100):0;

    let bestModel = 'N/A', bestModelPct = 0;
    for (const m in vldModelStats) {
        const stat = vldModelStats[m];
        const pct = stat.total > 0 ? (stat.loaded / stat.total) * 100 : 0;
        if (pct > bestModelPct) {
            bestModelPct = pct;
            bestModel = m;
        }
    }

    set('vTotalDist', `${totalDist.toFixed(1)} km`);
    set('vAvgDistVeh', sortedSel.length ? `${(totalDist/sortedSel.length).toFixed(1)} km` : '—');
    set('vProductivity', `${loadedPct.toFixed(1)}%`);
    
    set('vldInsightDeadhead', `${noLoad.toFixed(1)} km (${totalDist>0?(noLoad/totalDist*100).toFixed(1):0}%)`);
    set('vldInsightBestModel', bestModel);
    set('vldInsightBestModelDesc', `${bestModelPct.toFixed(1)}% of total distance driven with a load.`);

    set('vNoLoadDist', `${noLoad.toFixed(1)} km`);
    set('vPartLoadDist', `${partLoad.toFixed(1)} km`);
    set('vFullLoadDist', `${fullLoad.toFixed(1)} km`);
    set('vNoLoadPct', totalDist>0?`${(noLoad/totalDist*100).toFixed(1)}% of total`:'—');
    set('vPartLoadPct', totalDist>0?`${(partLoad/totalDist*100).toFixed(1)}% of total`:'—');
    set('vFullLoadPct', totalDist>0?`${(fullLoad/totalDist*100).toFixed(1)}% of total`:'—');
    document.getElementById('vNoLoadBar').style.width=totalDist>0?`${(noLoad/totalDist*100).toFixed(0)}%`:'0%';
    document.getElementById('vPartLoadBar').style.width=totalDist>0?`${(partLoad/totalDist*100).toFixed(0)}%`:'0%';
    document.getElementById('vFullLoadBar').style.width=totalDist>0?`${(fullLoad/totalDist*100).toFixed(0)}%`:'0%';

    set('vLoadedDist', `${loaded.toFixed(1)} km`);
    set('vUnloadedDist', `${noLoad.toFixed(1)} km`);
    set('vAvgPerDay', `${(totalDist/numDaysSpan/Math.max(1,sortedSel.length)).toFixed(1)} km/vehicle/day`);

    const listEl=document.getElementById('vldPerVehicleList');
    listEl.innerHTML=sortedSel.map(d=>{
        const dLoaded=d.part_load_km+d.full_load_km;
        const dPct=d.total_km>0?(dLoaded/d.total_km*100).toFixed(0):'0';
        return `<div class="ritem"><span title="${d.sub_system_vehicle_id}">${d.sub_system_vehicle_id}</span><span>${d.total_km.toFixed(1)} km &middot; ${dPct}% loaded</span></div>`;
    }).join('')||'<div style="font-size:12.5px;color:var(--text3)">No vehicles</div>';

    const distData = Object.keys(vldModelStats).map(m => ({label:m, val: vldModelStats[m].loaded}));
    const pctData = Object.keys(vldModelStats).map(m => ({label:m, val: vldModelStats[m].total > 0 ? (vldModelStats[m].loaded/vldModelStats[m].total)*100 : 0}));
    renderGenericBarChart('vldModelDistChart', distData, 'km', 'var(--c)');
    renderGenericBarChart('vldModelPctChart', pctData, '%', 'var(--cg)');
}

function renderComparisonVld(vehicles){
    const cmp=document.getElementById('cmpContentVld');
    const gridCols = vehicles.length===3 ? 'grid-template-columns:1fr 1fr 1fr' : 'grid-template-columns:1fr 1fr';
    function colHtml(d){
        const dLoaded = d.part_load_km + d.full_load_km;
        const dPct = d.total_km>0 ? (dLoaded/d.total_km*100).toFixed(1) : '0';
        const noLoadPct = d.total_km>0 ? (d.no_load_km/d.total_km*100).toFixed(1) : '0';
        const partLoadPct = d.total_km>0 ? (d.part_load_km/d.total_km*100).toFixed(1) : '0';
        const fullLoadPct = d.total_km>0 ? (d.full_load_km/d.total_km*100).toFixed(1) : '0';
        function ir(label,val,cls=''){return`<div class="ir" style="cursor:default"><span class="ir-l">${label}</span><span class="ir-v ${cls}">${val}</span></div>`}
        return`<div class="cmp-col"><div class="cmp-header">${d.sub_system_vehicle_id}</div>
            <div class="icard"><div class="ict"><span class="dot" style="background:var(--c)"></span>Trip Summary</div>${ir('Total Distance',d.total_km.toFixed(1)+' km')}${ir('Loaded Distance',dLoaded.toFixed(1)+' km','g')}${ir('Loaded %',dPct+'%','g')}</div>
            <div class="icard"><div class="ict"><span class="dot" style="background:var(--text3)"></span>Load Breakdown</div>${ir('No Load',d.no_load_km.toFixed(1)+' km ('+noLoadPct+'%)')}${ir('Part Load',d.part_load_km.toFixed(1)+' km ('+partLoadPct+'%)','w')}${ir('Full Load',d.full_load_km.toFixed(1)+' km ('+fullLoadPct+'%)','w')}</div>
        </div>`;
    }
    cmp.innerHTML=`<div class="cmp-wrap" style="${gridCols};height:100%;overflow:hidden;display:grid">${vehicles.map(colHtml).join('')}</div>`;
}

function setVldViewMode(mode){ vldViewMode=mode; document.getElementById('vtabAggVld').classList.toggle('active', mode==='agg'); document.getElementById('vtabCmpVld').classList.toggle('active', mode==='cmp'); refreshVld(); document.getElementById('mainPanelVld').scrollTop=0; }
function compareVehicleIdsVld(ids){ vldPrevSelection={vldSelectAll, vldSelected:{...vldSelected}}; vldSelectAll=false; vldSelected={}; ids.forEach(id=>vldSelected[id]=true); vldViewMode='cmp'; refreshVld(); document.getElementById('mainPanelVld').scrollTop=0; }
function selectSingleVehicleVld(id){ vldPrevSelection={vldSelectAll, vldSelected:{...vldSelected}}; vldSelectAll=false; vldSelected={}; vldSelected[id]=true; vldViewMode='agg'; refreshVld(); document.getElementById('mainPanelVld').scrollTop=0; }
function closeCompareViewVld(){ if(vldPrevSelection){ vldSelectAll=vldPrevSelection.vldSelectAll; vldSelected=vldPrevSelection.vldSelected; vldPrevSelection=null; } else { vldSelectAll=true; vldSelected={}; } vldViewMode='agg'; refreshVld(); document.getElementById('mainPanelVld').scrollTop=0; }

function refreshVld(){
    renderFileListVld();
    const hasData=vldDays.length>0;
    document.getElementById('emptyStateVld').style.display=hasData?'none':'flex';
    document.getElementById('aggContentVld').style.display='none';
    document.getElementById('cmpContentVld').style.display='none';
    if(!hasData) return;

    const ids=getSelVldIds();
    const sel=vldDays.filter(d=>ids.includes(d._id));
    const n=sel.length;

    const mainPanel=document.getElementById('mainPanelVld');
    mainPanel.style.padding='20px'; mainPanel.style.overflowY='auto'; mainPanel.style.display='flex'; mainPanel.style.flexDirection='column'; mainPanel.style.gap='16px';

    const canToggle=(n===2||n===3)&&!vldSelectAll;
    const hasClose=!!vldPrevSelection;
    const toggleBar=document.getElementById('viewToggleBarVld');
    toggleBar.classList.toggle('show', canToggle||hasClose);
    document.getElementById('vtabAggVld').style.display=canToggle?'':'none';
    document.getElementById('vtabCmpVld').style.display=canToggle?'':'none';
    document.getElementById('vtabCloseVld').style.borderLeft=canToggle?'1px solid var(--border)':'none';
    document.getElementById('vtabCloseVld').style.borderRadius=canToggle?'0 8px 8px 0':'8px';
    if(!canToggle&&!hasClose) vldViewMode='agg';
    document.getElementById('vtabAggVld').classList.toggle('active', vldViewMode==='agg');
    document.getElementById('vtabCmpVld').classList.toggle('active', vldViewMode==='cmp');

    if(canToggle&&vldViewMode==='cmp'){
        mainPanel.style.padding='10px 10px 0 10px'; mainPanel.style.overflowY='hidden'; mainPanel.style.gap='8px';
        const cmpEl=document.getElementById('cmpContentVld'); cmpEl.style.flex='1'; cmpEl.style.minHeight='0'; cmpEl.style.display='flex';
        renderComparisonVld(sel);
    } else {
        const cmpEl=document.getElementById('cmpContentVld'); cmpEl.style.flex=''; cmpEl.style.minHeight='';
        document.getElementById('aggContentVld').style.display='flex';
        renderAggVld(sel);
    }
}
</script>
</body>
</html>
"""

# ── DATABASE LAYER ─────────────────────────────────────────────────────
def get_db_connection():
    if not MYSQL_AVAILABLE: return None
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        db_conf = config.get('database', {})
        db_url = os.environ.get('DATABASE_URL', '')

        if db_url:
            parsed = urlparse(db_url)
            conn = mysql.connector.connect(
                host=parsed.hostname,
                port=parsed.port or 3306,
                user=parsed.username,
                password=parsed.password,
                database=(parsed.path or '/').lstrip('/')
            )
            return conn

        # Environment variables can override config.json for cloud deployments.
        db_host = os.environ.get('MYSQL_HOST') or os.environ.get('MYSQLHOST') or db_conf.get('host', 'localhost')
        db_user = os.environ.get('MYSQL_USER') or os.environ.get('MYSQLUSER') or db_conf.get('user', 'root')
        db_password = os.environ.get('MYSQL_PASSWORD') or os.environ.get('MYSQLPASSWORD') or db_conf.get('password', '')
        db_name = os.environ.get('MYSQL_DATABASE') or os.environ.get('MYSQLDATABASE') or db_conf.get('database', 'fleet_analytics')
        db_port = int(os.environ.get('MYSQL_PORT') or os.environ.get('MYSQLPORT') or 3306)
        conn = mysql.connector.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            database=db_name
        )
        return conn
    except Error as e:
        logging.error(f"Database Connection Error: {e}")
        return None

def setup_database_tables():
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor()
    try:
        cursor.execute("CREATE TABLE IF NOT EXISTS makes (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE)")
        cursor.execute("CREATE TABLE IF NOT EXISTS models (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL, make_id INT NOT NULL, UNIQUE KEY unique_model_per_make (name, make_id), FOREIGN KEY (make_id) REFERENCES makes(id) ON DELETE CASCADE)")
        cursor.execute("CREATE TABLE IF NOT EXISTS variants (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL, model_id INT NOT NULL, UNIQUE KEY unique_variant_per_model (name, model_id), FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE)")
        cursor.execute("""CREATE TABLE IF NOT EXISTS vehicles (
            id INT AUTO_INCREMENT PRIMARY KEY,
            sub_system_vehicle_id VARCHAR(150) NOT NULL UNIQUE,
            variant_id INT NOT NULL,
            sub_start_time DATETIME,
            FOREIGN KEY (variant_id) REFERENCES variants(id) ON DELETE CASCADE
        )""")

        cursor.execute("CREATE TABLE IF NOT EXISTS vld_makes (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE)")
        cursor.execute("CREATE TABLE IF NOT EXISTS vld_models (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL, make_id INT NOT NULL, UNIQUE KEY unique_model_per_make (name, make_id), FOREIGN KEY (make_id) REFERENCES vld_makes(id) ON DELETE CASCADE)")
        cursor.execute("CREATE TABLE IF NOT EXISTS vld_variants (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL, model_id INT NOT NULL, UNIQUE KEY unique_variant_per_model (name, model_id), FOREIGN KEY (model_id) REFERENCES vld_models(id) ON DELETE CASCADE)")
        cursor.execute("""CREATE TABLE IF NOT EXISTS vld_vehicles (
            id INT AUTO_INCREMENT PRIMARY KEY,
            sub_system_vehicle_id VARCHAR(150) NOT NULL UNIQUE,
            variant_id INT NOT NULL,
            sub_start_time DATETIME,
            FOREIGN KEY (variant_id) REFERENCES vld_variants(id) ON DELETE CASCADE
        )""")
        conn.commit()
        logging.info("Database tables verified (DA + VLD).")
    except Error as e:
        logging.error(f"Error verifying tables: {e}")
    finally:
        cursor.close()
        conn.close()

CUTOFF_DATE = datetime(2025, 5, 9, tzinfo=timezone.utc)

# ── REGISTRY FETCHES ──
def _fetch_registry(registry_conf_key, token, log_label):
    if not token:
        logging.error(f"Cannot fetch {log_label} registry: auth token unavailable.")
        return []
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    except Exception:
        return []
    reg_conf = config.get(registry_conf_key, {})
    base_url = reg_conf.get('base_url')
    endpoint = reg_conf.get('endpoint')
    if not base_url or not endpoint:
        logging.error(f"{registry_conf_key}.base_url/endpoint missing from config.")
        return []
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {'Authorization': f'Bearer {token}'}
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get('data', payload)
        customers = data if isinstance(data, list) else [data]
        subs = []
        for cust in customers:
            if not isinstance(cust, dict):
                continue
            for sub in cust.get('subscriptions', []) or []:
                subs.append(sub)
        return subs
    except Exception as e:
        logging.error(f"{log_label} registry fetch error: {e}")
        return []

def get_da_registry_data():
    token = get_access_token()
    return _fetch_registry('vehicle_registry', token, 'DA')

def get_vld_registry_data():
    token = get_vld_access_token()
    return _fetch_registry('vld_vehicle_registry', token, 'VLD')

def _parse_sub_date(sub):
    sub_str = sub.get('subscriptionStartTime')
    if not sub_str:
        return None
    try:
        d = datetime.fromisoformat(str(sub_str).replace('Z', '+00:00'))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None

def _extract_da_rows(subscriptions):
    rows = []
    for sub in subscriptions:
        v = sub.get('vehicle', {}) or {}
        sub_system_id = v.get('subSystemVehicleId')
        make = str(v.get('make') or 'Unknown')
        model = str(v.get('model') or 'Unknown')
        variant = str(v.get('variant') or 'Unknown')
        sub_date = _parse_sub_date(sub)
        if not sub_system_id or not sub_date or sub_date <= CUTOFF_DATE:
            continue
        rows.append({
            'sub_system_vehicle_id': sub_system_id,
            'make': make, 'model': model, 'variant': variant, 'sub_time': sub_date
        })
    return rows

def _extract_vld_rows(subscriptions, subsystem_to_makemodel):
    rows = []
    for sub in subscriptions:
        sub_system_id = sub.get('subSystemVehicleId')
        sub_date = _parse_sub_date(sub)
        if not sub_system_id or not sub_date or sub_date <= CUTOFF_DATE:
            continue
        make, model, variant = subsystem_to_makemodel.get(sub_system_id, ('Unknown', 'Unknown', 'Unknown'))
        rows.append({
            'sub_system_vehicle_id': sub_system_id,
            'make': make, 'model': model, 'variant': variant, 'sub_time': sub_date
        })
    return rows

def _sync_rows_to_tables(rows, makes_tbl, models_tbl, variants_tbl, vehicles_tbl):
    conn = get_db_connection()
    if not conn: return 0
    conn.autocommit = True
    cursor = conn.cursor(dictionary=True)
    make_cache, model_cache, variant_cache = {}, {}, {}
    cursor.execute(f"SELECT id, name FROM {makes_tbl}")
    for row in cursor.fetchall(): make_cache[row['name']] = row['id']
    cursor.execute(f"SELECT id, name, make_id FROM {models_tbl}")
    for row in cursor.fetchall(): model_cache[f"{row['make_id']}_{row['name']}"] = row['id']
    cursor.execute(f"SELECT id, name, model_id FROM {variants_tbl}")
    for row in cursor.fetchall(): variant_cache[f"{row['model_id']}_{row['name']}"] = row['id']

    count = 0
    for v in rows:
        make_id = make_cache.get(v['make'])
        if not make_id:
            cursor.execute(
                f"INSERT INTO {makes_tbl} (name) VALUES (%s) ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)",
                (v['make'],)
            )
            make_id = cursor.lastrowid
            make_cache[v['make']] = make_id
        m_key = f"{make_id}_{v['model']}"
        model_id = model_cache.get(m_key)
        if not model_id:
            cursor.execute(
                f"INSERT INTO {models_tbl} (name, make_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)",
                (v['model'], make_id)
            )
            model_id = cursor.lastrowid
            model_cache[m_key] = model_id
        v_key = f"{model_id}_{v['variant']}"
        variant_id = variant_cache.get(v_key)
        if not variant_id:
            cursor.execute(
                f"INSERT INTO {variants_tbl} (name, model_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)",
                (v['variant'], model_id)
            )
            variant_id = cursor.lastrowid
            variant_cache[v_key] = variant_id

        cursor.execute(f"""
            INSERT INTO {vehicles_tbl} (sub_system_vehicle_id, variant_id, sub_start_time)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE variant_id=VALUES(variant_id), sub_start_time=VALUES(sub_start_time)
        """, (v['sub_system_vehicle_id'], variant_id, v['sub_time']))
        count += 1
    cursor.close()
    conn.close()
    return count

def sync_registry_to_db():
    if not MYSQL_AVAILABLE: return

    da_subs = get_da_registry_data()
    da_rows = _extract_da_rows(da_subs) if da_subs else []
    logging.info(f"[DA] registry returned {len(da_subs)} subscriptions, {len(da_rows)} eligible vehicles.")

    subsystem_to_makemodel = {
        r['sub_system_vehicle_id']: (r['make'], r['model'], r['variant'])
        for r in da_rows if r.get('sub_system_vehicle_id')
    }

    vld_subs = get_vld_registry_data()
    vld_rows = _extract_vld_rows(vld_subs, subsystem_to_makemodel) if vld_subs else []
    unmatched = sum(1 for r in vld_rows if r['make'] == 'Unknown')
    logging.info(f"[VLD] registry returned {len(vld_subs)} subscriptions, {len(vld_rows)} eligible vehicles ({unmatched} without a DA subSystemVehicleId match).")

    da_count = _sync_rows_to_tables(da_rows, 'makes', 'models', 'variants', 'vehicles') if da_rows else 0
    vld_count = _sync_rows_to_tables(vld_rows, 'vld_makes', 'vld_models', 'vld_variants', 'vld_vehicles') if vld_rows else 0
    logging.info(f"Registry sync complete. DA vehicles: {da_count}, VLD vehicles: {vld_count}.")

def get_vehicle_filters_from_db(vld=False):
    if not MYSQL_AVAILABLE: return []
    conn = get_db_connection()
    if not conn: return []
    try:
        cursor = conn.cursor(dictionary=True)
        if vld:
            query = """
            SELECT v.sub_system_vehicle_id, ma.name as make, mo.name as model, va.name as variant
            FROM vld_vehicles v
            JOIN vld_variants va ON v.variant_id = va.id
            JOIN vld_models mo ON va.model_id = mo.id
            JOIN vld_makes ma ON mo.make_id = ma.id
            ORDER BY ma.name, mo.name, va.name
            """
        else:
            query = """
            SELECT v.sub_system_vehicle_id, ma.name as make, mo.name as model, va.name as variant
            FROM vehicles v
            JOIN variants va ON v.variant_id = va.id
            JOIN models mo ON va.model_id = mo.id
            JOIN makes ma ON mo.make_id = ma.id
            ORDER BY ma.name, mo.name, va.name
            """
        cursor.execute(query)
        results = cursor.fetchall()
        return [dict(r) for r in results]
    except Exception as e:
        logging.error(f"DB Filter Error: {e}")
        return []
    finally:
        if conn.is_connected(): conn.close()

# ── AUTH ─────────────────────────────────────────────────────────────
def _do_get_token(auth_conf, cache, force_refresh=False):
    now = datetime.now(timezone.utc).timestamp()
    if not force_refresh and "token" in cache and now < cache.get("expires_at", 0):
        return cache["token"]
    try:
        url = f"{auth_conf['base_url'].rstrip('/')}/{auth_conf['endpoint'].lstrip('/')}"
        payload = {"clientId": auth_conf['client_id'], "clientSecret": auth_conf['client_secret']}
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        token_data = response.json().get('data', {})
        access_token = token_data.get('accessToken')
        if access_token:
            cache["token"] = access_token
            cache["expires_at"] = now + TOKEN_EXPIRY_SECONDS
            return access_token
        return None
    except Exception as e:
        logging.error("Auth Error: %s", e)
        return None

def get_access_token(force_refresh=False):
    try:
        with open(CONFIG_FILE, 'r') as f: config = json.load(f)
    except Exception:
        return None
    return _do_get_token(config.get('auth', {}), AUTH_TOKEN_CACHE, force_refresh)

def get_vld_access_token(force_refresh=False):
    try:
        with open(CONFIG_FILE, 'r') as f: config = json.load(f)
    except Exception:
        return None
    return _do_get_token(config.get('vld_auth', {}), VLD_AUTH_TOKEN_CACHE, force_refresh)

# ── DECRYPTION ──────────────────────────────────────────────────────
def decrypt_payload(encrypted_data, decrypt_conf):
    base_url = decrypt_conf.get('base_url')
    endpoint = decrypt_conf.get('endpoint')
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    body = {
        "clientId": decrypt_conf.get('client_id'),
        "clientSecret": decrypt_conf.get('client_secret'),
        "data": encrypted_data
    }
    resp = requests.post(url, json=body, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"Decryption Failed: {resp.text[:80]}")
    raw = resp.json()
    data_payload = raw if isinstance(raw, str) else (raw.get('Data') or raw.get('data') if isinstance(raw, dict) else raw)
    final_content = raw
    if data_payload:
        if isinstance(data_payload, str):
            try:
                final_content = json.loads(data_payload)
            except json.JSONDecodeError:
                try:
                    final_content = ast.literal_eval(data_payload)
                except Exception:
                    final_content = data_payload
        elif isinstance(data_payload, dict):
            final_content = data_payload
    return final_content

# ── DA PIPELINE ─────────────────────────────────────────────────────
def process_vehicle(v_id, config, token, from_date, to_date):
    pred_config = config.get('prediction_service', {})
    pred_base_url = pred_config.get('base_url')
    pred_template = pred_config.get('url_template')
    path_only = pred_template.split('?')[0]
    base_request_url = f"{pred_base_url.rstrip('/')}/{path_only.lstrip('/')}".format(id=v_id)
    query_params = {"from": from_date, "to": to_date}

    def _attempt(auth_token):
        headers = {'Authorization': f'Bearer {auth_token}', 'User-Agent': 'PostmanRuntime/7.32.3', 'Accept': '*/*'}
        return requests.get(base_request_url, headers=headers, params=query_params, timeout=15)

    try:
        pred_response = _attempt(token)
        if pred_response.status_code in (400, 401, 403):
            logging.warning(f"Token rejected (HTTP {pred_response.status_code}) for {v_id}, refreshing token and retrying...")
            fresh_token = get_access_token(force_refresh=True)
            if fresh_token:
                pred_response = _attempt(fresh_token)
            else:
                return {"sub_system_vehicle_id": v_id, "status": "failed", "reason": "Token refresh failed"}

        if pred_response.status_code == 200:
            pred_json = pred_response.json()
            encrypted_data = pred_json.get('Data') or pred_json.get('data')
            if encrypted_data:
                try:
                    final_content = decrypt_payload(encrypted_data, config.get('decryption_service', {}))
                    return {"sub_system_vehicle_id": v_id, "status": "success", "data": final_content}
                except Exception as e:
                    return {"sub_system_vehicle_id": v_id, "status": "failed", "reason": str(e)[:60]}
            else:
                return {"sub_system_vehicle_id": v_id, "status": "failed", "reason": "No 'Data' field found"}
        else:
            return {"sub_system_vehicle_id": v_id, "status": "failed", "reason": f"Pred API {pred_response.status_code}"}
    except Exception as e:
        return {"sub_system_vehicle_id": v_id, "status": "failed", "reason": str(e)[:30]}

def fetch_and_process_data(params):
    global DATA_STORE
    DATA_STORE = {"success": [], "failed": [], "total_eligible": 0}
    token = get_access_token()
    if not token: return {"error": "Auth Failed"}
    try:
        with open(CONFIG_FILE, 'r') as f: config = json.load(f)
    except Exception:
        return {"error": "Config missing"}

    try:
        start_ist = datetime.strptime(params['start_ist_local'], '%Y-%m-%d %H:%M:%S')
        end_ist = datetime.strptime(params['end_ist_local'], '%Y-%m-%d %H:%M:%S')
    except Exception:
        return {"error": "Invalid date range"}

    start_utc = start_ist - IST_OFFSET
    end_utc = end_ist - IST_OFFSET
    from_date = start_utc.strftime('%Y-%m-%d %H:%M:%S')
    to_date = end_utc.strftime('%Y-%m-%d %H:%M:%S')

    vehicle_ids = params.get('vehicle_ids', [])
    if not vehicle_ids and MYSQL_AVAILABLE:
        vehicles = get_vehicle_filters_from_db(vld=False)
        vehicle_ids = [v['sub_system_vehicle_id'] for v in vehicles]
    if not vehicle_ids: return {"message": "No vehicles selected"}

    DATA_STORE['total_eligible'] = len(vehicle_ids)
    logging.info(f"[DA] Fetching {len(vehicle_ids)} vehicles: IST {params['start_ist_local']}\u2192{params['end_ist_local']}  (UTC {from_date}\u2192{to_date})")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_vehicle, v_id, config, token, from_date, to_date): v_id for v_id in vehicle_ids}
        for future in as_completed(futures):
            result = future.result()
            with DATA_LOCK:
                if result['status'] == 'success':
                    DATA_STORE["success"].append({"sub_system_vehicle_id": result['sub_system_vehicle_id'], "data": result['data']})
                else:
                    DATA_STORE["failed"].append({"sub_system_vehicle_id": result['sub_system_vehicle_id'], "reason": result['reason']})
    logging.info(f"[DA] Done. Success:{len(DATA_STORE['success'])} Failed:{len(DATA_STORE['failed'])}")
    return {"status": "ok"}

# ── VLD PIPELINE ─────────────────────────────────────────────────────
def process_vehicle_vld(v_id, config, token, from_iso, to_iso):
    pred_config = config.get('vld_prediction_service', {})
    base_url = pred_config.get('base_url')
    url_template = pred_config.get('url_template', '/load-detection/data/api/vehicles/{id}?st={from_date}&et={to_date}')
    path_and_query = url_template.format(id=v_id, from_date=from_iso, to_date=to_iso)
    url = f"{base_url.rstrip('/')}/{path_and_query.lstrip('/')}"

    def _attempt(auth_token):
        headers = {'Authorization': f'Bearer {auth_token}', 'Accept': '*/*'}
        return requests.get(url, headers=headers, timeout=20)

    try:
        resp = _attempt(token)
        if resp.status_code in (400, 401, 403):
            fresh_token = get_vld_access_token(force_refresh=True)
            if fresh_token:
                resp = _attempt(fresh_token)
            else:
                return {"sub_system_vehicle_id": v_id, "status": "failed", "reason": "Token refresh failed"}

        if resp.status_code != 200:
            return {"sub_system_vehicle_id": v_id, "status": "failed", "reason": f"VLD API {resp.status_code}"}

        body = resp.json()
        encrypted_data = body.get('data') or body.get('Data')
        if not encrypted_data:
            return {"sub_system_vehicle_id": v_id, "status": "failed", "reason": "No 'data' field found"}

        decrypted = decrypt_payload(encrypted_data, config.get('vld_decryption_service', {}))
        if isinstance(decrypted, str):
            try:
                decrypted = json.loads(decrypted)
            except json.JSONDecodeError:
                decrypted = ast.literal_eval(decrypted)

        trips = decrypted.get('trip', []) if isinstance(decrypted, dict) else []
        no_load_km = part_load_km = full_load_km = total_km = 0.0
        for t in trips:
            pr = t.get('predictedResult', {}) or {}
            load = (pr.get('load') or '').strip()
            dist = float(pr.get('distanceValue') or 0)
            total_km += dist
            if load == 'No Load':
                no_load_km += dist
            elif load == 'Part Load':
                part_load_km += dist
            elif load == 'Full Load':
                full_load_km += dist

        return {
            "sub_system_vehicle_id": v_id, "status": "success",
            "no_load_km": no_load_km, "part_load_km": part_load_km,
            "full_load_km": full_load_km, "total_km": total_km
        }
    except Exception as e:
        return {"sub_system_vehicle_id": v_id, "status": "failed", "reason": str(e)[:60]}

def fetch_and_process_data_vld(params):
    global VLD_DATA_STORE
    VLD_DATA_STORE = {"success": [], "failed": [], "total_eligible": 0}
    token = get_vld_access_token()
    if not token: return {"error": "VLD Auth Failed"}
    try:
        with open(CONFIG_FILE, 'r') as f: config = json.load(f)
    except Exception:
        return {"error": "Config missing"}

    try:
        start_local = params['start_ist_local']
        end_local = params['end_ist_local']
        from_iso = f"{start_local}+05:30"
        to_iso = f"{end_local}+05:30"
    except Exception:
        return {"error": "Invalid date range"}

    vehicle_ids = params.get('vehicle_ids', [])
    if not vehicle_ids and MYSQL_AVAILABLE:
        vehicles = get_vehicle_filters_from_db(vld=True)
        vehicle_ids = [v['sub_system_vehicle_id'] for v in vehicles]
    if not vehicle_ids: return {"message": "No vehicles selected"}

    VLD_DATA_STORE['total_eligible'] = len(vehicle_ids)
    logging.info(f"[VLD] Fetching {len(vehicle_ids)} vehicles: {from_iso} \u2192 {to_iso}")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_vehicle_vld, v_id, config, token, from_iso, to_iso): v_id for v_id in vehicle_ids}
        for future in as_completed(futures):
            result = future.result()
            with DATA_LOCK:
                if result['status'] == 'success':
                    VLD_DATA_STORE["success"].append(result)
                else:
                    VLD_DATA_STORE["failed"].append({"sub_system_vehicle_id": result['sub_system_vehicle_id'], "reason": result.get('reason')})
    logging.info(f"[VLD] Done. Success:{len(VLD_DATA_STORE['success'])} Failed:{len(VLD_DATA_STORE['failed'])}")
    return {"status": "ok"}

def get_session_id():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=32))

class FleetHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200); self.send_header('Content-type', 'text/html'); self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode('utf-8'))
        elif self.path == '/api/check-session':
            ok = self._check_session()
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps({"logged_in": ok}).encode())
        elif self.path == '/api/da/vehicles/filters':
            if not self._check_session(): self.send_response(403); self.end_headers(); return
            data = get_vehicle_filters_from_db(vld=False)
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        elif self.path == '/api/vld/vehicles/filters':
            if not self._check_session(): self.send_response(403); self.end_headers(); return
            data = get_vehicle_filters_from_db(vld=True)
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/api/login':
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            try:
                with open(CONFIG_FILE, 'r') as f: config = json.load(f)
                auth_config = config.get('auth', {})
                client_id = data.get('client_id', '')
                client_secret = data.get('client_secret', '')
                url = f"{auth_config['base_url'].rstrip('/')}/{auth_config['endpoint'].lstrip('/')}"
                payload = {"clientId": client_id, "clientSecret": client_secret}
                resp = requests.post(url, json=payload, timeout=10)
                if resp.status_code == 200:
                    token_data = resp.json().get('data', {})
                    access_token = token_data.get('accessToken')
                    if access_token:
                        now = datetime.now(timezone.utc).timestamp()
                        AUTH_TOKEN_CACHE['token'] = access_token
                        AUTH_TOKEN_CACHE['expires_at'] = now + TOKEN_EXPIRY_SECONDS
                        sid = get_session_id()
                        with SESSION_LOCK: SESSIONS[sid] = True
                        self.send_response(200); self.send_header('Content-type', 'application/json')
                        self.send_header('Set-Cookie', f'session_id={sid}; Path=/; HttpOnly'); self.end_headers()
                        self.wfile.write(json.dumps({"success": True}).encode())
                    else:
                        self.send_response(200); self.end_headers()
                        self.wfile.write(json.dumps({"success": False, "message": "No token in response"}).encode())
                else:
                    msg = f"Auth API returned {resp.status_code}"
                    try: msg = resp.json().get('message', msg)
                    except Exception: pass
                    self.send_response(200); self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "message": msg}).encode())
            except Exception as e:
                logging.error("Login error: %s", e)
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": "Server error: " + str(e)[:60]}).encode())

        elif self.path == '/api/logout':
            cookie = self.headers.get('Cookie', '')
            for c in cookie.split(';'):
                if 'session_id=' in c:
                    sid = c.strip().split('=')[1]
                    with SESSION_LOCK:
                        if sid in SESSIONS: del SESSIONS[sid]
            self.send_response(200); self.end_headers()

        elif self.path == '/api/da/fetch':
            if not self._check_session(): self.send_response(403); self.end_headers(); return
            params = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            try:
                fetch_and_process_data(params)
                resp = {"total_eligible": DATA_STORE['total_eligible'], "success": DATA_STORE['success'], "failed": DATA_STORE['failed']}
                self.send_response(200); self.send_header('content-type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps(resp).encode())
            except Exception as e:
                self.send_response(500); self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        elif self.path == '/api/vld/fetch':
            if not self._check_session(): self.send_response(403); self.end_headers(); return
            params = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            try:
                fetch_and_process_data_vld(params)
                resp = {"total_eligible": VLD_DATA_STORE['total_eligible'], "success": VLD_DATA_STORE['success'], "failed": VLD_DATA_STORE['failed']}
                self.send_response(200); self.send_header('content-type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps(resp).encode())
            except Exception as e:
                self.send_response(500); self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        elif self.path == '/api/registry/sync':
            if not self._check_session(): self.send_response(403); self.end_headers(); return
            threading.Thread(target=sync_registry_to_db, daemon=True).start()
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps({"status": "syncing"}).encode())

    def _check_session(self):
        cookie = self.headers.get('Cookie', '')
        for c in cookie.split(';'):
            if 'session_id=' in c:
                sid = c.strip().split('=')[1]
                if sid in SESSIONS: return True
        return False

    def log_message(self, format, *args):
        if 'favicon.ico' not in str(args): super().log_message(format, *args)

def start_server():
    if MYSQL_AVAILABLE:
        setup_database_tables()
        threading.Thread(target=sync_registry_to_db, daemon=True).start()
    else:
        logging.warning("Starting without database features.")
    with socketserver.TCPServer(("", PORT), FleetHandler) as httpd:
        logging.info(f"Serving at http://localhost:{PORT}")
        httpd.serve_forever()

if __name__ == '__main__':
    start_server()