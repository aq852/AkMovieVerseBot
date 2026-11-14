import logging
import time
import urllib.parse
import re
import datetime
import json
import mimetypes
import asyncio
from html import escape as html_escape
from bson.objectid import ObjectId
from aiohttp import web
from config import Config
from database.mongo import mongo
from utils.ranges import parse_range, RangeNotSatisfiable
from utils.custom_dl import TGCustomStreamer, ServerBusyError
from utils.helpers import get_readable_size, parse_media_metadata, get_cached_poster_url
from database.files import get_related_files, get_search_results, count_files

logger = logging.getLogger(__name__)

VERIFY_GATEWAY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>AkMovieVerse — Verification Gateway</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            -webkit-touch-callout: none;
            -webkit-user-select: none;
            -moz-user-select: none;
            -ms-user-select: none;
            user-select: none;
        }}
        body {{
            background: radial-gradient(circle at top, #1e2638, #0a0e17 80%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #ffffff;
            padding: 20px;
        }}
        .card {{
            background: rgba(22, 27, 34, 0.85);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 24px;
            padding: 40px 30px;
            max-width: 440px;
            width: 100%;
            text-align: center;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6);
            animation: fadeIn 0.6s ease-out;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(20px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(56, 189, 248, 0.15);
            color: #38bdf8;
            padding: 6px 14px;
            border-radius: 30px;
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 24px;
            border: 1px solid rgba(56, 189, 248, 0.25);
        }}
        .timer-circle {{
            position: relative;
            width: 100px;
            height: 100px;
            margin: 0 auto 24px auto;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            background: conic-gradient(#38bdf8 0deg, #1e293b 0deg);
            box-shadow: 0 0 25px rgba(56, 189, 248, 0.35);
        }}
        .timer-inner {{
            width: 82px;
            height: 82px;
            background: #0f172a;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 34px;
            font-weight: 800;
            color: #38bdf8;
        }}
        h1 {{
            font-size: 22px;
            font-weight: 700;
            margin-bottom: 10px;
            color: #f8fafc;
        }}
        p {{
            font-size: 14px;
            color: #94a3b8;
            line-height: 1.6;
            margin-bottom: 24px;
        }}
        .progress-container {{
            width: 100%;
            height: 6px;
            background: rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            overflow: hidden;
            margin-bottom: 20px;
        }}
        .progress-bar {{
            width: 0%;
            height: 100%;
            background: linear-gradient(90deg, #38bdf8, #818cf8);
            border-radius: 6px;
            transition: width 1s linear;
        }}
        .status {{
            font-size: 13px;
            color: #64748b;
            margin-bottom: 24px;
            font-style: italic;
        }}
        .btn {{
            display: inline-block;
            background: linear-gradient(135deg, #0284c7, #2563eb);
            color: #ffffff;
            border: none;
            outline: none;
            cursor: pointer;
            padding: 13px 26px;
            border-radius: 12px;
            font-weight: 600;
            font-size: 14px;
            transition: all 0.2s ease;
            box-shadow: 0 4px 15px rgba(37, 99, 235, 0.4);
        }}
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(37, 99, 235, 0.6);
        }}
        .btn:active {{
            transform: translateY(0);
        }}
    </style>
</head>
<body oncontextmenu="return false;" onselectstart="return false;" ondragstart="return false;">
    <div class="card">
        <div class="badge">
            <span>🛡️</span> Secure Verification Gateway
        </div>
        <div class="timer-circle" id="circle">
            <div class="timer-inner" id="timer-num">5</div>
        </div>
        <h1>AkMovieVerse Verification</h1>
        <p>Loading your <b>24-Hour Unlimited VIP Access Pass</b> in the background. Please wait a moment...</p>
        <div class="progress-container">
            <div class="progress-bar" id="progress-bar"></div>
        </div>
        <div class="status" id="status-text">⚡ Connecting to secure gateway in 5 seconds...</div>
        <div>
            <button type="button" class="btn" id="manual-btn" onclick="proceedToVerification()">Proceed to Verification ↗️</button>
        </div>
    </div>

    <script>
        const _k = "{target_b64}";
        function getTarget() {{
            try {{
                return atob(_k);
            }} catch(e) {{
                return "";
            }}
        }}

        function proceedToVerification() {{
            const u = getTarget();
            if (u) {{
                window.location.replace(u);
            }}
        }}

        let count = 5;
        const timerNum = document.getElementById("timer-num");
        const progressBar = document.getElementById("progress-bar");
        const statusText = document.getElementById("status-text");
        const circle = document.getElementById("circle");

        const interval = setInterval(() => {{
            count--;
            if (count > 0) {{
                timerNum.innerText = count;
                progressBar.style.width = ((5 - count) / 5 * 100) + "%";
                circle.style.background = `conic-gradient(#38bdf8 ${{(5 - count) * 72}}deg, #1e293b 0deg)`;
                statusText.innerText = `⚡ Connecting to secure gateway in ${{count}} seconds...`;
            }} else {{
                clearInterval(interval);
                timerNum.innerText = "✓";
                progressBar.style.width = "100%";
                circle.style.background = "#10b981";
                statusText.innerText = "🚀 Redirecting to verification now...";
                proceedToVerification();
            }}
        }}, 1000);

        // Bulletproof Anti-Right-Click & Stealth URL Inspection Shield
        (function () {{
            function killEvent(e) {{
                if (e) {{
                    if (e.preventDefault) e.preventDefault();
                    if (e.stopPropagation) e.stopPropagation();
                    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                }}
                return false;
            }}

            window.addEventListener("contextmenu", killEvent, true);
            document.addEventListener("contextmenu", killEvent, true);
            window.addEventListener("selectstart", killEvent, true);
            document.addEventListener("selectstart", killEvent, true);
            window.addEventListener("dragstart", killEvent, true);
            document.addEventListener("dragstart", killEvent, true);
            window.oncontextmenu = killEvent;
            document.oncontextmenu = killEvent;

            window.addEventListener("keydown", function (e) {{
                if (
                    e.keyCode === 123 ||
                    (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74 || e.keyCode === 75 || e.keyCode === 69)) ||
                    (e.metaKey && e.altKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74)) ||
                    ((e.ctrlKey || e.metaKey) && (e.keyCode === 85 || e.keyCode === 83 || e.keyCode === 80))
                ) {{
                    return killEvent(e);
                }}
            }}, true);

            // Stealth URL Cloaker: Masks href for desktop status bar, preserves native app & intent schemes
            function maskLink(el) {{
                if (!el || !el.getAttribute) return;
                const href = el.getAttribute('href');
                if (!href || href.startsWith('javascript:') || href === '#' || href.startsWith('#')) return;
                if (href.startsWith('intent:') || href.startsWith('vlc:') || href.startsWith('vlc-x-callback:') || href.startsWith('tg:') || href.startsWith('market:') || href.startsWith('whatsapp:') || href.includes('/playlist/') || href.includes('/player/')) return;
                el.setAttribute('data-target-url', href);
                el.removeAttribute('href');
                el.style.cursor = 'pointer';
                el.setAttribute('role', 'link');
                el.setAttribute('tabindex', '0');
            }}

            function maskAll(root) {{
                const scope = root || document;
                if (!scope.querySelectorAll) return;
                scope.querySelectorAll('a[href]').forEach(maskLink);
            }}

            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', function () {{ maskAll(); }});
            }} else {{
                maskAll();
            }}

            // Pre-emptively mask links before hover triggers the status bar
            document.addEventListener('mouseover', function (e) {{
                const a = e.target && e.target.closest && e.target.closest('a[href]');
                if (a) maskLink(a);
            }}, true);

            window.openSafeUrl = function (url, newTab) {{
                if (!url) return;
                if (newTab) {{
                    const a = document.createElement('a');
                    a.href = url;
                    a.target = '_blank';
                    a.rel = 'noopener noreferrer';
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => {{
                        try {{ document.body.removeChild(a); }} catch (e) {{}}
                    }}, 250);
                }} else {{
                    window.location.href = url;
                }}
            }};

            if (window.MutationObserver) {{
                new MutationObserver(function (mutations) {{
                    for (let i = 0; i < mutations.length; i++) {{
                        const added = mutations[i].addedNodes;
                        for (let j = 0; j < added.length; j++) {{
                            if (added[j].nodeType === 1) {{
                                if (added[j].tagName === 'A' && added[j].hasAttribute('href')) {{
                                    maskLink(added[j]);
                                }} else if (added[j].querySelectorAll) {{
                                    maskAll(added[j]);
                                }}
                            }}
                        }}
                    }}
                }}).observe(document.documentElement, {{ childList: true, subtree: true }});
            }}

            document.addEventListener('click', function (e) {{
                const el = e.target && e.target.closest && e.target.closest('[data-target-url]');
                if (!el) return;
                if (e.defaultPrevented) return;

                const url = el.getAttribute('data-target-url');
                if (!url) return;

                const target = el.getAttribute('target');
                const isNewTab = (target === '_blank' || e.ctrlKey || e.metaKey || e.button === 1);
                window.openSafeUrl(url, isNewTab);
            }}, false);

            document.addEventListener('keydown', function (e) {{
                if (e.key === 'Enter') {{
                    const el = document.activeElement && document.activeElement.closest && document.activeElement.closest('[data-target-url]');
                    if (el) el.click();
                }}
            }});
        }})();
    </script>
</body>
</html>
"""

VERIFY_ERROR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Link Expired — AkMovieVerse</title>
    <style>
        body {{
            background: #0a0e17;
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
            text-align: center;
        }}
        .card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 20px;
            padding: 35px 25px;
            max-width: 420px;
        }}
        h1 {{ font-size: 22px; margin-bottom: 12px; color: #f87171; }}
        p {{ color: #94a3b8; font-size: 14px; line-height: 1.6; margin-bottom: 20px; }}
        a {{ display: inline-block; background: #238636; color: #fff; text-decoration: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; }}
    </style>
</head>
<body oncontextmenu="return false;" onselectstart="return false;" ondragstart="return false;">
    <div class="card">
        <h1>❌ Link Expired or Invalid</h1>
        <p>This verification link has expired or has already been used. Please return to the bot and request your file again to generate a fresh link.</p>
        <a href="https://t.me/{bot_username}">Return to Bot ↗️</a>
    </div>
    <script>
        (function () {{
            function killEvent(e) {{
                if (e) {{
                    if (e.preventDefault) e.preventDefault();
                    if (e.stopPropagation) e.stopPropagation();
                    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                }}
                return false;
            }}
            window.addEventListener("contextmenu", killEvent, true);
            document.addEventListener("contextmenu", killEvent, true);
            window.addEventListener("selectstart", killEvent, true);
            document.addEventListener("selectstart", killEvent, true);
            window.addEventListener("dragstart", killEvent, true);
            document.addEventListener("dragstart", killEvent, true);
            window.oncontextmenu = killEvent;
            document.oncontextmenu = killEvent;
            window.addEventListener("keydown", function (e) {{
                if (
                    e.keyCode === 123 ||
                    (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74 || e.keyCode === 75 || e.keyCode === 69)) ||
                    (e.metaKey && e.altKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74)) ||
                    ((e.ctrlKey || e.metaKey) && (e.keyCode === 85 || e.keyCode === 83 || e.keyCode === 80))
                ) {{
                    return killEvent(e);
                }}
            }}, true);
        }})();
    </script>
</body>
</html>
"""

WEB_PLAYER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>{clean_title} — AkMovieVerse Stream</title>
    <!-- Artplayer CDN -->
    <script src="https://cdn.jsdelivr.net/npm/artplayer/dist/artplayer.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            -webkit-tap-highlight-color: transparent;
            -webkit-touch-callout: none;
            -webkit-user-select: none;
            user-select: none;
        }}
        input, textarea {{
            -webkit-user-select: auto;
            user-select: auto;
        }}
        body {{
            background: radial-gradient(circle at 50% 0%, #172033 0%, #090d16 60%, #05070c 100%);
            color: #f1f5f9;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 12px 14px 28px 14px;
        }}
        .container {{
            max-width: 900px;
            width: 100%;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 4px 14px 4px;
        }}
        .brand {{
            font-size: 19px;
            font-weight: 800;
            color: #38bdf8;
            text-decoration: none;
            display: flex;
            align-items: center;
            gap: 8px;
            letter-spacing: -0.3px;
        }}
        .brand-pill {{
            background: rgba(56, 189, 248, 0.15);
            border: 1px solid rgba(56, 189, 248, 0.3);
            color: #38bdf8;
            font-size: 11px;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 999px;
            text-transform: uppercase;
        }}
        .player-wrapper {{
            position: relative;
            width: 100%;
            height: 54vw;
            min-height: 220px;
            max-height: 520px;
            background: #000000;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.8), 0 0 35px rgba(56, 189, 248, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        #artplayer {{
            width: 100%;
            height: 100%;
        }}
        .meta-card {{
            background: rgba(22, 27, 34, 0.85);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 16px 18px;
            margin-top: 14px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.4);
        }}
        .title {{
            font-size: 18px;
            font-weight: 700;
            color: #ffffff;
            line-height: 1.35;
            margin-bottom: 6px;
            word-break: break-word;
        }}
        .raw-filename {{
            font-size: 11px;
            color: #64748b;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            word-break: break-all;
            margin-bottom: 12px;
            line-height: 1.4;
        }}
        .badges {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-bottom: 12px;
        }}
        .badge {{
            background: rgba(255, 255, 255, 0.06);
            color: #cbd5e1;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            border: 1px solid rgba(255, 255, 255, 0.1);
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }}
        .badge-cyan {{
            background: rgba(56, 189, 248, 0.14);
            color: #38bdf8;
            border-color: rgba(56, 189, 248, 0.35);
        }}
        .badge-green {{
            background: rgba(34, 197, 94, 0.14);
            color: #4ade80;
            border-color: rgba(34, 197, 94, 0.35);
        }}
        .badge-purple {{
            background: rgba(168, 85, 247, 0.14);
            color: #c084fc;
            border-color: rgba(168, 85, 247, 0.35);
        }}
        .tip-banner {{
            background: linear-gradient(135deg, rgba(234, 88, 12, 0.12), rgba(2, 132, 199, 0.12));
            border: 1px solid rgba(234, 88, 12, 0.3);
            border-radius: 12px;
            padding: 10px 14px;
            margin-top: 10px;
            font-size: 12.5px;
            line-height: 1.5;
            color: #fed7aa;
            display: flex;
            align-items: flex-start;
            gap: 10px;
        }}
        .tip-icon {{
            font-size: 18px;
            line-height: 1;
            flex-shrink: 0;
            margin-top: 2px;
        }}
        .actions-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-top: 14px;
        }}
        .btn {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            padding: 12px 10px;
            border-radius: 12px;
            font-size: 13px;
            font-weight: 600;
            text-decoration: none;
            color: #ffffff;
            transition: all 0.2s ease;
            text-align: center;
            border: none;
            cursor: pointer;
            outline: none;
        }}
        .btn-chooser {{
            grid-column: span 2;
            background: linear-gradient(135deg, #10b981, #059669);
            box-shadow: 0 4px 14px rgba(16, 185, 129, 0.35);
            font-size: 13.5px;
            padding: 13px 10px;
        }}
        .btn-mx {{
            background: linear-gradient(135deg, #0284c7, #2563eb);
            box-shadow: 0 4px 14px rgba(2, 132, 199, 0.3);
        }}
        .btn-vlc {{
            background: linear-gradient(135deg, #ea580c, #c2410c);
            box-shadow: 0 4px 14px rgba(234, 88, 12, 0.3);
        }}
        .btn-dl {{
            background: linear-gradient(135deg, #6366f1, #4f46e5);
            box-shadow: 0 4px 14px rgba(99, 102, 241, 0.3);
        }}
        .btn-copy {{
            background: linear-gradient(135deg, #334155, #1e293b);
            border: 1px solid rgba(255, 255, 255, 0.15);
        }}
        .btn-share {{
            background: linear-gradient(135deg, #ec4899, #be185d);
            box-shadow: 0 4px 14px rgba(236, 72, 153, 0.3);
        }}
        .btn-m3u {{
            background: linear-gradient(135deg, #059669, #047857);
            box-shadow: 0 4px 14px rgba(5, 150, 105, 0.3);
        }}
        .btn:active {{
            transform: scale(0.97);
        }}
        .btn-channel {{
            background: linear-gradient(135deg, rgba(56, 189, 248, 0.16), rgba(37, 99, 235, 0.28));
            border: 1px solid rgba(56, 189, 248, 0.45);
            color: #38bdf8;
            font-size: 12px;
            font-weight: 700;
            padding: 7px 14px;
            border-radius: 999px;
            text-decoration: none;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            white-space: nowrap;
            box-shadow: 0 2px 8px rgba(56, 189, 248, 0.2);
        }}
        .btn-channel:hover {{
            background: rgba(56, 189, 248, 0.35);
            color: #ffffff;
            border-color: #38bdf8;
        }}
        .sponsor-banner-bar {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.14), rgba(239, 68, 68, 0.14));
            border: 1px solid rgba(245, 158, 11, 0.4);
            padding: 11px 16px;
            border-radius: 12px;
            text-decoration: none;
            margin-bottom: 14px;
            transition: all 0.2s ease;
        }}
        .sponsor-banner-bar:hover {{
            border-color: rgba(245, 158, 11, 0.8);
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.25), rgba(239, 68, 68, 0.25));
            transform: translateY(-1px);
        }}
        .sponsor-tag {{
            font-size: 11px;
            font-weight: 900;
            background: #f59e0b;
            color: #000;
            padding: 3px 8px;
            border-radius: 5px;
            letter-spacing: 0.5px;
            margin-right: 10px;
            flex-shrink: 0;
        }}
        .sponsor-text {{
            color: #fef3c7;
            font-size: 14.5px;
            font-weight: 700;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            flex: 1;
        }}
        .sponsor-arrow {{
            color: #f59e0b;
            font-size: 16px;
            font-weight: 800;
            margin-left: 10px;
        }}
        .btn-bot {{
            grid-column: span 2;
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            box-shadow: 0 4px 14px rgba(37, 99, 235, 0.3);
            margin-top: 4px;
            font-size: 13.5px;
            padding: 12px 10px;
        }}
        /* Share Sheet Modal */
        .share-sheet-overlay {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.75);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            z-index: 99999;
            display: none;
            align-items: flex-end;
            justify-content: center;
        }}
        .share-sheet-overlay.active {{
            display: flex;
        }}
        .share-sheet-card {{
            background: #161b22;
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 22px 22px 0 0;
            width: 100%;
            max-width: 520px;
            padding: 14px 18px 26px 18px;
            box-shadow: 0 -10px 40px rgba(0, 0, 0, 0.85);
            animation: sheetSlideUp 0.22s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        @keyframes sheetSlideUp {{
            from {{ transform: translateY(100%); }}
            to {{ transform: translateY(0); }}
        }}
        .share-sheet-handle {{
            width: 36px;
            height: 4px;
            background: rgba(255, 255, 255, 0.25);
            border-radius: 999px;
            margin: 0 auto 12px auto;
        }}
        .share-sheet-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 4px;
        }}
        .share-sheet-title {{
            font-size: 17px;
            font-weight: 700;
            color: #ffffff;
        }}
        .share-sheet-close {{
            background: rgba(255, 255, 255, 0.08);
            border: none;
            color: #94a3b8;
            font-size: 20px;
            width: 28px;
            height: 28px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            line-height: 1;
        }}
        .share-sheet-subtitle {{
            font-size: 12px;
            color: #64748b;
            margin-bottom: 16px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .share-sheet-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-bottom: 14px;
        }}
        .share-item {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 8px;
            padding: 14px 8px;
            border-radius: 14px;
            text-decoration: none;
            color: #ffffff;
            font-size: 12.5px;
            font-weight: 600;
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: all 0.15s ease;
            cursor: pointer;
            outline: none;
        }}
        .share-item:active {{
            transform: scale(0.95);
        }}
        .share-item-icon {{
            font-size: 24px;
            line-height: 1;
        }}
        .share-item-wa {{
            background: linear-gradient(135deg, rgba(37, 211, 102, 0.16), rgba(18, 140, 126, 0.28));
            border-color: rgba(37, 211, 102, 0.35);
            color: #4ade80;
        }}
        .share-item-tg {{
            background: linear-gradient(135deg, rgba(56, 189, 248, 0.16), rgba(37, 99, 235, 0.28));
            border-color: rgba(56, 189, 248, 0.35);
            color: #38bdf8;
        }}
        .share-item-cp {{
            background: linear-gradient(135deg, rgba(148, 163, 184, 0.12), rgba(51, 65, 85, 0.25));
            border-color: rgba(148, 163, 184, 0.25);
            color: #cbd5e1;
        }}
        .share-sheet-cancel {{
            width: 100%;
            padding: 11px;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            color: #94a3b8;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
        }}
        /* In-Page Search Bar */
        .search-section {{
            margin-top: 14px;
        }}
        .search-form {{
            display: flex;
            align-items: center;
            background: rgba(22, 27, 34, 0.85);
            border: 1px solid rgba(56, 189, 248, 0.3);
            border-radius: 14px;
            padding: 4px 6px 4px 14px;
            backdrop-filter: blur(12px);
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
            transition: all 0.2s ease;
        }}
        .search-form:focus-within {{
            border-color: #38bdf8;
            box-shadow: 0 0 16px rgba(56, 189, 248, 0.25);
        }}
        .search-icon {{
            font-size: 15px;
            margin-right: 6px;
            color: #64748b;
        }}
        .search-input {{
            flex: 1;
            background: transparent;
            border: none;
            color: #ffffff;
            font-size: 13.5px;
            outline: none;
            padding: 8px 4px;
        }}
        .search-input::placeholder {{
            color: #64748b;
        }}
        .search-btn {{
            background: linear-gradient(135deg, #0284c7, #2563eb);
            color: #ffffff;
            border: none;
            padding: 9px 16px;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .search-btn:active {{
            transform: scale(0.96);
        }}
        /* Explore Catalog Banner */
        .catalog-banner {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-top: 14px;
            padding: 13px 16px;
            background: linear-gradient(135deg, rgba(56, 189, 248, 0.12), rgba(99, 102, 241, 0.18));
            border: 1px solid rgba(56, 189, 248, 0.35);
            border-radius: 15px;
            text-decoration: none;
            color: #ffffff;
            transition: all 0.2s ease;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
        }}
        .catalog-banner:hover {{
            border-color: #38bdf8;
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(56, 189, 248, 0.2);
        }}
        .banner-title {{
            font-size: 14px;
            font-weight: 700;
            color: #38bdf8;
            margin-bottom: 2px;
        }}
        .banner-desc {{
            font-size: 11.5px;
            color: #94a3b8;
        }}
        .banner-arrow {{
            font-size: 18px;
            color: #38bdf8;
            transition: transform 0.2s ease;
        }}
        .catalog-banner:hover .banner-arrow {{
            transform: translateX(4px);
        }}
        /* Related Movies Section */
        .related-section {{
            margin-top: 22px;
        }}
        .section-heading {{
            font-size: 16px;
            font-weight: 700;
            color: #f1f5f9;
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 12px;
        }}
        .related-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
        }}
        @media (min-width: 640px) {{
            .related-grid {{
                grid-template-columns: repeat(3, 1fr);
            }}
        }}
        .related-card {{
            background: rgba(22, 27, 34, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35);
            transition: transform 0.2s, border-color 0.2s;
        }}
        .related-card:hover {{
            transform: translateY(-3px);
            border-color: rgba(56, 189, 248, 0.4);
        }}
        .poster-wrap {{
            position: relative;
            width: 100%;
            aspect-ratio: 2 / 3;
            background: #0d1117;
            overflow: hidden;
            display: block;
            text-decoration: none;
            cursor: pointer;
        }}
        .poster-img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
            transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        .poster-play-overlay {{
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.4);
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0;
            transition: opacity 0.22s ease;
            z-index: 3;
        }}
        .poster-play-icon {{
            width: 44px;
            height: 44px;
            border-radius: 50%;
            background: rgba(56, 189, 248, 0.95);
            box-shadow: 0 0 20px rgba(56, 189, 248, 0.65);
            display: flex;
            align-items: center;
            justify-content: center;
            color: #030712;
            font-size: 18px;
            padding-left: 3px;
            transform: scale(0.75);
            transition: transform 0.22s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        .related-card:hover .poster-play-overlay {{
            opacity: 1;
        }}
        .related-card:hover .poster-play-icon {{
            transform: scale(1);
        }}
        .related-card:hover .poster-img {{
            transform: scale(1.06);
        }}
        .poster-fallback {{
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: radial-gradient(circle at center, #1e293b, #0f172a);
            color: #64748b;
            font-size: 32px;
        }}
        .card-badge-overlay {{
            position: absolute;
            top: 6px;
            left: 6px;
            display: flex;
            flex-direction: column;
            gap: 4px;
            z-index: 2;
        }}
        .mini-badge {{
            font-size: 10px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 6px;
            text-transform: uppercase;
            letter-spacing: 0.3px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.4);
        }}
        .mini-badge-qual {{
            background: rgba(168, 85, 247, 0.85);
            color: #ffffff;
        }}
        .mini-badge-comb {{
            background: rgba(234, 88, 12, 0.85);
            color: #ffffff;
        }}
        .mini-badge-size {{
            position: absolute;
            bottom: 6px;
            right: 6px;
            background: rgba(0, 0, 0, 0.78);
            backdrop-filter: blur(4px);
            color: #38bdf8;
            font-size: 10px;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 6px;
            border: 1px solid rgba(255, 255, 255, 0.12);
            z-index: 2;
        }}
        .card-info {{
            padding: 10px;
            display: flex;
            flex-direction: column;
            flex: 1;
            justify-content: space-between;
        }}
        .card-title {{
            font-size: 12px;
            font-weight: 600;
            color: #f8fafc;
            line-height: 1.35;
            margin-bottom: 8px;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            text-decoration: none;
            transition: color 0.15s ease;
            cursor: pointer;
        }}
        .card-title:hover {{
            color: #38bdf8;
        }}
        .card-watch-btn {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 5px;
            width: 100%;
            padding: 8px 6px;
            background: linear-gradient(135deg, #0284c7, #2563eb);
            color: #ffffff;
            text-decoration: none;
            font-size: 12px;
            font-weight: 700;
            border-radius: 8px;
            transition: all 0.2s;
        }}
        .card-watch-btn:active {{
            transform: scale(0.97);
        }}
        /* Netflix-style Up Next Overlay inside player */
        .netflix-up-next {{
            position: absolute;
            bottom: 20px;
            right: 20px;
            z-index: 99;
            max-width: 330px;
            width: calc(100% - 40px);
            animation: netflixFadeUp 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        @keyframes netflixFadeUp {{
            from {{ opacity: 0; transform: translateY(14px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .netflix-up-next-card {{
            background: rgba(15, 23, 42, 0.95);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border: 1px solid rgba(56, 189, 248, 0.35);
            border-radius: 14px;
            padding: 14px 16px;
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.9), 0 0 25px rgba(56, 189, 248, 0.2);
        }}
        .netflix-badge {{
            display: inline-block;
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 0.6px;
            padding: 2.5px 8px;
            border-radius: 4px;
            background: #e50914;
            color: #ffffff;
            margin-bottom: 6px;
            text-transform: uppercase;
        }}
        .netflix-up-next-title {{
            font-size: 13.5px;
            font-weight: 700;
            color: #ffffff;
            line-height: 1.35;
            margin-bottom: 6px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .netflix-countdown-bar {{
            width: 100%;
            height: 4px;
            background: rgba(255, 255, 255, 0.15);
            border-radius: 999px;
            overflow: hidden;
            margin-bottom: 8px;
        }}
        #countdown-progress {{
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, #38bdf8, #2563eb);
            transition: width 1s linear;
        }}
        .netflix-up-next-desc {{
            font-size: 11.5px;
            color: #94a3b8;
            margin-bottom: 12px;
        }}
        .netflix-up-next-actions {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .netflix-btn-play {{
            flex: 1;
            padding: 8px 12px;
            background: #ffffff;
            color: #000000;
            font-size: 12px;
            font-weight: 700;
            border-radius: 8px;
            border: none;
            cursor: pointer;
            transition: all 0.15s ease;
            text-align: center;
            text-decoration: none;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
        }}
        .netflix-btn-play:hover {{
            background: #f1f5f9;
            transform: scale(1.02);
        }}
        .netflix-btn-cancel {{
            padding: 8px 12px;
            background: rgba(255, 255, 255, 0.1);
            color: #cbd5e1;
            font-size: 12px;
            font-weight: 600;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.15);
            cursor: pointer;
            transition: all 0.15s ease;
        }}
        .netflix-btn-cancel:hover {{
            background: rgba(255, 255, 255, 0.2);
            color: #ffffff;
        }}

        /* Netflix-style Episodes Carousel Section */
        .netflix-episodes-section {{
            background: rgba(22, 27, 34, 0.85);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 14px 16px;
            margin-top: 14px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.4);
        }}
        .netflix-episodes-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            gap: 8px;
            flex-wrap: wrap;
        }}
        .episodes-header-left {{
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            min-width: 0;
        }}
        .episodes-icon {{
            font-size: 17px;
        }}
        .episodes-title {{
            font-size: 15px;
            font-weight: 700;
            color: #ffffff;
        }}
        .episodes-count-pill {{
            font-size: 11px;
            font-weight: 700;
            background: rgba(56, 189, 248, 0.15);
            color: #38bdf8;
            border: 1px solid rgba(56, 189, 248, 0.3);
            padding: 2px 8px;
            border-radius: 999px;
        }}
        .episodes-view-all {{
            font-size: 12px;
            font-weight: 600;
            color: #38bdf8;
            text-decoration: none;
            transition: color 0.15s;
        }}
        .episodes-view-all:hover {{
            color: #7dd3fc;
            text-decoration: underline;
        }}
        .netflix-episodes-row {{
            display: flex;
            gap: 12px;
            overflow-x: auto;
            scroll-behavior: smooth;
            padding-bottom: 8px;
            -webkit-overflow-scrolling: touch;
        }}
        .netflix-episodes-row::-webkit-scrollbar {{
            height: 6px;
        }}
        .netflix-episodes-row::-webkit-scrollbar-track {{
            background: rgba(255, 255, 255, 0.05);
            border-radius: 999px;
        }}
        .netflix-episodes-row::-webkit-scrollbar-thumb {{
            background: rgba(56, 189, 248, 0.35);
            border-radius: 999px;
        }}
        .netflix-episodes-row::-webkit-scrollbar-thumb:hover {{
            background: rgba(56, 189, 248, 0.6);
        }}
        .netflix-ep-card {{
            flex: 0 0 135px;
            width: 135px;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            overflow: hidden;
            text-decoration: none;
            transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
            display: flex;
            flex-direction: column;
            cursor: pointer;
            position: relative;
        }}
        .netflix-ep-card:hover {{
            transform: translateY(-4px) scale(1.03);
            border-color: rgba(56, 189, 248, 0.5);
            box-shadow: 0 8px 20px rgba(0,0,0,0.5), 0 0 15px rgba(56, 189, 248, 0.25);
        }}
        .netflix-ep-card.active-ep {{
            border: 1.5px solid #38bdf8;
            background: rgba(56, 189, 248, 0.1);
            box-shadow: 0 0 18px rgba(56, 189, 248, 0.3);
        }}
        .ep-thumb-wrap {{
            position: relative;
            width: 100%;
            aspect-ratio: 16/9;
            background: #0b0f19;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .ep-thumb {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            transition: transform 0.25s ease;
        }}
        .netflix-ep-card:hover .ep-thumb {{
            transform: scale(1.08);
        }}
        .ep-thumb-fallback {{
            font-size: 24px;
            color: #64748b;
        }}
        .ep-thumb-overlay {{
            position: absolute;
            inset: 0;
            background: rgba(0, 0, 0, 0.45);
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0;
            transition: opacity 0.2s ease;
        }}
        .netflix-ep-card:hover .ep-thumb-overlay {{
            opacity: 1;
        }}
        .netflix-ep-card.active-ep .ep-thumb-overlay {{
            opacity: 1;
            background: rgba(3, 7, 18, 0.55);
        }}
        .ep-play-icon {{
            width: 28px;
            height: 28px;
            border-radius: 50%;
            background: #38bdf8;
            color: #030712;
            font-size: 13px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.7);
        }}
        .ep-num-tag {{
            position: absolute;
            top: 4px;
            left: 4px;
            background: rgba(0, 0, 0, 0.75);
            color: #f1f5f9;
            font-size: 9px;
            font-weight: 800;
            padding: 2px 5px;
            border-radius: 4px;
            border: 1px solid rgba(255, 255, 255, 0.15);
        }}
        .ep-playing-tag {{
            position: absolute;
            top: 4px;
            left: 4px;
            background: rgba(16, 185, 129, 0.9);
            color: #ffffff;
            font-size: 9px;
            font-weight: 800;
            padding: 2px 6px;
            border-radius: 4px;
            letter-spacing: 0.3px;
            animation: pulsePlaying 1.5s infinite;
        }}
        @keyframes pulsePlaying {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.7; }}
        }}
        .ep-card-qual {{
            position: absolute;
            bottom: 4px;
            right: 4px;
            background: rgba(0, 0, 0, 0.75);
            color: #cbd5e1;
            font-size: 8.5px;
            font-weight: 700;
            padding: 1px 4px;
            border-radius: 3px;
        }}
        .ep-card-meta {{
            padding: 8px 8px 10px 8px;
            display: flex;
            flex-direction: column;
            gap: 2px;
        }}
        .ep-card-title {{
            font-size: 12px;
            font-weight: 700;
            color: #f8fafc;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .netflix-ep-card.active-ep .ep-card-title {{
            color: #38bdf8;
        }}
        .ep-card-sub {{
            font-size: 10px;
            color: #94a3b8;
        }}
        .btn-next-ep {{
            grid-column: span 2;
            background: linear-gradient(135deg, #e50914, #b91c1c);
            box-shadow: 0 4px 15px rgba(229, 9, 20, 0.4);
            font-size: 13.5px;
            padding: 12px 10px;
            font-weight: 700;
        }}
        .btn-next-ep:hover {{
            background: linear-gradient(135deg, #f87171, #dc2626);
        }}
        /* Movie Parts & Episode Quality Bar */
        .movie-parts-bar, .ep-quality-bar {{
            background: rgba(22, 27, 34, 0.85);
            border: 1px solid rgba(56, 189, 248, 0.25);
            border-radius: 14px;
            padding: 12px 14px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 10px;
            backdrop-filter: blur(14px);
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
        }}
        .movie-parts-left, .ep-qual-left {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .movie-parts-title, .ep-qual-title {{
            font-size: 14px;
            font-weight: 800;
            color: #ffffff;
        }}
        .movie-parts-pills, .ep-qual-pills {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .movie-part-pill, .ep-qual-pill {{
            padding: 6px 12px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 700;
            text-decoration: none;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }}
        .movie-part-pill.active, .ep-qual-pill.active {{
            background: rgba(16, 185, 129, 0.25);
            color: #34d399;
            border: 1.5px solid #10b981;
            box-shadow: 0 0 12px rgba(16, 185, 129, 0.3);
        }}
        .movie-part-pill:not(.active), .ep-qual-pill:not(.active) {{
            background: rgba(255, 255, 255, 0.06);
            color: #94a3b8;
            border: 1px solid rgba(255, 255, 255, 0.12);
        }}
        .movie-part-pill:not(.active):hover, .ep-qual-pill:not(.active):hover {{
            background: rgba(56, 189, 248, 0.25);
            color: #38bdf8;
            border-color: #38bdf8;
        }}
        /* Movie Quality & Prints Switcher */
        .movie-prints-section {{
            background: rgba(22, 27, 34, 0.85);
            border: 1px solid rgba(56, 189, 248, 0.25);
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 20px;
            backdrop-filter: blur(14px);
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.45);
        }}
        .prints-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 12px;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .prints-header-left {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .prints-title {{
            font-size: 15px;
            font-weight: 800;
            color: #ffffff;
        }}
        .prints-count-pill {{
            font-size: 11px;
            font-weight: 700;
            background: rgba(56, 189, 248, 0.15);
            color: #38bdf8;
            border: 1px solid rgba(56, 189, 248, 0.35);
            padding: 3px 9px;
            border-radius: 999px;
        }}
        .prints-active-badge {{
            font-size: 11px;
            font-weight: 700;
            background: rgba(16, 185, 129, 0.2);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.4);
            padding: 3px 9px;
            border-radius: 999px;
        }}
        .prints-filter-pills {{
            display: flex;
            gap: 6px;
            overflow-x: auto;
            padding-bottom: 8px;
            margin-bottom: 12px;
            scrollbar-width: none;
        }}
        .prints-filter-pills::-webkit-scrollbar {{
            display: none;
        }}
        .print-filter-btn {{
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #94a3b8;
            padding: 5px 12px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
            white-space: nowrap;
        }}
        .print-filter-btn:hover, .print-filter-btn.active {{
            background: rgba(56, 189, 248, 0.25);
            border-color: #38bdf8;
            color: #38bdf8;
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.2);
        }}
        .print-filter-btn.audio-btn {{
            border-color: rgba(16, 185, 129, 0.35);
            color: #6ee7b7;
        }}
        .print-filter-btn.audio-btn:hover, .print-filter-btn.audio-btn.active {{
            background: rgba(16, 185, 129, 0.25);
            border-color: #10b981;
            color: #a7f3d0;
            box-shadow: 0 0 10px rgba(16, 185, 129, 0.25);
        }}
        .dual-audio-banner {{
            width: 100%;
            margin-bottom: 16px;
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.12), rgba(6, 78, 59, 0.22));
            border: 1px solid rgba(16, 185, 129, 0.35);
            border-radius: 14px;
            padding: 12px 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        }}
        .dab-left {{
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 0;
        }}
        .dab-icon {{
            font-size: 1.5rem;
            flex-shrink: 0;
        }}
        .dab-text {{
            display: flex;
            flex-direction: column;
            font-size: 0.85rem;
            color: #e2e8f0;
            min-width: 0;
        }}
        .dab-text strong {{
            color: #34d399;
            font-size: 0.95rem;
            font-weight: 700;
        }}
        .dab-text span {{
            color: #94a3b8;
            font-size: 0.8rem;
            line-height: 1.3;
        }}
        .dab-actions {{
            display: flex;
            gap: 8px;
            flex-shrink: 0;
        }}
        .dab-btn {{
            padding: 6px 12px;
            border-radius: 8px;
            font-size: 0.8rem;
            font-weight: 700;
            text-decoration: none;
            color: #ffffff;
            display: inline-flex;
            align-items: center;
            transition: transform 0.15s ease, opacity 0.15s ease;
        }}
        .dab-btn:hover {{
            transform: translateY(-1px);
            opacity: 0.9;
        }}
        .dab-btn.vlc {{
            background: linear-gradient(135deg, #ea580c, #c2410c);
        }}
        .dab-btn.mx {{
            background: linear-gradient(135deg, #0284c7, #0369a1);
        }}
        @media (max-width: 640px) {{
            .dual-audio-banner {{
                flex-direction: column;
                align-items: flex-start;
            }}
            .dab-actions {{
                width: 100%;
                justify-content: flex-end;
            }}
        }}
        .prints-grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 10px;
            max-height: 480px;
            overflow-y: auto;
            padding-right: 4px;
        }}
        @media (min-width: 600px) {{
            .prints-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}
        @media (min-width: 960px) {{
            .prints-grid {{
                grid-template-columns: repeat(3, 1fr);
            }}
        }}
        .print-card {{
            background: rgba(15, 23, 42, 0.65);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            padding: 12px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            gap: 10px;
            transition: all 0.2s ease;
            position: relative;
            overflow: hidden;
        }}
        .print-card:hover {{
            border-color: rgba(56, 189, 248, 0.45);
            background: rgba(15, 23, 42, 0.85);
            transform: translateY(-2px);
            box-shadow: 0 6px 18px rgba(0, 0, 0, 0.4);
        }}
        .print-card.is-active-print {{
            border: 1.5px solid #10b981;
            background: rgba(16, 185, 129, 0.08);
            box-shadow: 0 0 16px rgba(16, 185, 129, 0.25);
        }}
        .print-card-top {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 8px;
        }}
        .print-card-title {{
            font-size: 13px;
            font-weight: 700;
            color: #ffffff;
            line-height: 1.35;
            word-break: break-word;
        }}
        .print-card-badges {{
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            margin-top: 6px;
        }}
        .print-badge {{
            font-size: 10px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
            text-transform: uppercase;
        }}
        .pbadge-res {{
            background: linear-gradient(135deg, #0284c7, #2563eb);
            color: #ffffff;
        }}
        .pbadge-codec {{
            background: rgba(168, 85, 247, 0.25);
            color: #c084fc;
            border: 1px solid rgba(168, 85, 247, 0.35);
        }}
        .pbadge-audio {{
            background: rgba(16, 185, 129, 0.2);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.35);
        }}
        .pbadge-size {{
            background: rgba(0, 0, 0, 0.6);
            color: #fbbf24;
            border: 1px solid rgba(255, 255, 255, 0.12);
            font-size: 11px;
            font-weight: 800;
            padding: 3px 7px;
            border-radius: 6px;
            white-space: nowrap;
            shrink-0;
        }}
        .print-card-actions {{
            display: flex;
            align-items: center;
            gap: 6px;
            margin-top: auto;
            padding-top: 8px;
            border-top: 1px solid rgba(255, 255, 255, 0.06);
        }}
        .print-play-btn {{
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 5px;
            padding: 8px 10px;
            border-radius: 8px;
            background: linear-gradient(135deg, #0284c7, #2563eb);
            color: #ffffff;
            font-size: 12px;
            font-weight: 700;
            text-decoration: none;
            transition: all 0.18s;
        }}
        .print-play-btn:hover {{
            background: linear-gradient(135deg, #38bdf8, #0284c7);
            box-shadow: 0 4px 12px rgba(2, 132, 199, 0.4);
        }}
        .print-play-btn.now-playing {{
            background: rgba(16, 185, 129, 0.25);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.4);
            cursor: default;
        }}
        .print-action-icon {{
            padding: 7px 9px;
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: #cbd5e1;
            font-size: 12px;
            text-decoration: none;
            transition: all 0.18s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }}
        .print-action-icon:hover {{
            background: rgba(255, 255, 255, 0.15);
            color: #ffffff;
        }}
        @media (min-width: 640px) {{
            .title {{ font-size: 21px; }}
            .actions-grid {{
                grid-template-columns: repeat(3, 1fr);
            }}
            .btn-chooser, .btn-bot, .btn-next-ep {{
                grid-column: span 3;
            }}
        }}
        /* Mobile Responsive Player Controls Guard */
        @media (max-width: 640px) {{
            body {{
                padding: 8px 10px 24px 10px;
            }}
            .header {{
                padding: 4px 2px 10px 2px;
                gap: 8px;
            }}
            .brand {{
                font-size: 16px;
                gap: 5px;
                white-space: nowrap;
                flex-shrink: 0;
            }}
            .btn-channel {{
                font-size: 11px;
                padding: 5px 10px;
                white-space: nowrap;
                flex-shrink: 0;
            }}
            .player-wrapper {{
                height: 56.25vw;
                min-height: 200px;
                border-radius: 12px;
            }}
            /* Artplayer Bottom Bar & Controls Flex Overrides */
            .art-video-player .art-bottom {{
                padding: 0 4px 2px 4px !important;
            }}
            .art-video-player .art-controls {{
                padding: 0 2px !important;
                gap: 3px !important;
            }}
            .art-video-player .art-controls-left {{
                gap: 4px !important;
                min-width: 0 !important;
                flex-shrink: 1 !important;
            }}
            .art-video-player .art-controls-right {{
                gap: 2px !important;
                flex-shrink: 0 !important;
                display: flex !important;
                align-items: center !important;
            }}
            /* Hide non-essential buttons on mobile portrait to prevent controls overflow */
            .art-video-player .art-control-screenshot,
            .art-video-player .art-control-pip,
            .art-video-player .art-control-fullscreenWeb,
            .art-video-player .art-control-aspectRatio,
            .art-video-player .art-control-flip,
            .art-video-player .art-control-airplay {{
                display: none !important;
            }}
            /* Mobile Volume: hide width-eating slider so touch doesn't misfire */
            .art-video-player .art-control-volume .art-volume-slider,
            .art-video-player .art-control-volume-slider {{
                display: none !important;
            }}
            .art-video-player .art-control-volume {{
                min-width: 26px !important;
                padding: 0 2px !important;
            }}
            /* Compact Time Display */
            .art-video-player .art-control-time {{
                font-size: 11px !important;
                padding: 0 3px !important;
                margin: 0 !important;
                white-space: nowrap !important;
            }}
            /* Quality pill in bottom bar */
            .art-video-player .art-control-quality {{
                font-size: 11px !important;
                padding: 0 4px !important;
                max-width: 80px !important;
                overflow: hidden !important;
                text-overflow: ellipsis !important;
                white-space: nowrap !important;
            }}
            /* Settings Gear */
            .art-video-player .art-control-setting {{
                min-width: 28px !important;
                padding: 0 2px !important;
                display: flex !important;
                align-items: center !important;
            }}
            /* Fullscreen button: ALWAYS visible, prioritized */
            .art-video-player .art-control-fullscreen {{
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                min-width: 32px !important;
                min-height: 32px !important;
                padding: 0 4px !important;
                margin-left: 2px !important;
                z-index: 20 !important;
            }}
        }}
    </style>
</head>
<body oncontextmenu="return false;" onselectstart="return false;" ondragstart="return false;">
    <div class="container">
        <div class="header">
            <a href="{browse_url}" class="brand" title="Browse Full Catalog">
                <span>⚡</span> AkMovieVerse
            </a>
            <a href="{channel_url}" target="_blank" class="btn-channel">📢 Join Channel ↗️</a>
        </div>

        {sponsor_banner_html}

        <div class="player-wrapper">
            <div id="artplayer"></div>
            <!-- Netflix-Style Up Next Autoplay Overlay -->
            <div id="netflix-up-next" class="netflix-up-next" style="display: none;">
                <div class="netflix-up-next-card">
                    <div class="netflix-badge">UP NEXT</div>
                    <div class="netflix-up-next-title" id="up-next-title">{next_ep_title}</div>
                    <div class="netflix-countdown-bar"><div id="countdown-progress"></div></div>
                    <div class="netflix-up-next-desc">Playing automatically in <span id="netflix-countdown-sec">5</span>s</div>
                    <div class="netflix-up-next-actions">
                        <button onclick="playNextNow()" class="netflix-btn-play">▶ Play Now</button>
                        <button onclick="cancelUpNext()" class="netflix-btn-cancel">Cancel</button>
                    </div>
                </div>
            </div>
        </div>

        {dual_audio_banner_html}
        {movie_parts_html}
        {quality_selector_html}
        {episodes_carousel_html}

        <div class="meta-card">
            <div class="title">{clean_title}</div>
            <div class="raw-filename">{raw_filename}</div>
            
            <div class="badges">
                {badges_html}
            </div>

            <div class="tip-banner">
                <span class="tip-icon">💡</span>
                <div>
                    <b>Multi-Audio / Any Player:</b> Agar phone me koi bhi video player ho (PlayIt, MX, VLC, KMPlayer, Phone Player) ya audio switch karni ho, toh neeche <b>Open in Any Video Player</b> par tap karein!
                </div>
            </div>

            <div class="actions-grid">
                {next_ep_btn_html}
                {series_btn_html}
                <a href="{chooser_intent}" onclick="handleAnyPlayer(event)" class="btn btn-chooser">📱 Open in Any Video Player (All Installed Apps)</a>
                <a href="{mx_intent}" onclick="handleMxPlayer(event)" class="btn btn-mx">🍿 MX Player</a>
                <a href="{vlc_intent}" onclick="handleVlcPlayer(event)" class="btn btn-vlc">🧡 VLC Player</a>
                {download_button_html}
                <button onclick="copyStreamUrl()" class="btn btn-copy" id="copy-btn">📋 Copy Link</button>
                <button onclick="shareMovie()" class="btn btn-share">📤 Share Movie</button>
                <a href="{m3u_url}" class="btn btn-m3u">📺 M3U Playlist</a>
                <a href="https://t.me/{bot_username}" target="_blank" class="btn btn-bot">🔍 Search More Movies in @{bot_username} ↗️</a>
            </div>
        </div>
    </div>

    <!-- Share Bottom Sheet Modal -->
    <div id="shareSheet" class="share-sheet-overlay" onclick="closeShareSheet(event)">
        <div class="share-sheet-card" onclick="event.stopPropagation()">
            <div class="share-sheet-handle"></div>
            <div class="share-sheet-header">
                <div class="share-sheet-title">📤 Share Movie</div>
                <button class="share-sheet-close" onclick="closeShareSheet()">&times;</button>
            </div>
            <div class="share-sheet-subtitle">{clean_title}</div>
            
            <div class="share-sheet-grid">
                <a href="#" onclick="doShareWhatsApp(event)" class="share-item share-item-wa">
                    <span class="share-item-icon">💬</span>
                    <span class="share-item-text">WhatsApp</span>
                </a>
                <a href="#" onclick="doShareTelegram(event)" class="share-item share-item-tg">
                    <span class="share-item-icon">✈️</span>
                    <span class="share-item-text">Telegram</span>
                </a>
                <button onclick="doShareCopy()" class="share-item share-item-cp">
                    <span class="share-item-icon">📋</span>
                    <span class="share-item-text" id="sheetCopyText">Copy Link</span>
                </button>
            </div>
            
            <button class="share-sheet-cancel" onclick="closeShareSheet()">Close</button>
        </div>
    </div>

    <!-- VIP Download Modal -->
    <div id="vipDownloadModal" class="share-sheet-overlay" onclick="closeVipDownloadModal(event)">
        <div class="share-sheet-card" onclick="event.stopPropagation()" style="border: 1px solid rgba(56, 189, 248, 0.35);">
            <div class="share-sheet-handle"></div>
            <div class="share-sheet-header">
                <div class="share-sheet-title" style="color: #38bdf8; display: flex; align-items: center; gap: 8px;">
                    <span>👑</span> <span>VIP High-Speed Download</span>
                </div>
                <button class="share-sheet-close" onclick="closeVipDownloadModal()">&times;</button>
            </div>
            <div class="share-sheet-subtitle" style="font-weight: 600; color: #f1f5f9;">{clean_title}</div>
            <div style="font-size: 12px; color: #94a3b8; margin-top: -10px; margin-bottom: 12px;">📦 Size: <b style="color: #e2e8f0;">{file_size_str}</b> • ⚡ Direct CDN Speed</div>

            <!-- 6s Countdown Box -->
            <div id="vipDlCountdownBox" style="margin: 12px 0 14px 0; background: rgba(15, 23, 42, 0.75); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 12px; padding: 12px 14px; text-align: center;">
                <div id="vipDlStatusText" style="font-size: 13px; font-weight: 600; color: #38bdf8;">
                    ⏳ Starting secure VIP download in <span id="vipDlSeconds" style="font-size: 17px; font-weight: 800; color: #facc15;">6</span>s...
                </div>
                <div style="width: 100%; height: 6px; background: rgba(255,255,255,0.1); border-radius: 999px; margin-top: 10px; overflow: hidden;">
                    <div id="vipDlProgressBar" style="width: 100%; height: 100%; background: linear-gradient(90deg, #38bdf8, #22c55e); transition: width 6s linear;"></div>
                </div>
            </div>

            <!-- Guidelines / Tips as requested by user -->
            <div style="background: rgba(30, 41, 59, 0.6); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 10px 14px; margin-bottom: 14px; text-align: left; font-size: 12px; line-height: 1.6; color: #cbd5e1;">
                <div style="font-weight: 700; color: #facc15; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
                    <span>💡</span> <span>Important Download Guidelines:</span>
                </div>
                <div>• ⚡ <b>Fast Internet:</b> Fast aur stable connection use karein.</div>
                <div>• ⏸️ <b>Avoid Pausing:</b> Download ko lambe time tak pause na karein.</div>
                <div>• 🔄 <b>Link Expire:</b> Agar download cancel ya expire ho jaye, toh Telegram bot se naya link le lein.</div>
            </div>

            <div style="display: flex; gap: 10px;">
                <button id="vipDlInstantBtn" onclick="triggerImmediateDownload()" class="btn" style="flex: 1; background: linear-gradient(135deg, #0284c7, #2563eb); color: #fff; font-weight: 700; border: none; padding: 12px; border-radius: 10px; cursor: pointer; text-align: center;">
                    🚀 Start Download Now
                </button>
                <button onclick="closeVipDownloadModal()" class="share-sheet-cancel" style="margin: 0; padding: 12px 18px; border-radius: 10px;">
                    Close
                </button>
            </div>
        </div>
    </div>

    <script>
        var vipDlTimer = null;
        var vipDlTargetUrl = "{download_url}";

        function openVipDownloadModal() {{
            var modal = document.getElementById("vipDownloadModal");
            if (!modal) return;
            modal.classList.add("active");

            var secEl = document.getElementById("vipDlSeconds");
            var barEl = document.getElementById("vipDlProgressBar");
            var statusEl = document.getElementById("vipDlStatusText");
            var timeLeft = 6;

            if (secEl) secEl.innerText = timeLeft;
            if (barEl) {{
                barEl.style.transition = "none";
                barEl.style.width = "100%";
                setTimeout(function() {{
                    barEl.style.transition = "width 6s linear";
                    barEl.style.width = "0%";
                }}, 50);
            }}

            if (vipDlTimer) clearInterval(vipDlTimer);
            vipDlTimer = setInterval(function() {{
                timeLeft--;
                if (secEl) secEl.innerText = timeLeft;
                if (timeLeft <= 0) {{
                    clearInterval(vipDlTimer);
                    vipDlTimer = null;
                    if (statusEl) statusEl.innerHTML = "✅ <b>Download started! Check browser downloads.</b>";
                    triggerImmediateDownload();
                }}
            }}, 1000);
        }}

        function closeVipDownloadModal(e) {{
            if (e && e.target && e.target !== e.currentTarget && !e.target.classList.contains("share-sheet-close") && !e.target.classList.contains("share-sheet-cancel")) {{
                return;
            }}
            var modal = document.getElementById("vipDownloadModal");
            if (modal) modal.classList.remove("active");
            if (vipDlTimer) {{
                clearInterval(vipDlTimer);
                vipDlTimer = null;
            }}
        }}

        function triggerImmediateDownload() {{
            if (vipDlTimer) {{
                clearInterval(vipDlTimer);
                vipDlTimer = null;
            }}
            var statusEl = document.getElementById("vipDlStatusText");
            if (statusEl) statusEl.innerHTML = "🚀 <b>Download starting...</b>";

            var a = document.createElement("a");
            a.href = vipDlTargetUrl;
            a.setAttribute("download", "");
            a.style.display = "none";
            document.body.appendChild(a);
            a.click();
            setTimeout(function() {{
                try {{ document.body.removeChild(a); }} catch (err) {{}}
                closeVipDownloadModal();
            }}, 1500);
        }}

        function handleFreeDownload(e) {{
            return true;
        }}
        function getMovieTitle() {{
            var el = document.querySelector(".title");
            return (el ? el.innerText : document.title).trim();
        }}

        function handleAnyPlayer(e) {{
            const isAndroid = /Android/i.test(navigator.userAgent || '');
            if (!isAndroid) {{
                if (e) e.preventDefault();
                window.location.href = "{stream_url}";
            }}
        }}

        function handleMxPlayer(e) {{
            const isAndroid = /Android/i.test(navigator.userAgent || '');
            if (!isAndroid) {{
                if (e) e.preventDefault();
                window.location.href = "{m3u_url}";
            }}
        }}

        function handleVlcPlayer(e) {{
            const isAndroid = /Android/i.test(navigator.userAgent || '');
            if (!isAndroid) {{
                if (e) e.preventDefault();
                window.location.href = "{m3u_url}";
            }}
        }}

        function openShareSheet() {{
            const sheet = document.getElementById("shareSheet");
            if (sheet) {{
                sheet.classList.add("active");
            }}
        }}

        function closeShareSheet(e) {{
            if (e && e.target && e.target !== e.currentTarget && !e.target.classList.contains("share-sheet-close") && !e.target.classList.contains("share-sheet-cancel")) {{
                return;
            }}
            const sheet = document.getElementById("shareSheet");
            if (sheet) {{
                sheet.classList.remove("active");
            }}
        }}

        function getShareText() {{
            var title = getMovieTitle();
            var url = window.location.href;
            return "🎬 Watch *" + title + "* in HD Online Stream: " + String.fromCharCode(10) + url;
        }}

        function doShareWhatsApp(e) {{
            if (e) e.preventDefault();
            const text = getShareText();
            const waUrl = "https://api.whatsapp.com/send?text=" + encodeURIComponent(text);
            window.open(waUrl, "_blank", "noopener,noreferrer");
        }}

        function doShareTelegram(e) {{
            if (e) e.preventDefault();
            const title = getMovieTitle();
            const url = window.location.href;
            const text = "🎬 Watch " + title + " in HD Online Stream";
            const tgWebUrl = "https://t.me/share/url?url=" + encodeURIComponent(url) + "&text=" + encodeURIComponent(text);
            window.open(tgWebUrl, "_blank", "noopener,noreferrer");
        }}

        function fallbackCopy(text, cb) {{
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            try {{ document.execCommand("copy"); }} catch (err) {{}}
            document.body.removeChild(ta);
            if (cb) cb();
        }}

        function doShareCopy() {{
            const text = getShareText();
            const copyLabel = document.getElementById("sheetCopyText");
            function onCopied() {{
                if (copyLabel) copyLabel.innerText = "✅ Copied!";
                setTimeout(() => {{
                    if (copyLabel) copyLabel.innerText = "Copy Link";
                    closeShareSheet();
                }}, 1200);
            }}
            if (navigator.clipboard && window.isSecureContext) {{
                navigator.clipboard.writeText(text).then(onCopied).catch(() => {{ fallbackCopy(text, onCopied); }});
            }} else {{
                fallbackCopy(text, onCopied);
            }}
        }}

        function shareMovie() {{
            const title = getMovieTitle();
            const url = window.location.href;
            const text = getShareText();
            if (navigator.share && window.isSecureContext) {{
                navigator.share({{
                    title: title,
                    text: text,
                    url: url
                }}).catch(() => {{
                    openShareSheet();
                }});
            }} else {{
                openShareSheet();
            }}
        }}

        function copyStreamUrl() {{
            const url = "{stream_url}";
            const btn = document.getElementById('copy-btn');
            function onCopied() {{
                btn.innerText = '✅ Copied!';
                setTimeout(() => {{ btn.innerText = '📋 Copy Link'; }}, 2000);
            }}
            if (navigator.clipboard && window.isSecureContext) {{
                navigator.clipboard.writeText(url).then(onCopied).catch(() => {{ fallbackCopy(url, onCopied); }});
            }} else {{
                fallbackCopy(url, onCopied);
            }}
        }}

        function filterPrints(qual, btn) {{
            const buttons = document.querySelectorAll('.print-filter-btn');
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const cards = document.querySelectorAll('.print-card');
            const target = (qual || '').toLowerCase();
            cards.forEach(c => {{
                const q = (c.getAttribute('data-quality') || '').toLowerCase();
                const a = (c.getAttribute('data-audio') || '').toLowerCase();
                if (target === 'all' || q === target || a === target || a.includes(target)) {{
                    c.style.display = 'flex';
                }} else {{
                    c.style.display = 'none';
                }}
            }});
        }}

        document.addEventListener("DOMContentLoaded", function () {{
            const movieTitle = getMovieTitle();
            const art = new Artplayer({{
                container: '#artplayer',
                url: '{stream_url}',
                title: movieTitle,
                quality: {artplayer_quality_json_str},
                contextmenu: [],
                theme: '#38bdf8',
                volume: 0.9,
                isLive: false,
                muted: false,
                autoplay: false,
                pip: true,
                autoSize: false,
                autoMini: false,
                screenshot: true,
                setting: true,
                loop: false,
                flip: true,
                playbackRate: true,
                aspectRatio: true,
                fullscreen: true,
                fullscreenWeb: true,
                miniProgressBar: true,
                mutex: true,
                backdrop: true,
                playsInline: true,
                autoPlayback: true,
                airplay: true,
                lock: true,
                fastForward: true,
                gesture: true,
                lang: 'en',
                moreVideoAttr: {{
                    playsInline: true,
                    'webkit-playsinline': true,
                    preload: 'metadata'
                }}
            }});

            // Strict suppression of Artplayer internal and video context menus
            art.on('video:contextmenu', (e) => {{
                if (e && e.preventDefault) e.preventDefault();
                if (e && e.stopPropagation) e.stopPropagation();
                return false;
            }});
            art.on('contextmenu', (e) => {{
                if (e && e.preventDefault) e.preventDefault();
                if (e && e.stopPropagation) e.stopPropagation();
                return false;
            }});
            const playerEl = document.getElementById('artplayer');
            if (playerEl) {{
                playerEl.addEventListener('contextmenu', function (e) {{
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    return false;
                }}, true);
            }}

            art.on('video:error', () => {{
                art.notice.show = '⚠️ Format not supported by browser. Tap [📱 Open in Any Video Player] below!';
            }});

            // Screen Wake-Lock (Keeps display awake while playing video)
            let wakeLock = null;
            async function requestWakeLock() {{
                try {{
                    if ('wakeLock' in navigator) {{
                        wakeLock = await navigator.wakeLock.request('screen');
                        wakeLock.addEventListener('release', () => {{ wakeLock = null; }});
                    }}
                }} catch (e) {{
                    console.log('WakeLock:', e);
                }}
            }}
            art.on('play', () => {{ requestWakeLock(); }});
            art.on('pause', () => {{
                if (wakeLock !== null) {{
                    wakeLock.release().then(() => {{ wakeLock = null; }}).catch(() => {{}});
                }}
            }});
            document.addEventListener('visibilitychange', async () => {{
                if (wakeLock === null && document.visibilityState === 'visible' && !art.video.paused) {{
                    await requestWakeLock();
                }}
            }});

            let lastTap = 0;
            const container = document.getElementById('artplayer');
            if (container) {{
                container.addEventListener('touchend', function (e) {{
                    const currentTime = new Date().getTime();
                    const tapLength = currentTime - lastTap;
                    if (tapLength < 300 && tapLength > 0 && e.changedTouches && e.changedTouches.length > 0) {{
                        const touchX = e.changedTouches[0].clientX;
                        const width = window.innerWidth;
                        if (touchX < width * 0.4) {{
                            art.seek = Math.max(0, art.currentTime - 10);
                            art.notice.show = '⏪ -10s';
                        }} else if (touchX > width * 0.6) {{
                            art.seek = Math.min(art.duration, art.currentTime + 10);
                            art.notice.show = '⏩ +10s';
                        }}
                    }}
                    lastTap = currentTime;
                }});
            }}

            art.on('ready', () => {{
                try {{
                    const video = art.video;
                    if (video && video.audioTracks && video.audioTracks.length > 1) {{
                        const audioList = [];
                        for (let i = 0; i < video.audioTracks.length; i++) {{
                            const trk = video.audioTracks[i];
                            audioList.push({{
                                default: trk.enabled,
                                html: trk.label || trk.language || ('Track ' + (i + 1)),
                                trackIndex: i
                            }});
                        }}
                        art.setting.add({{
                            width: 220,
                            html: '🎧 Audio Track',
                            tooltip: 'Native Tracks',
                            selector: audioList,
                            onSelect: function (item) {{
                                for (let i = 0; i < video.audioTracks.length; i++) {{
                                    video.audioTracks[i].enabled = (i === item.trackIndex);
                                }}
                                return item.html;
                            }}
                        }});
                    }} else if ({is_dual_audio_js}) {{
                        art.setting.add({{
                            width: 260,
                            html: '🎧 Audio Switch',
                            tooltip: 'Dual / Multi',
                            selector: [
                                {{ default: true, html: '🎧 Browser Default Track' }},
                                {{ html: '🧡 Switch to Hindi in VLC', action: 'vlc' }},
                                {{ html: '🍿 Switch to Hindi in MX Player', action: 'mx' }}
                            ],
                            onSelect: function (item) {{
                                if (item.action === 'vlc') {{
                                    window.location.href = '{vlc_intent}';
                                }} else if (item.action === 'mx') {{
                                    window.location.href = '{mx_intent}';
                                }}
                                return item.html;
                            }}
                        }});
                    }}
                }} catch (e) {{
                    console.log('AudioTracks API:', e);
                }}

                // Autoplay check if navigated with ?autoplay=1
                try {{
                    const urlParams = new URLSearchParams(window.location.search);
                    if (urlParams.get('autoplay') === '1') {{
                        art.play().catch(() => {{
                            art.muted = true;
                            art.play();
                        }});
                    }}
                }} catch (e) {{}}
            }});

            // Netflix Autoplay Next Episode & Drawer Logic
            const nextEpUrl = "{next_ep_url}";
            const nextEpNum = "{next_ep_num}";
            const nextEpTitle = "{next_ep_title}";
            const currentEpNum = "{current_ep_num}";
            let countdownTimer = null;
            let countdownSec = 5;

            function triggerUpNext() {{
                if (!nextEpUrl || nextEpUrl === "") return;
                const overlay = document.getElementById("netflix-up-next");
                if (!overlay || overlay.style.display === "block") return;
                
                overlay.style.display = "block";
                countdownSec = 5;
                const secEl = document.getElementById("netflix-countdown-sec");
                const progEl = document.getElementById("countdown-progress");
                if (secEl) secEl.innerText = countdownSec;
                if (progEl) progEl.style.width = "100%";
                
                if (countdownTimer) clearInterval(countdownTimer);
                countdownTimer = setInterval(() => {{
                    countdownSec--;
                    if (secEl) secEl.innerText = countdownSec;
                    if (progEl) progEl.style.width = (countdownSec / 5 * 100) + "%";
                    if (countdownSec <= 0) {{
                        clearInterval(countdownTimer);
                        window.location.href = nextEpUrl;
                    }}
                }}, 1000);
            }}

            window.playNextNow = function() {{
                if (countdownTimer) clearInterval(countdownTimer);
                if (nextEpUrl && nextEpUrl !== "") window.location.href = nextEpUrl;
            }};

            window.cancelUpNext = function() {{
                if (countdownTimer) clearInterval(countdownTimer);
                const overlay = document.getElementById("netflix-up-next");
                if (overlay) overlay.style.display = "none";
            }};

            art.on('video:ended', () => {{
                if (nextEpUrl && nextEpUrl !== "") {{
                    triggerUpNext();
                }}
            }});

            let preEndTriggered = false;
            art.on('video:timeupdate', () => {{
                if (!preEndTriggered && nextEpUrl && nextEpUrl !== "" && art.duration > 30 && (art.duration - art.currentTime <= 10)) {{
                    preEndTriggered = true;
                    triggerUpNext();
                }}
            }});

            // Add Next Episode button in player controls
            if (nextEpUrl && nextEpUrl !== "") {{
                art.controls.add({{
                    name: 'next-ep-btn',
                    position: 'left',
                    index: 12,
                    html: '<span style="display:flex;align-items:center;cursor:pointer;font-size:16px;color:#ffffff;" title="Next: ' + nextEpTitle + '">⏭</span>',
                    click: function () {{
                        window.location.href = nextEpUrl;
                    }}
                }});
            }}

            // Add Episodes Selector in ArtPlayer Settings
            try {{
                const epsList = {episodes_json_str};
                if (epsList && epsList.length > 1) {{
                    art.setting.add({{
                        width: 220,
                        html: '📺 Episodes',
                        tooltip: 'Ep ' + (currentEpNum || '1'),
                        selector: epsList.map(item => ({{
                            default: item.is_current,
                            html: (item.is_current ? '🟢 ' : '') + 'Episode ' + item.ep,
                            url: item.url
                        }})),
                        onSelect: function (item) {{
                            if (item.url) window.location.href = item.url;
                            return item.html;
                        }}
                    }});
                }}
            }} catch (err) {{
                console.log('Episodes setting error:', err);
            }}
        }});
        // Bulletproof Anti-Right-Click & Stealth URL Inspection Shield
        (function () {{
            function killEvent(e) {{
                if (e) {{
                    if (e.preventDefault) e.preventDefault();
                    if (e.stopPropagation) e.stopPropagation();
                    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                }}
                return false;
            }}

            window.addEventListener("contextmenu", killEvent, true);
            document.addEventListener("contextmenu", killEvent, true);
            window.addEventListener("selectstart", killEvent, true);
            document.addEventListener("selectstart", killEvent, true);
            window.addEventListener("dragstart", killEvent, true);
            document.addEventListener("dragstart", killEvent, true);
            window.oncontextmenu = killEvent;
            document.oncontextmenu = killEvent;

            window.addEventListener("keydown", function (e) {{
                if (
                    e.keyCode === 123 ||
                    (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74 || e.keyCode === 75 || e.keyCode === 69)) ||
                    (e.metaKey && e.altKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74)) ||
                    ((e.ctrlKey || e.metaKey) && (e.keyCode === 85 || e.keyCode === 83 || e.keyCode === 80))
                ) {{
                    return killEvent(e);
                }}
            }}, true);

            // Stealth URL Cloaker: Masks href for desktop status bar, preserves native app & intent schemes
            function maskLink(el) {{
                if (!el || !el.getAttribute) return;
                const href = el.getAttribute('href');
                if (!href || href.startsWith('javascript:') || href === '#' || href.startsWith('#')) return;
                if (href.startsWith('intent:') || href.startsWith('vlc:') || href.startsWith('vlc-x-callback:') || href.startsWith('tg:') || href.startsWith('market:') || href.startsWith('whatsapp:') || href.includes('/playlist/') || href.includes('/player/')) return;
                el.setAttribute('data-target-url', href);
                el.removeAttribute('href');
                el.style.cursor = 'pointer';
                el.setAttribute('role', 'link');
                el.setAttribute('tabindex', '0');
            }}

            function maskAll(root) {{
                const scope = root || document;
                if (!scope.querySelectorAll) return;
                scope.querySelectorAll('a[href]').forEach(maskLink);
            }}

            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', function () {{ maskAll(); }});
            }} else {{
                maskAll();
            }}

            // Pre-emptively mask links before hover triggers the status bar
            document.addEventListener('mouseover', function (e) {{
                const a = e.target && e.target.closest && e.target.closest('a[href]');
                if (a) maskLink(a);
            }}, true);

            window.openSafeUrl = function (url, newTab) {{
                if (!url) return;
                if (newTab) {{
                    const a = document.createElement('a');
                    a.href = url;
                    a.target = '_blank';
                    a.rel = 'noopener noreferrer';
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => {{
                        try {{ document.body.removeChild(a); }} catch (e) {{}}
                    }}, 250);
                }} else {{
                    window.location.href = url;
                }}
            }};

            if (window.MutationObserver) {{
                new MutationObserver(function (mutations) {{
                    for (let i = 0; i < mutations.length; i++) {{
                        const added = mutations[i].addedNodes;
                        for (let j = 0; j < added.length; j++) {{
                            if (added[j].nodeType === 1) {{
                                if (added[j].tagName === 'A' && added[j].hasAttribute('href')) {{
                                    maskLink(added[j]);
                                }} else if (added[j].querySelectorAll) {{
                                    maskAll(added[j]);
                                }}
                            }}
                        }}
                    }}
                }}).observe(document.documentElement, {{ childList: true, subtree: true }});
            }}

            document.addEventListener('click', function (e) {{
                const el = e.target && e.target.closest && e.target.closest('[data-target-url]');
                if (!el) return;
                if (e.defaultPrevented) return;

                const url = el.getAttribute('data-target-url');
                if (!url) return;

                const target = el.getAttribute('target');
                const isNewTab = (target === '_blank' || e.ctrlKey || e.metaKey || e.button === 1);
                window.openSafeUrl(url, isNewTab);
            }}, false);

            document.addEventListener('keydown', function (e) {{
                if (e.key === 'Enter') {{
                    const el = document.activeElement && document.activeElement.closest && document.activeElement.closest('[data-target-url]');
                    if (el) el.click();
                }}
            }});
        }})();
    </script>
</body>
</html>
"""

MEDIA_POST_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>{post_title} — AkMovieVerse Cinema</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23e50914'><path d='M8 5v14l11-7z'/></svg>">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
            -webkit-touch-callout: none;
            -webkit-user-select: none;
            user-select: none;
        }}
        html, body {{
            -webkit-touch-callout: none !important;
            -webkit-user-select: none !important;
            user-select: none !important;
        }}
        img, video, canvas {{
            -webkit-user-drag: none !important;
            user-drag: none !important;
            pointer-events: auto;
        }}
        body {{
            background-color: #07090e;
            color: #f1f5f9;
            min-height: 100vh;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            overflow-x: hidden;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        .hero-banner {{
            position: relative;
            width: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            overflow: hidden;
            padding: 16px 12px 32px 12px;
        }}
        .hero-backdrop {{
            position: absolute;
            inset: 0;
            background-image: url('{backdrop_url}');
            background-size: cover;
            background-position: center top;
            filter: blur(28px) brightness(0.35) saturate(1.3);
            transform: scale(1.15);
            z-index: 1;
        }}
        .hero-overlay {{
            position: absolute;
            inset: 0;
            background: linear-gradient(180deg, rgba(7, 9, 14, 0.4) 0%, rgba(7, 9, 14, 0.85) 60%, #07090e 100%);
            z-index: 2;
        }}
        .hero-content {{
            position: relative;
            z-index: 10;
            width: 100%;
            max-width: 768px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        .navbar-card {{
            width: 100%;
            background: rgba(18, 24, 38, 0.75);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 12px 18px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 24px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
        }}
        .poster-wrapper {{
            width: 250px;
            max-width: 78%;
            aspect-ratio: 2/3;
            border-radius: 18px;
            overflow: hidden;
            border: 1px solid rgba(255, 255, 255, 0.16);
            box-shadow: 0 24px 60px rgba(0, 0, 0, 0.9), 0 0 35px rgba(225, 29, 72, 0.25);
            background: #0f172a;
            position: relative;
            margin-bottom: 16px;
        }}
        .poster-wrapper img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}
        .badge-pill {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 12px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.2px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            background: rgba(18, 24, 38, 0.85);
            color: #e2e8f0;
            backdrop-filter: blur(10px);
        }}
        .badge-source {{
            background: rgba(159, 18, 57, 0.35);
            border-color: rgba(244, 63, 94, 0.45);
            color: #fda4af;
            font-weight: 700;
        }}
        .badge-qual {{
            background: rgba(12, 74, 110, 0.45);
            border-color: rgba(56, 189, 248, 0.45);
            color: #7dd3fc;
            font-weight: 700;
        }}
        .badge-audio {{
            background: rgba(120, 53, 15, 0.4);
            border-color: rgba(245, 158, 11, 0.45);
            color: #fcd34d;
            font-weight: 700;
        }}
        .badge-rating {{
            background: rgba(19, 78, 74, 0.45);
            border-color: rgba(45, 212, 191, 0.45);
            color: #5eead4;
            font-weight: 700;
        }}
        .badge-cast {{
            background: rgba(255, 255, 255, 0.05);
            border-color: rgba(255, 255, 255, 0.1);
            color: #94a3b8;
            font-size: 11.5px;
        }}
        .btn-play-primary {{
            background: linear-gradient(135deg, #e50914 0%, #b80710 100%);
            box-shadow: 0 10px 25px rgba(229, 9, 20, 0.4);
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        .btn-play-primary:hover {{
            transform: translateY(-2px);
            box-shadow: 0 14px 30px rgba(229, 9, 20, 0.55);
            filter: brightness(1.08);
        }}
        .btn-bot-action {{
            background: rgba(14, 165, 233, 0.15);
            border: 1px solid rgba(56, 189, 248, 0.35);
            color: #38bdf8;
            transition: all 0.2s ease;
        }}
        .btn-bot-action:hover {{
            background: rgba(14, 165, 233, 0.25);
            border-color: rgba(56, 189, 248, 0.6);
            transform: translateY(-2px);
        }}
        .btn-vip-action {{
            background: rgba(245, 158, 11, 0.12);
            border: 1px solid rgba(245, 158, 11, 0.3);
            color: #fbbf24;
            transition: all 0.2s ease;
        }}
        .btn-vip-action:hover {{
            background: rgba(245, 158, 11, 0.22);
            border-color: rgba(245, 158, 11, 0.55);
            transform: translateY(-2px);
        }}
        .content-panel {{
            background: rgba(18, 24, 38, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            backdrop-filter: blur(14px);
        }}
        .print-card, .ep-card {{
            background: rgba(22, 30, 48, 0.75);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px;
            transition: all 0.2s ease;
        }}
        .print-card:hover, .ep-card:hover {{
            background: rgba(30, 42, 68, 0.95);
            border-color: rgba(56, 189, 248, 0.45);
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
        }}
        .sponsor-banner-bar {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.14), rgba(239, 68, 68, 0.14));
            border: 1px solid rgba(245, 158, 11, 0.4);
            padding: 11px 16px;
            border-radius: 12px;
            text-decoration: none;
            margin-bottom: 14px;
            transition: all 0.2s ease;
        }}
        .sponsor-banner-bar:hover {{
            border-color: rgba(245, 158, 11, 0.8);
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.25), rgba(239, 68, 68, 0.25));
            transform: translateY(-1px);
        }}
        .sponsor-tag {{
            font-size: 11px;
            font-weight: 900;
            background: #f59e0b;
            color: #000;
            padding: 3px 8px;
            border-radius: 5px;
            letter-spacing: 0.5px;
            margin-right: 10px;
            flex-shrink: 0;
        }}
        .sponsor-text {{
            color: #fef3c7;
            font-size: 14.5px;
            font-weight: 700;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            flex: 1;
        }}
        .sponsor-arrow {{
            color: #f59e0b;
            font-size: 16px;
            font-weight: 800;
            margin-left: 10px;
        }}
    </style>
</head>
<body class="p-2 sm:p-5 flex flex-col items-center" oncontextmenu="return false;" onselectstart="return false;" ondragstart="return false;">
    <div class="w-full max-w-4xl space-y-4">
        <!-- Top Navigation Bar -->
        <header class="flex items-center justify-between gap-2 navbar-card py-2.5 px-3 sm:px-4">
            <div class="flex items-center min-w-0">
                <div class="text-base sm:text-xl font-black text-red-500 tracking-wider flex items-center gap-1.5 truncate">
                    <span>🍿</span> <span class="truncate">AkMovieVerse</span>
                </div>
            </div>
            <div class="flex items-center gap-1.5 sm:gap-2 flex-shrink-0">
                <a href="{channel_url}" target="_blank" class="text-xs sm:text-sm font-semibold px-2.5 sm:px-3 py-1.5 bg-sky-500/10 hover:bg-sky-500/20 text-sky-400 rounded-xl transition border border-sky-500/20 flex items-center gap-1 whitespace-nowrap">
                    <span>📢</span> <span>Channel</span>
                </a>
                <a href="https://t.me/{bot_username}" target="_blank" class="text-xs sm:text-sm font-medium px-2.5 sm:px-3.5 py-1.5 bg-white/10 hover:bg-white/20 text-gray-200 rounded-xl transition flex items-center gap-1 border border-white/10 whitespace-nowrap">
                    <span>🤖</span> <span>Bot</span>
                </a>
            </div>
        </header>

        {sponsor_banner_html}

        <!-- Main Hero Banner Card (Screenshot exact layout) -->
        <div class="hero-banner rounded-3xl border border-white/10 shadow-2xl relative">
            <div class="hero-backdrop"></div>
            <div class="hero-overlay"></div>
            
            <div class="hero-content">
                <!-- Center Poster -->
                <div class="poster-wrapper">
                    <img src="{poster_url}" alt="{post_title}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                    <div class="w-full h-full flex items-center justify-center text-5xl bg-slate-900" style="display:none;">🎬</div>
                </div>

                <!-- Big Title -->
                <h1 class="text-2xl sm:text-3xl font-black text-white text-center tracking-tight mb-3 px-2">
                    {post_title}
                </h1>

                <!-- Badges Row 1: Date, Type, Source, Rating -->
                <div class="flex flex-wrap items-center justify-center gap-2 mb-2 px-2">
                    {badges_row1_html}
                </div>

                <!-- Badges Row 2: Qualities, Audio -->
                <div class="flex flex-wrap items-center justify-center gap-2 mb-2 px-2">
                    {badges_row2_html}
                </div>

                <!-- Badges Row 3: Cast & Director -->
                <div class="flex flex-wrap items-center justify-center gap-2 mb-4 px-2">
                    {badges_row3_html}
                </div>

                <!-- Storyline Hook -->
                <div class="content-panel p-4 rounded-xl text-center max-w-2xl mb-4 mx-2">
                    <div class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1">📖 Storyline Overview</div>
                    <p class="text-xs sm:text-sm text-gray-300 leading-relaxed">{overview_text}</p>
                </div>

                <!-- Action Buttons (Safe & Monetized) -->
                {action_buttons_html}
            </div>
        </div>

        <!-- Section: Movie Prints OR Series Episodes Grid -->
        {prints_or_episodes_html}
    </div>

    <!-- Bulletproof Anti-Right-Click & Stealth URL Inspection Shield -->
    <script>
        (function () {{
            function killEvent(e) {{
                if (e) {{
                    if (e.preventDefault) e.preventDefault();
                    if (e.stopPropagation) e.stopPropagation();
                    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                }}
                return false;
            }}

            window.addEventListener("contextmenu", killEvent, true);
            document.addEventListener("contextmenu", killEvent, true);
            window.addEventListener("selectstart", killEvent, true);
            document.addEventListener("selectstart", killEvent, true);
            window.addEventListener("dragstart", killEvent, true);
            document.addEventListener("dragstart", killEvent, true);
            window.oncontextmenu = killEvent;
            document.oncontextmenu = killEvent;

            window.addEventListener("keydown", function (e) {{
                if (
                    e.keyCode === 123 ||
                    (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74 || e.keyCode === 75 || e.keyCode === 69)) ||
                    (e.metaKey && e.altKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74)) ||
                    ((e.ctrlKey || e.metaKey) && (e.keyCode === 85 || e.keyCode === 83 || e.keyCode === 80))
                ) {{
                    return killEvent(e);
                }}
            }}, true);

            // Stealth URL Cloaker: Masks href for desktop status bar, preserves native app & intent schemes
            function maskLink(el) {{
                if (!el || !el.getAttribute) return;
                const href = el.getAttribute('href');
                if (!href || href.startsWith('javascript:') || href === '#' || href.startsWith('#')) return;
                if (href.startsWith('intent:') || href.startsWith('vlc:') || href.startsWith('vlc-x-callback:') || href.startsWith('tg:') || href.startsWith('market:') || href.startsWith('whatsapp:') || href.includes('/playlist/') || href.includes('/player/')) return;
                el.setAttribute('data-target-url', href);
                el.removeAttribute('href');
                el.style.cursor = 'pointer';
                el.setAttribute('role', 'link');
                el.setAttribute('tabindex', '0');
            }}

            function maskAll(root) {{
                const scope = root || document;
                if (!scope.querySelectorAll) return;
                scope.querySelectorAll('a[href]').forEach(maskLink);
            }}

            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', function () {{ maskAll(); }});
            }} else {{
                maskAll();
            }}

            // Pre-emptively mask links before hover triggers the status bar
            document.addEventListener('mouseover', function (e) {{
                const a = e.target && e.target.closest && e.target.closest('a[href]');
                if (a) maskLink(a);
            }}, true);

            window.openSafeUrl = function (url, newTab) {{
                if (!url) return;
                if (newTab) {{
                    const a = document.createElement('a');
                    a.href = url;
                    a.target = '_blank';
                    a.rel = 'noopener noreferrer';
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => {{
                        try {{ document.body.removeChild(a); }} catch (e) {{}}
                    }}, 250);
                }} else {{
                    window.location.href = url;
                }}
            }};

            if (window.MutationObserver) {{
                new MutationObserver(function (mutations) {{
                    for (let i = 0; i < mutations.length; i++) {{
                        const added = mutations[i].addedNodes;
                        for (let j = 0; j < added.length; j++) {{
                            if (added[j].nodeType === 1) {{
                                if (added[j].tagName === 'A' && added[j].hasAttribute('href')) {{
                                    maskLink(added[j]);
                                }} else if (added[j].querySelectorAll) {{
                                    maskAll(added[j]);
                                }}
                            }}
                        }}
                    }}
                }}).observe(document.documentElement, {{ childList: true, subtree: true }});
            }}

            document.addEventListener('click', function (e) {{
                const el = e.target && e.target.closest && e.target.closest('[data-target-url]');
                if (!el) return;
                if (e.defaultPrevented) return;

                const url = el.getAttribute('data-target-url');
                if (!url) return;

                const target = el.getAttribute('target');
                const isNewTab = (target === '_blank' || e.ctrlKey || e.metaKey || e.button === 1);
                window.openSafeUrl(url, isNewTab);
            }}, false);

            document.addEventListener('keydown', function (e) {{
                if (e.key === 'Enter') {{
                    const el = document.activeElement && document.activeElement.closest && document.activeElement.closest('[data-target-url]');
                    if (el) el.click();
                }}
            }});
        }})();
    </script>
</body>
</html>
"""

SERIES_HUB_HTML = MEDIA_POST_HTML


CATALOG_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>{page_title} — AkMovieVerse Cinema</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            -webkit-tap-highlight-color: transparent;
            -webkit-touch-callout: none;
            -webkit-user-select: none;
            user-select: none;
        }}
        input, textarea {{
            -webkit-user-select: auto;
            user-select: auto;
        }}
        body {{
            background: radial-gradient(circle at 50% 0%, #172033 0%, #090d16 60%, #05070c 100%);
            color: #f1f5f9;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 14px 14px 40px 14px;
        }}
        .container {{
            max-width: 1080px;
            width: 100%;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 4px 2px 14px 2px;
            gap: 8px;
            width: 100%;
        }}
        .brand {{
            font-size: 19px;
            font-weight: 800;
            color: #38bdf8;
            text-decoration: none;
            display: flex;
            align-items: center;
            gap: 6px;
            letter-spacing: -0.3px;
            flex-shrink: 0;
            min-width: 0;
        }}
        .header-actions {{
            display: flex;
            align-items: center;
            gap: 6px;
            flex-shrink: 0;
        }}
        .nav-btn {{
            background: rgba(56, 189, 248, 0.12);
            border: 1px solid rgba(56, 189, 248, 0.35);
            color: #38bdf8;
            font-size: 11.5px;
            font-weight: 700;
            padding: 6px 11px;
            border-radius: 999px;
            text-decoration: none;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            white-space: nowrap;
            line-height: 1;
            flex-shrink: 0;
        }}
        .nav-btn:hover {{
            background: rgba(56, 189, 248, 0.25);
            color: #ffffff;
            border-color: #38bdf8;
        }}
        @media (max-width: 380px) {{
            .brand {{
                font-size: 16.5px;
            }}
            .nav-btn {{
                font-size: 10.5px;
                padding: 5px 8px;
            }}
        }}
        /* Search Box */
        .catalog-search-section {{
            margin-bottom: 14px;
        }}
        .catalog-search-form {{
            display: flex;
            align-items: center;
            background: rgba(22, 27, 34, 0.85);
            border: 1px solid rgba(56, 189, 248, 0.28);
            border-radius: 14px;
            padding: 4px 6px 4px 14px;
            backdrop-filter: blur(14px);
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.5);
            transition: all 0.2s;
        }}
        .catalog-search-form:focus-within {{
            border-color: #38bdf8;
            box-shadow: 0 0 20px rgba(56, 189, 248, 0.3);
        }}
        .catalog-search-icon {{
            font-size: 16px;
            color: #64748b;
            margin-right: 6px;
            flex-shrink: 0;
        }}
        .catalog-search-input {{
            flex: 1;
            min-width: 0;
            background: transparent;
            border: none;
            color: #ffffff;
            font-size: 14px;
            outline: none;
            padding: 7px 4px;
        }}
        .catalog-search-input::placeholder {{
            color: #64748b;
            font-size: 13px;
        }}
        .catalog-search-btn {{
            background: linear-gradient(135deg, #0284c7, #2563eb);
            color: #ffffff;
            border: none;
            padding: 8px 16px;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 700;
            cursor: pointer;
            white-space: nowrap;
            flex-shrink: 0;
            transition: all 0.2s;
        }}
        .catalog-search-btn:active {{
            transform: scale(0.96);
        }}
        /* Filter Pills */
        .filters-scroll {{
            display: flex;
            gap: 8px;
            overflow-x: auto;
            padding-bottom: 12px;
            margin-bottom: 14px;
            scrollbar-width: none;
        }}
        .filters-scroll::-webkit-scrollbar {{
            display: none;
        }}
        .filter-pill {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: #94a3b8;
            padding: 7px 14px;
            border-radius: 999px;
            font-size: 12.5px;
            font-weight: 600;
            text-decoration: none;
            white-space: nowrap;
            transition: all 0.2s;
        }}
        .filter-pill.active {{
            background: rgba(56, 189, 248, 0.2);
            border-color: #38bdf8;
            color: #38bdf8;
            box-shadow: 0 0 12px rgba(56, 189, 248, 0.25);
        }}
        /* Status line */
        .catalog-status {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 13px;
            color: #64748b;
            margin-bottom: 16px;
            padding: 0 4px;
        }}
        .catalog-status b {{
            color: #e2e8f0;
        }}
        /* Movie Grid */
        .catalog-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
        }}
        @media (min-width: 600px) {{
            .catalog-grid {{
                grid-template-columns: repeat(3, 1fr);
                gap: 16px;
            }}
        }}
        @media (min-width: 900px) {{
            .catalog-grid {{
                grid-template-columns: repeat(4, 1fr);
                gap: 18px;
            }}
        }}
        .catalog-card {{
            background: rgba(22, 27, 34, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.4);
            transition: transform 0.22s, border-color 0.22s, box-shadow 0.22s;
        }}
        .catalog-card:hover {{
            transform: translateY(-4px);
            border-color: rgba(56, 189, 248, 0.45);
            box-shadow: 0 14px 35px rgba(0, 0, 0, 0.6), 0 0 20px rgba(56, 189, 248, 0.15);
        }}
        .poster-wrap {{
            position: relative;
            width: 100%;
            aspect-ratio: 2 / 3;
            background: #0d1117;
            overflow: hidden;
            display: block;
            text-decoration: none;
            cursor: pointer;
        }}
        .poster-img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
            transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        .poster-play-overlay {{
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.35);
            display: none;
            align-items: center;
            justify-content: center;
            opacity: 0;
            transition: opacity 0.22s ease;
            z-index: 3;
        }}
        @media (hover: hover) and (pointer: fine) {{
            .poster-play-overlay {{
                display: flex;
            }}
            .catalog-card:hover .poster-play-overlay {{
                opacity: 1;
            }}
            .catalog-card:hover .poster-play-icon {{
                transform: scale(1);
            }}
            .catalog-card:hover .poster-img {{
                transform: scale(1.06);
            }}
        }}
        .poster-play-icon {{
            width: 44px;
            height: 44px;
            border-radius: 50%;
            background: rgba(56, 189, 248, 0.95);
            box-shadow: 0 0 25px rgba(56, 189, 248, 0.65);
            display: flex;
            align-items: center;
            justify-content: center;
            color: #030712;
            font-size: 18px;
            padding-left: 3px;
            transform: scale(0.75);
            transition: transform 0.22s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        .poster-fallback {{
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: radial-gradient(circle at center, #1e293b, #0f172a);
            color: #64748b;
            font-size: 38px;
        }}
        .card-badges-top {{
            position: absolute;
            top: 6px;
            left: 6px;
            display: flex;
            flex-direction: column;
            gap: 3px;
            z-index: 2;
            max-width: 85%;
        }}
        .cbadge {{
            font-size: 9.5px;
            font-weight: 700;
            padding: 2.5px 6px;
            border-radius: 5px;
            text-transform: uppercase;
            letter-spacing: 0.3px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.4);
            width: fit-content;
            line-height: 1.1;
        }}
        .cbadge-qual {{
            background: rgba(168, 85, 247, 0.9);
            color: #ffffff;
        }}
        .cbadge-comb {{
            background: rgba(234, 88, 12, 0.9);
            color: #ffffff;
        }}
        .cbadge-anime {{
            background: linear-gradient(135deg, #ec4899, #d946ef);
            color: #ffffff;
            font-weight: 800;
        }}
        .cbadge-new {{
            background: linear-gradient(135deg, #ef4444, #dc2626);
            color: #ffffff;
            box-shadow: 0 0 10px rgba(239, 68, 68, 0.6);
            font-weight: 800;
        }}
        .cbadge-eps {{
            background: linear-gradient(135deg, #0284c7, #2563eb);
            color: #ffffff;
            font-weight: 700;
        }}
        .cbadge-lang {{
            background: rgba(16, 185, 129, 0.9);
            color: #ffffff;
            font-weight: 700;
        }}
        .card-size-bottom {{
            position: absolute;
            bottom: 6px;
            right: 6px;
            background: rgba(0, 0, 0, 0.82);
            backdrop-filter: blur(6px);
            color: #38bdf8;
            font-size: 9.5px;
            font-weight: 700;
            padding: 2.5px 6px;
            border-radius: 5px;
            border: 1px solid rgba(255, 255, 255, 0.12);
            z-index: 2;
            white-space: nowrap;
        }}
        .card-body {{
            padding: 8px 8px 10px 8px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            flex: 1;
            justify-content: space-between;
        }}
        .card-title {{
            font-size: 12.5px;
            font-weight: 700;
            color: #f1f5f9;
            line-height: 1.3;
            margin-bottom: 4px;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            text-decoration: none;
            transition: color 0.15s ease;
            cursor: pointer;
            min-height: 32px;
        }}
        .card-title:hover {{
            color: #38bdf8;
        }}
        .card-stream-btn, .card-series-btn {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 5px;
            width: 100%;
            padding: 7px 6px;
            color: #ffffff;
            text-decoration: none;
            font-size: 11.5px;
            font-weight: 700;
            border-radius: 8px;
            transition: all 0.2s;
            white-space: nowrap;
        }}
        .card-stream-btn {{
            background: linear-gradient(135deg, #0284c7, #2563eb);
            box-shadow: 0 4px 12px rgba(2, 132, 199, 0.35);
        }}
        .card-stream-btn:hover {{
            background: linear-gradient(135deg, #38bdf8, #0284c7);
            box-shadow: 0 6px 18px rgba(2, 132, 199, 0.55);
        }}
        .card-series-btn {{
            background: linear-gradient(135deg, #e50914, #b91c1c);
            box-shadow: 0 4px 12px rgba(229, 9, 20, 0.35);
        }}
        .card-series-btn:hover {{
            background: linear-gradient(135deg, #ef4444, #dc2626);
            box-shadow: 0 6px 18px rgba(229, 9, 20, 0.55);
        }}
        .card-stream-btn:active, .card-series-btn:active {{
            transform: scale(0.97);
        }}
        /* Pagination */
        .pagination {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            margin-top: 30px;
            padding: 10px 0;
        }}
        .page-btn {{
            background: rgba(22, 27, 34, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #f1f5f9;
            padding: 9px 18px;
            border-radius: 12px;
            font-size: 13px;
            font-weight: 600;
            text-decoration: none;
            transition: all 0.2s;
        }}
        .page-btn:hover:not(.disabled) {{
            border-color: #38bdf8;
            color: #38bdf8;
            box-shadow: 0 0 12px rgba(56, 189, 248, 0.25);
        }}
        .page-btn.disabled {{
            opacity: 0.35;
            cursor: not-allowed;
            pointer-events: none;
        }}
        .page-info {{
            font-size: 13px;
            color: #94a3b8;
            font-weight: 600;
        }}
        /* Empty State */
        .empty-card {{
            grid-column: 1 / -1;
            background: rgba(22, 27, 34, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 50px 20px;
            text-align: center;
        }}
        .empty-icon {{
            font-size: 42px;
            margin-bottom: 12px;
        }}
        .empty-title {{
            font-size: 18px;
            font-weight: 700;
            color: #f8fafc;
            margin-bottom: 6px;
        }}
        .empty-desc {{
            font-size: 13px;
            color: #94a3b8;
            margin-bottom: 20px;
        }}
        .empty-btn {{
            display: inline-block;
            background: linear-gradient(135deg, #0284c7, #2563eb);
            color: #ffffff;
            text-decoration: none;
            padding: 10px 22px;
            border-radius: 10px;
            font-weight: 600;
            font-size: 13px;
        }}
        .sponsor-banner-bar {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.14), rgba(239, 68, 68, 0.14));
            border: 1px solid rgba(245, 158, 11, 0.4);
            padding: 11px 16px;
            border-radius: 12px;
            text-decoration: none;
            margin-bottom: 14px;
            transition: all 0.2s ease;
        }}
        .sponsor-banner-bar:hover {{
            border-color: rgba(245, 158, 11, 0.8);
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.25), rgba(239, 68, 68, 0.25));
            transform: translateY(-1px);
        }}
        .sponsor-tag {{
            font-size: 11px;
            font-weight: 900;
            background: #f59e0b;
            color: #000;
            padding: 3px 8px;
            border-radius: 5px;
            letter-spacing: 0.5px;
            margin-right: 10px;
            flex-shrink: 0;
        }}
        .sponsor-text {{
            color: #fef3c7;
            font-size: 14.5px;
            font-weight: 700;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            flex: 1;
        }}
        .sponsor-arrow {{
            color: #f59e0b;
            font-size: 16px;
            font-weight: 800;
            margin-left: 10px;
        }}
    </style>
</head>
<body oncontextmenu="return false;" onselectstart="return false;" ondragstart="return false;">
    <div class="container">
        <div class="header">
            <a href="{browse_url}" class="brand">
                <span>⚡</span> AkMovieVerse
            </a>
            <div class="header-actions">
                <a href="{channel_url}" target="_blank" class="nav-btn">📢 Channel</a>
                <a href="https://t.me/{bot_username}" target="_blank" class="nav-btn">🤖 Bot</a>
            </div>
        </div>

        {sponsor_banner_html}

        <div class="catalog-search-section">
            <form action="{browse_url}" method="GET" class="catalog-search-form">
                <span class="catalog-search-icon">🔍</span>
                <input type="text" name="q" value="{search_query}" class="catalog-search-input" placeholder="Search movies, web series, anime..." autocomplete="off">
                <button type="submit" class="catalog-search-btn">Search</button>
            </form>
        </div>

        <div class="filters-scroll">
            <a href="{browse_url}?q={search_query}" class="filter-pill {active_filter_all}">🔥 All Titles</a>
            <a href="{browse_url}?filter=recent&q={search_query}" class="filter-pill {active_filter_recent}">⚡ Recently Updated</a>
            <a href="{browse_url}?filter=series&q={search_query}" class="filter-pill {active_filter_series}">📺 Web Series</a>
            <a href="{browse_url}?filter=movies&q={search_query}" class="filter-pill {active_filter_movies}">🎬 Movies</a>
            <a href="{browse_url}?filter=anime&q={search_query}" class="filter-pill {active_filter_anime}">🌸 Anime</a>
            <a href="{browse_url}?quality=1080p&q={search_query}" class="filter-pill {active_filter_1080p}">💎 1080p FHD</a>
            <a href="{browse_url}?quality=720p&q={search_query}" class="filter-pill {active_filter_720p}">⚡ 720p HD</a>
            <a href="{browse_url}?quality=2160p&q={search_query}" class="filter-pill {active_filter_4k}">👑 4K UHD</a>
        </div>

        <div class="catalog-status">
            <div>{status_text}</div>
            <div class="page-info">{page_info_text}</div>
        </div>

        <div class="catalog-grid">
            {movie_cards_html}
        </div>

        <div class="pagination">
            {prev_btn_html}
            <span class="page-info">{page_info_text}</span>
            {next_btn_html}
        </div>
    </div>
    <!-- Bulletproof Anti-Right-Click & Stealth URL Inspection Shield -->
    <script>
        (function () {{
            function killEvent(e) {{
                if (e) {{
                    if (e.preventDefault) e.preventDefault();
                    if (e.stopPropagation) e.stopPropagation();
                    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                }}
                return false;
            }}

            window.addEventListener("contextmenu", killEvent, true);
            document.addEventListener("contextmenu", killEvent, true);

            function isInputField(target) {{
                return target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA');
            }}

            window.addEventListener("selectstart", function (e) {{
                if (isInputField(e.target)) return true;
                return killEvent(e);
            }}, true);
            document.addEventListener("selectstart", function (e) {{
                if (isInputField(e.target)) return true;
                return killEvent(e);
            }}, true);

            window.addEventListener("dragstart", killEvent, true);
            document.addEventListener("dragstart", killEvent, true);
            window.oncontextmenu = killEvent;
            document.oncontextmenu = killEvent;

            window.addEventListener("keydown", function (e) {{
                if (
                    e.keyCode === 123 ||
                    (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74 || e.keyCode === 75 || e.keyCode === 69)) ||
                    (e.metaKey && e.altKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74)) ||
                    ((e.ctrlKey || e.metaKey) && (e.keyCode === 85 || e.keyCode === 83 || e.keyCode === 80))
                ) {{
                    return killEvent(e);
                }}
            }}, true);

            // Stealth URL Cloaker: Masks href for desktop status bar, preserves native app & intent schemes
            function maskLink(el) {{
                if (!el || !el.getAttribute) return;
                const href = el.getAttribute('href');
                if (!href || href.startsWith('javascript:') || href === '#' || href.startsWith('#')) return;
                if (href.startsWith('intent:') || href.startsWith('vlc:') || href.startsWith('vlc-x-callback:') || href.startsWith('tg:') || href.startsWith('market:') || href.startsWith('whatsapp:') || href.includes('/playlist/') || href.includes('/player/')) return;
                el.setAttribute('data-target-url', href);
                el.removeAttribute('href');
                el.style.cursor = 'pointer';
                el.setAttribute('role', 'link');
                el.setAttribute('tabindex', '0');
            }}

            function maskAll(root) {{
                const scope = root || document;
                if (!scope.querySelectorAll) return;
                scope.querySelectorAll('a[href]').forEach(maskLink);
            }}

            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', function () {{ maskAll(); }});
            }} else {{
                maskAll();
            }}

            // Pre-emptively mask links before hover triggers the status bar
            document.addEventListener('mouseover', function (e) {{
                const a = e.target && e.target.closest && e.target.closest('a[href]');
                if (a) maskLink(a);
            }}, true);

            window.openSafeUrl = function (url, newTab) {{
                if (!url) return;
                if (newTab) {{
                    const a = document.createElement('a');
                    a.href = url;
                    a.target = '_blank';
                    a.rel = 'noopener noreferrer';
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => {{
                        try {{ document.body.removeChild(a); }} catch (e) {{}}
                    }}, 250);
                }} else {{
                    window.location.href = url;
                }}
            }};

            if (window.MutationObserver) {{
                new MutationObserver(function (mutations) {{
                    for (let i = 0; i < mutations.length; i++) {{
                        const added = mutations[i].addedNodes;
                        for (let j = 0; j < added.length; j++) {{
                            if (added[j].nodeType === 1) {{
                                if (added[j].tagName === 'A' && added[j].hasAttribute('href')) {{
                                    maskLink(added[j]);
                                }} else if (added[j].querySelectorAll) {{
                                    maskAll(added[j]);
                                }}
                            }}
                        }}
                    }}
                }}).observe(document.documentElement, {{ childList: true, subtree: true }});
            }}

            document.addEventListener('click', function (e) {{
                const el = e.target && e.target.closest && e.target.closest('[data-target-url]');
                if (!el) return;
                if (e.defaultPrevented) return;

                const url = el.getAttribute('data-target-url');
                if (!url) return;

                const target = el.getAttribute('target');
                const isNewTab = (target === '_blank' || e.ctrlKey || e.metaKey || e.button === 1);
                window.openSafeUrl(url, isNewTab);
            }}, false);

            document.addEventListener('keydown', function (e) {{
                if (e.key === 'Enter') {{
                    const el = document.activeElement && document.activeElement.closest && document.activeElement.closest('[data-target-url]');
                    if (el) el.click();
                }}
            }});
        }})();
    </script>
</body>
</html>
"""


_WEB_DL_CACHE = {"enabled": None}

async def is_web_download_enabled() -> bool:
    """Check if direct file downloading in the web player is enabled."""
    if _WEB_DL_CACHE["enabled"] is not None:
        return _WEB_DL_CACHE["enabled"]
    try:
        from database.mongo import get_bot_setting
        val = await get_bot_setting("enable_web_download")
        if val is not None:
            _WEB_DL_CACHE["enabled"] = bool(val)
            return _WEB_DL_CACHE["enabled"]
    except Exception:
        pass
    return getattr(Config, "ENABLE_WEB_DOWNLOAD", False)

async def set_web_download_enabled(enabled: bool) -> bool:
    from database.mongo import set_bot_setting
    _WEB_DL_CACHE["enabled"] = bool(enabled)
    return await set_bot_setting("enable_web_download", bool(enabled))


def generate_vip_stream_token(user_id: int, expires_in: int = 7200) -> str:
    """Generate tamper-proof HMAC signed token for VIP streaming & download session (default 2 hours)."""
    import time
    import hmac
    import hashlib
    import base64
    expiry = int(time.time()) + expires_in
    payload = f"{user_id}:{expiry}"
    secret = (Config.BOT_TOKEN or "vip_stream_secret").encode("utf-8")
    sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8").rstrip("=")


def verify_vip_stream_token(token: str) -> tuple[bool, int | None]:
    """Verify VIP session token signature and check expiry. Returns (is_valid, user_id)."""
    import time
    import hmac
    import hashlib
    import base64
    try:
        if not token:
            return False, None
        pad = len(token) % 4
        if pad:
            token += "=" * (4 - pad)
        decoded = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        parts = decoded.split(":")
        if len(parts) != 3:
            return False, None
        uid_str, exp_str, sig = parts
        user_id = int(uid_str)
        expiry = int(exp_str)
        payload = f"{user_id}:{expiry}"
        secret = (Config.BOT_TOKEN or "vip_stream_secret").encode("utf-8")
        expected_sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected_sig):
            return False, None
        if time.time() > expiry:
            return False, None
        return True, user_id
    except Exception:
        return False, None


def get_stream_base_url(request: web.Request | None = None) -> str:
    """Resolve public stream base URL dynamically from incoming request or Config.
    Automatically prioritizes incoming host headers so Web Browse and Streaming always
    reflect the exact domain the user is visiting, and automatically syncs Config.STREAM_URL.
    """
    if request:
        proto = request.headers.get("X-Forwarded-Proto", getattr(request, "scheme", "https"))
        host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host") or getattr(request, "host", "")
        if host and not any(h in host for h in ("127.0.0.1", "localhost", "0.0.0.0")):
            detected = f"{proto}://{host}".rstrip("/")
            if not Config.STREAM_URL or any(h in Config.STREAM_URL for h in ("127.0.0.1", "localhost")):
                Config.STREAM_URL = detected
            return detected

    if Config.STREAM_URL and not any(h in Config.STREAM_URL for h in ("127.0.0.1", "localhost")):
        return Config.STREAM_URL.rstrip("/")
    if Config.WEB_URL and not any(h in Config.WEB_URL for h in ("127.0.0.1", "localhost")):
        return Config.WEB_URL.rstrip("/")

    if request:
        proto = request.headers.get("X-Forwarded-Proto", getattr(request, "scheme", "http"))
        host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host") or getattr(request, "host", f"127.0.0.1:{Config.PORT}")
        return f"{proto}://{host}".rstrip("/")

    return f"http://127.0.0.1:{Config.PORT}"


_file_doc_cache: dict[str, tuple[dict, float]] = {}


async def resolve_file_from_param(param: str) -> dict | None:
    """Find file document in MongoDB by file_unique_id, file_id, or ObjectId with in-memory caching."""
    if not param:
        return None
    try:
        import time
        clean_p = str(param).strip()
        now_ts = time.time()
        cached = _file_doc_cache.get(clean_p)
        if cached and (now_ts - cached[1] < 3600):
            return cached[0]

        # 1. Primary search index
        doc = await mongo.files.find_one({"file_unique_id": clean_p})
        if doc:
            if len(_file_doc_cache) > 2000:
                _file_doc_cache.clear()
            _file_doc_cache[clean_p] = (doc, now_ts)
            return doc
        if mongo.has_secondary:
            doc = await mongo.files_secondary.find_one({"file_unique_id": clean_p})
            if doc:
                return doc
        doc = await mongo.files.find_one({"file_id": clean_p})
        if doc:
            return doc
        if mongo.has_secondary:
            doc = await mongo.files_secondary.find_one({"file_id": clean_p})
            if doc:
                return doc
        try:
            doc = await mongo.files.find_one({"_id": ObjectId(clean_p)})
            if doc:
                return doc
            if mongo.has_secondary:
                doc = await mongo.files_secondary.find_one({"_id": ObjectId(clean_p)})
                if doc:
                    return doc
        except Exception:
            pass

        # 2. Check isolated temp stream files (never indexed into search catalog)
        try:
            doc = await mongo.db["temp_stream_files"].find_one({"file_unique_id": clean_p})
            if doc:
                return doc
            doc = await mongo.db["temp_stream_files"].find_one({"file_id": clean_p})
            if doc:
                return doc
        except Exception:
            pass

        # 3. Check batches collection (if param is batch_id or matches a file inside a batch)
        try:
            batch = await mongo.batches.find_one({"batch_id": clean_p})
            if batch and batch.get("files"):
                return batch["files"][0]
            batch_file = await mongo.batches.find_one({"files.file_unique_id": clean_p})
            if batch_file and batch_file.get("files"):
                for bf in batch_file["files"]:
                    if bf.get("file_unique_id") == clean_p or bf.get("file_id") == clean_p:
                        return bf
        except Exception:
            pass

        return None
    except Exception as e:
        logger.error(f"Error resolving file param {param}: {e}", exc_info=True)
        return None


async def options_handler(request: web.Request):
    """Handle CORS preflight requests."""
    return web.Response(
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "Range, Content-Type, Accept, Origin",
            "Access-Control-Max-Age": "86400"
        }
    )


async def stream_handler(request: web.Request):
    """Handle video streaming requests with HTTP 206 Range seeking."""
    if not Config.ENABLE_STREAMING:
        return web.Response(text="Streaming is currently disabled by administrator.", status=503)

    param = request.match_info.get("file_unique_id")
    file_doc = await resolve_file_from_param(param)
    if not file_doc:
        return web.Response(text="File not found in database", status=404)

    # Stremio VIP Token validation & 1-IP Concurrency check
    stremio_token = request.query.get("token")
    if stremio_token and stremio_token.startswith("ak_"):
        from database.stremio import verify_stremio_access
        client_ip = get_client_ip(request)
        is_ok, reason, _ = await verify_stremio_access(stremio_token, client_ip=client_ip)
        if not is_ok:
            return web.Response(text=f"Streaming Access Denied: {reason}", status=403)

    file_size = int(file_doc.get("file_size", 0))
    file_name = file_doc.get("file_name", "video.mp4")
    mime_type = file_doc.get("mime_type") or mimetypes.guess_type(file_name)[0] or "video/mp4"

    client = Config.MASTER_CLIENT
    if not client:
        return web.Response(text="Telegram bot client is not initialized", status=503)

    range_header = request.headers.get("Range")
    logger.info(f"⚡ Streaming [{param}] - File: {file_name} - Range: {range_header or 'Full'} - Size: {file_size}")

    try:
        byte_range, is_partial = parse_range(range_header, file_size)
    except RangeNotSatisfiable:
        return web.Response(
            status=416,
            headers={"Content-Range": f"bytes */{file_size}"}
        )

    clean_name = re.sub(r'[^\w\-_\. ]', '_', file_name).strip() or "video.mp4"
    quoted_clean = urllib.parse.quote(clean_name)
    is_download = (
        request.query.get("download") in ("1", "true") or
        request.query.get("dl") in ("1", "true") or
        "/download/" in request.path
    )
    if is_download:
        global_dl_enabled = await is_web_download_enabled()
        if not global_dl_enabled:
            dl_token = request.query.get("token") or ""
            is_valid_token, token_user_id = verify_vip_stream_token(dl_token)
            is_vip = False
            if is_valid_token and token_user_id:
                from database.users import is_premium
                is_vip = await is_premium(token_user_id) or Config.is_admin(token_user_id)
            if not is_vip:
                bot_uname = Config.BOT_USERNAME or "bot"
                f_uid = file_doc.get("file_unique_id") or str(file_doc.get("_id"))
                raise web.HTTPFound(f"https://t.me/{bot_uname}?start=file_{f_uid}")

    disposition_type = "attachment" if is_download else "inline"

    # Set accurate MIME type for video containers so external players (VLC, MX) initialize correct demuxers
    lower_name = file_name.lower()
    if lower_name.endswith(".mkv"):
        stream_mime = "video/x-matroska"
    elif lower_name.endswith(".webm"):
        stream_mime = "video/webm"
    elif lower_name.endswith(".mp4"):
        stream_mime = "video/mp4"
    elif not is_download and (mime_type.startswith("video/") or mime_type == "application/octet-stream"):
        stream_mime = "video/mp4"
    else:
        stream_mime = mime_type

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": stream_mime,
        "Content-Disposition": f'{disposition_type}; filename="{clean_name}"; filename*=UTF-8\'\'{quoted_clean}',
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "Range, Content-Type, Accept, Origin",
        "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
        "Connection": "keep-alive"
    }

    if is_partial:
        status = 206
        headers["Content-Range"] = f"bytes {byte_range.start}-{byte_range.end}/{byte_range.total}"
        headers["Content-Length"] = str(byte_range.length)
    else:
        status = 200
        headers["Content-Length"] = str(file_size)

    if request.method == "HEAD":
        return web.Response(status=status, headers=headers)

    try:
        # 512KB chunks: fast initial response for VLC/MX Player and lean memory footprint (<200MB) on Koyeb
        chunk_size = 512 * 1024
        body_gen = TGCustomStreamer.yield_file_range(client, file_doc, byte_range, chunk_size=chunk_size)
        return web.Response(status=status, body=body_gen, headers=headers)
    except ServerBusyError:
        return web.Response(
            status=503,
            text="Server streaming capacity is currently full. Please try again shortly or download the file directly."
        )
    except Exception as e:
        logger.error(f"Error handling stream for {param}: {e}", exc_info=True)
        return web.Response(status=500, text="Internal streaming error")


async def get_web_sponsor_banner_html() -> str:
    """Build unified, high-CTR responsive sponsor banner for all web pages (Sweet Spot ~44px)."""
    try:
        from database.ads import get_active_sponsor_ad
        ad = await get_active_sponsor_ad()
        if ad and ad.get("text") and ad.get("url"):
            return (
                f'<a href="{html_escape(ad["url"])}" target="_blank" rel="noopener noreferrer" class="sponsor-banner-bar">'
                f'<div style="display:flex;align-items:center;overflow:hidden;flex:1;">'
                f'<span class="sponsor-tag">🔥 SPONSOR</span>'
                f'<span class="sponsor-text">{html_escape(ad["text"])}</span>'
                f'</div>'
                f'<span class="sponsor-arrow">↗</span>'
                f'</a>'
            )
    except Exception as e:
        logger.debug(f"Could not load web sponsor banner: {e}")
    return ""


async def watch_handler(request: web.Request):
    """Serve responsive custom Artplayer cinema web page with multi-audio controls and related movies."""
    param = request.match_info.get("file_unique_id")
    file_doc = await resolve_file_from_param(param)
    if not file_doc:
        return web.Response(text="File not found in database", status=404)

    base_url = get_stream_base_url(request)
    browse_url = f"{base_url}/browse"
    file_unique_id = file_doc.get("file_unique_id") or str(file_doc.get("_id"))
    file_name = file_doc.get("file_name", "Movie Video.mp4")
    file_size = int(file_doc.get("file_size", 0))
    size_str = get_readable_size(file_size)

    meta = parse_media_metadata(file_name)
    clean_title = meta.get("title") or file_name
    quality = meta.get("quality")
    badges = meta.get("badges", [])
    is_dual = meta.get("is_dual_audio", False)
    is_multi = meta.get("is_multi_audio", False)
    is_dual_audio_js = "true" if (is_dual or is_multi) else "false"

    badges_list = [f'<span class="badge badge-cyan">📦 {size_str}</span>']
    if quality:
        badges_list.append(f'<span class="badge badge-purple">🎬 {html_escape(quality)}</span>')
    for b in badges:
        if b != quality and b != size_str:
            if any(k in b for k in ("Audio", "Hindi", "English", "Dolby")):
                badges_list.append(f'<span class="badge badge-green">🎧 {html_escape(b)}</span>')
            else:
                badges_list.append(f'<span class="badge">⚡ {html_escape(b)}</span>')
    if not any("Stream" in b for b in badges_list):
        badges_list.append('<span class="badge">⚡ Direct Stream</span>')

    badges_html = "\n                ".join(badges_list)

    clean_name = re.sub(r'[^\w\-_\. ]', '_', file_name).strip() or "video.mp4"
    quoted_clean = urllib.parse.quote(clean_name)
    stream_url = f"{base_url}/stream/{file_unique_id}/{quoted_clean}"
    
    token = request.query.get("token") or ""
    is_valid_token, token_user_id = verify_vip_stream_token(token)
    is_vip_user = False
    if is_valid_token and token_user_id:
        from database.users import is_premium
        is_vip_user = await is_premium(token_user_id) or Config.is_admin(token_user_id)

    enable_web_dl = await is_web_download_enabled()
    allow_direct_dl = enable_web_dl or is_vip_user
    token_param = f"&token={token}" if (token and is_vip_user) else ""

    bot_uname = Config.BOT_USERNAME or "bot"
    if allow_direct_dl:
        download_url = f"{stream_url}?download=1{token_param}"
        download_text = "📥 Fast Download (VIP 👑)" if is_vip_user else "📥 Fast Download"
        download_attr = 'type="button"'
        download_button_html = f'<button type="button" onclick="openVipDownloadModal()" class="btn btn-dl" id="btn-vip-dl">{download_text}</button>'
    else:
        download_url = f"https://t.me/{bot_uname}?start=file_{file_unique_id}"
        download_text = "✈️ Download in Bot (Free)"
        download_attr = 'target="_blank"'
        download_button_html = f'<a href="{download_url}" target="_blank" class="btn btn-dl" onclick="handleFreeDownload(event)">{download_text}</a>'
        
    m3u_url = f"{base_url}/playlist/{file_unique_id}.m3u"

    clean_url = re.sub(r'^https?://', '', stream_url)
    protocol = "https" if stream_url.startswith("https") else "http"
    safe_title = urllib.parse.quote(clean_name)

    chooser_intent = f"intent://{clean_url}#Intent;action=android.intent.action.VIEW;scheme={protocol};type=video/*;S.title={safe_title};end"
    mx_intent = f"intent://{clean_url}#Intent;action=android.intent.action.VIEW;scheme={protocol};type=video/*;package=com.mxtech.videoplayer.ad;S.title={safe_title};end"
    vlc_intent = f"intent://{clean_url}#Intent;action=android.intent.action.VIEW;scheme={protocol};type=video/*;package=org.videolan.vlc;S.title={safe_title};end"

    channel_url = getattr(Config, "CHANNEL_URL", None) or "https://t.me/AkMovieVerse"

    catalog = await get_grouped_catalog()
    curr_clean_norm = re.sub(r"[^\w]", "", (meta.get("clean_name") or "").lower())

    related_cards_html = ""

    series_btn_html = ""
    episodes_carousel_html = ""
    quality_selector_html = ""
    movie_parts_html = ""
    next_ep_btn_html = ""
    next_ep_url = ""
    next_ep_num = 0
    next_ep_title = ""
    current_ep_num = meta.get("episode") or 0
    episodes_json = []
    artplayer_quality_json = []

    if meta.get("is_series"):
        clean_base = meta.get("clean_name") or ""
        s_num = meta.get("season") or 1
        series_slug = re.sub(r"[^\w\-]", "-", f"{clean_base} Season {s_num}".lower()).strip("-")
        series_slug = re.sub(r"-+", "-", series_slug)

        series_item = None
        for item in catalog:
            if item.get("is_series") and (item.get("slug") == series_slug or item.get("clean_name", "").lower() == clean_base.lower() or series_slug in item.get("aliases", [])):
                series_item = item
                break
            for f in item.get("files", []):
                if f.get("file_unique_id") == file_unique_id or str(f.get("_id")) == file_unique_id:
                    series_item = item
                    break
            if series_item:
                break

        if series_item:
            series_slug = series_item.get("slug") or series_slug
            clean_base = series_item.get("clean_name") or clean_base

        series_btn_html = f'<a href="/series/{series_slug}" class="btn btn-chooser" style="background: linear-gradient(135deg, #0284c7, #2563eb); grid-column: 1 / -1;">📺 View All Episodes & Packs ({html_escape(clean_base)}) ↗️</a>'

        if series_item and series_item.get("episodes_map"):
            sorted_eps = sorted(series_item["episodes_map"].keys())
            curr_qual = meta.get("quality")
            curr_ep = meta.get("episode")

            # 1. Episode Quality Selector (when current episode has multiple quality prints)
            if curr_ep is not None and curr_ep in series_item["episodes_map"]:
                curr_ep_files = series_item["episodes_map"][curr_ep]
                if len(curr_ep_files) > 1:
                    qual_rank = {"4k": 6, "2160p": 6, "1080p": 5, "720p": 4, "540p": 3, "480p": 2, "360p": 1}
                    def ep_sort_key(f):
                        f_m = parse_media_metadata(f.get("file_name", ""))
                        q = (f_m.get("quality") or "").lower()
                        return (qual_rank.get(q, 0), int(f.get("file_size", 0)))

                    sorted_ep_files = sorted(curr_ep_files, key=ep_sort_key, reverse=True)

                    ep_qual_pills = []
                    for ef in sorted_ep_files:
                        ef_uid = ef.get("file_unique_id") or str(ef.get("_id"))
                        ef_name = ef.get("file_name", "")
                        ef_m = parse_media_metadata(ef_name)
                        ef_q = ef_m.get("quality") or "HD"
                        ef_sz = get_readable_size(int(ef.get("file_size", 0)))
                        ef_clean = re.sub(r'[^\w\-_\. ]', '_', ef_name).strip() or "video.mp4"
                        ef_stream_url = f"{base_url}/stream/{ef_uid}/{urllib.parse.quote(ef_clean)}"
                        is_act = (ef_uid == file_unique_id)

                        artplayer_quality_json.append({
                            "default": is_act,
                            "html": f"{ef_q} ({ef_sz})",
                            "url": ef_stream_url
                        })

                        if is_act:
                            ep_qual_pills.append(f'<span class="ep-qual-pill active">🟢 {html_escape(ef_q)} ({ef_sz}) • Playing</span>')
                        else:
                            ep_qual_pills.append(f'<a href="/watch/{ef_uid}" class="ep-qual-pill">▶ {html_escape(ef_q)} ({ef_sz})</a>')

                    quality_selector_html = f"""
                    <div class="ep-quality-bar">
                        <div class="ep-qual-left">
                            <span class="ep-qual-title">🎞️ Episode {curr_ep} Quality:</span>
                            <span class="prints-count-pill">{len(curr_ep_files)} Qualities Available</span>
                        </div>
                        <div class="ep-qual-pills">
                            {''.join(ep_qual_pills)}
                        </div>
                    </div>
                    """

            # 2. Next Episode Calculation & Autoplay
            if curr_ep is not None:
                candidates = [ep for ep in sorted_eps if ep > curr_ep]
                if candidates:
                    next_ep_num = candidates[0]
                    ep_files = series_item["episodes_map"][next_ep_num]
                    chosen_next = ep_files[0]
                    for f in ep_files:
                        f_m = parse_media_metadata(f.get("file_name", ""))
                        if f_m.get("quality") == curr_qual:
                            chosen_next = f
                            break
                    next_id = chosen_next.get("file_unique_id") or str(chosen_next.get("_id"))
                    next_ep_url = f"/watch/{next_id}?autoplay=1"
                    next_ep_title = f"Episode {next_ep_num} - {clean_base}"
                    next_ep_btn_html = f'<a href="{next_ep_url}" class="btn btn-next-ep">⏭ Next: Episode {next_ep_num} ▶</a>'

            # 3. Carousel & Settings JSON
            poster = await get_cached_poster_url(clean_base)
            poster_url = poster if isinstance(poster, str) and poster else ""
            ep_cards = []

            for ep in sorted_eps:
                files_list = series_item["episodes_map"][ep]
                chosen_f = files_list[0]
                for f in files_list:
                    f_m = parse_media_metadata(f.get("file_name", ""))
                    if f_m.get("quality") == curr_qual:
                        chosen_f = f
                        break
                f_uid = chosen_f.get("file_unique_id") or str(chosen_f.get("_id"))
                f_sz = get_readable_size(int(chosen_f.get("file_size", 0)))
                f_m = parse_media_metadata(chosen_f.get("file_name", ""))
                f_q = f_m.get("quality") or "HD"
                is_curr = (ep == curr_ep)

                episodes_json.append({
                    "ep": ep,
                    "url": f"/watch/{f_uid}?autoplay=1",
                    "is_current": is_curr
                })

                act_cls = "active-ep" if is_curr else ""
                tag_html = '<span class="ep-playing-tag">🟢 PLAYING</span>' if is_curr else f'<span class="ep-num-tag">EP {ep}</span>'
                play_icon = "❚❚" if is_curr else "▶"
                thumb_inner = f'<img src="{poster_url}" class="ep-thumb" alt="Episode {ep}" loading="lazy">' if poster_url else '<div class="ep-thumb-fallback">🎬</div>'

                ep_cards.append(f"""
                    <a href="/watch/{f_uid}?autoplay=1" class="netflix-ep-card {act_cls}">
                        <div class="ep-thumb-wrap">
                            {thumb_inner}
                            <div class="ep-thumb-overlay">
                                <span class="ep-play-icon">{play_icon}</span>
                            </div>
                            {tag_html}
                            <span class="ep-card-qual">{html_escape(f_q)}</span>
                        </div>
                        <div class="ep-card-meta">
                            <div class="ep-card-title">Episode {ep}</div>
                            <div class="ep-card-sub">{html_escape(f_sz)}</div>
                        </div>
                    </a>
                """)

            episodes_carousel_html = f"""
            <div class="netflix-episodes-section">
                <div class="netflix-episodes-header">
                    <div class="episodes-header-left">
                        <span class="episodes-icon">📺</span>
                        <span class="episodes-title">Season {s_num} Episodes</span>
                        <span class="episodes-count-pill">{len(sorted_eps)} Episodes</span>
                    </div>
                    <a href="/series/{series_slug}" class="episodes-view-all">Full Series Hub ➔</a>
                </div>
                <div class="netflix-episodes-row">
                    {''.join(ep_cards)}
                </div>
            </div>
            """
        elif series_item and series_item.get("combined_files"):
            packs_list = series_item["combined_files"]
            curr_qual = meta.get("quality")
            curr_start = meta.get("start_ep")
            curr_end = meta.get("end_ep")

            # Find index of current pack in sorted packs_list
            curr_idx = -1
            for idx, p in enumerate(packs_list):
                if (p.get("file_unique_id") == file_unique_id or str(p.get("_id")) == file_unique_id):
                    curr_idx = idx
                    break

            # 1. Pack Quality Switcher (when multiple qualities exist for this exact pack range)
            if curr_start is not None and curr_end is not None:
                same_range_packs = [
                    p for p in packs_list
                    if parse_media_metadata(p.get("file_name", "")).get("start_ep") == curr_start and
                       parse_media_metadata(p.get("file_name", "")).get("end_ep") == curr_end
                ]
                if len(same_range_packs) > 1:
                    qual_rank = {"4k": 6, "2160p": 6, "1080p": 5, "720p": 4, "540p": 3, "480p": 2, "360p": 1}
                    same_range_packs.sort(
                        key=lambda f: (qual_rank.get((parse_media_metadata(f.get("file_name", "")).get("quality") or "").lower(), 0), int(f.get("file_size", 0))),
                        reverse=True
                    )
                    pack_qual_pills = []
                    for pf in same_range_packs:
                        pf_uid = pf.get("file_unique_id") or str(pf.get("_id"))
                        pf_name = pf.get("file_name", "")
                        pf_m = parse_media_metadata(pf_name)
                        pf_q = pf_m.get("quality") or "HD"
                        pf_sz = get_readable_size(int(pf.get("file_size", 0)))
                        pf_clean = re.sub(r'[^\w\-_\. ]', '_', pf_name).strip() or "video.mp4"
                        pf_stream_url = f"{base_url}/stream/{pf_uid}/{urllib.parse.quote(pf_clean)}"
                        is_act = (pf_uid == file_unique_id)

                        artplayer_quality_json.append({
                            "default": is_act,
                            "html": f"{pf_q} ({pf_sz})",
                            "url": pf_stream_url
                        })

                        if is_act:
                            pack_qual_pills.append(f'<span class="ep-qual-pill active">🟢 {html_escape(pf_q)} ({pf_sz}) • Playing</span>')
                        else:
                            pack_qual_pills.append(f'<a href="/watch/{pf_uid}" class="ep-qual-pill">▶ {html_escape(pf_q)} ({pf_sz})</a>')

                    range_lbl = f"Ep {curr_start:02d}–{curr_end:02d}"
                    quality_selector_html = f"""
                    <div class="ep-quality-bar">
                        <div class="ep-qual-left">
                            <span class="ep-qual-title">🎞️ {range_lbl} Quality:</span>
                            <span class="prints-count-pill">{len(same_range_packs)} Qualities Available</span>
                        </div>
                        <div class="ep-qual-pills">
                            {''.join(pack_qual_pills)}
                        </div>
                    </div>
                    """

            # 2. Next Pack Button & Autoplay
            if curr_idx != -1 and curr_idx + 1 < len(packs_list):
                next_pack = packs_list[curr_idx + 1]
                next_id = next_pack.get("file_unique_id") or str(next_pack.get("_id"))
                next_m = parse_media_metadata(next_pack.get("file_name", ""))
                if next_m.get("start_ep") and next_m.get("end_ep"):
                    next_pack_lbl = f"Ep {next_m['start_ep']:02d}–{next_m['end_ep']:02d}"
                else:
                    next_pack_lbl = f"Pack {curr_idx + 2}"
                next_ep_url = f"/watch/{next_id}?autoplay=1"
                next_ep_title = f"{next_pack_lbl} - {clean_base}"
                next_ep_btn_html = f'<a href="{next_ep_url}" class="btn btn-next-ep">⏭ Next: {next_pack_lbl} ▶</a>'

            # 3. Packs Carousel under the player
            poster = await get_cached_poster_url(clean_base)
            poster_url = poster if isinstance(poster, str) and poster else ""
            pack_cards = []

            for p_i, pf in enumerate(packs_list):
                pf_uid = pf.get("file_unique_id") or str(pf.get("_id"))
                pf_sz = get_readable_size(int(pf.get("file_size", 0)))
                pf_m = parse_media_metadata(pf.get("file_name", ""))
                pf_q = pf_m.get("quality") or "HD"
                is_curr = (pf_uid == file_unique_id)
                if pf_m.get("start_ep") and pf_m.get("end_ep"):
                    p_title = f"Ep {pf_m['start_ep']:02d}–{pf_m['end_ep']:02d}"
                else:
                    p_title = f"Pack {p_i + 1}"

                episodes_json.append({
                    "ep": p_i + 1,
                    "url": f"/watch/{pf_uid}?autoplay=1",
                    "is_current": is_curr
                })

                act_cls = "active-ep" if is_curr else ""
                tag_html = '<span class="ep-playing-tag">🟢 PLAYING</span>' if is_curr else f'<span class="ep-num-tag">PACK {p_i+1}</span>'
                play_icon = "❚❚" if is_curr else "▶"
                thumb_inner = f'<img src="{poster_url}" class="ep-thumb" alt="{p_title}" loading="lazy">' if poster_url else '<div class="ep-thumb-fallback">📦</div>'

                pack_cards.append(f"""
                    <a href="/watch/{pf_uid}?autoplay=1" class="netflix-ep-card {act_cls}">
                        <div class="ep-thumb-wrap">
                            {thumb_inner}
                            <div class="ep-thumb-overlay">
                                <span class="ep-play-icon">{play_icon}</span>
                            </div>
                            {tag_html}
                            <span class="ep-card-qual">{html_escape(pf_q)}</span>
                        </div>
                        <div class="ep-card-meta">
                            <div class="ep-card-title">{p_title}</div>
                            <div class="ep-card-sub">{html_escape(pf_sz)}</div>
                        </div>
                    </a>
                """)

            episodes_carousel_html = f"""
            <div class="netflix-episodes-section">
                <div class="netflix-episodes-header">
                    <div class="episodes-header-left">
                        <span class="episodes-icon">📦</span>
                        <span class="episodes-title">Season {s_num} Combined Packs</span>
                        <span class="episodes-count-pill">{len(packs_list)} Packs</span>
                    </div>
                    <a href="/series/{series_slug}" class="episodes-view-all">Full Series Hub ➔</a>
                </div>
                <div class="netflix-episodes-row">
                    {''.join(pack_cards)}
                </div>
            </div>
            """
    else:
        # Movie Quality, Multi-Part, and Prints Switcher
        movie_prints = []
        for item in catalog:
            if not item.get("is_series"):
                for f in item.get("files", []):
                    if (f.get("file_unique_id") == file_unique_id or str(f.get("_id")) == file_unique_id):
                        movie_prints = item.get("files", [])
                        break
                if movie_prints:
                    break

        # Fallback to single file_doc if item has no prints list
        if not movie_prints and file_doc:
            movie_prints = [file_doc]

        # 1. Detect Multi-Part Movie (Part 1, Part 2, etc.)
        parts_map = {}
        for pf in movie_prints:
            pf_m = parse_media_metadata(pf.get("file_name", ""))
            p_num = pf_m.get("part") if pf_m.get("is_part") else 1
            parts_map.setdefault(p_num, []).append(pf)

        curr_part = meta.get("part") or 1

        if len(parts_map) > 1:
            sorted_parts = sorted(parts_map.keys())
            part_pills = []
            for p in sorted_parts:
                p_files = parts_map[p]
                # Pick file matching current quality if available
                p_chosen = p_files[0]
                for f in p_files:
                    if parse_media_metadata(f.get("file_name", "")).get("quality") == meta.get("quality"):
                        p_chosen = f
                        break
                p_uid = p_chosen.get("file_unique_id") or str(p_chosen.get("_id"))
                p_sz = get_readable_size(int(p_chosen.get("file_size", 0)))
                is_act = (p == curr_part)
                p_label = f"Part {p}"

                if is_act:
                    part_pills.append(f'<span class="movie-part-pill active">🟢 {p_label} ({p_sz}) • Playing</span>')
                else:
                    part_pills.append(f'<a href="/watch/{p_uid}" class="movie-part-pill">▶ {p_label} ({p_sz})</a>')

            movie_parts_html = f"""
            <div class="movie-parts-bar">
                <div class="movie-parts-left">
                    <span class="movie-parts-title">🧩 Movie Parts:</span>
                    <span class="prints-count-pill">{len(sorted_parts)} Parts</span>
                </div>
                <div class="movie-parts-pills">
                    {''.join(part_pills)}
                </div>
            </div>
            """

            # Next Part Autoplay & Button
            next_part_num = curr_part + 1
            if next_part_num in parts_map:
                next_part_files = parts_map[next_part_num]
                next_chosen = next_part_files[0]
                for f in next_part_files:
                    if parse_media_metadata(f.get("file_name", "")).get("quality") == meta.get("quality"):
                        next_chosen = f
                        break
                next_id = next_chosen.get("file_unique_id") or str(next_chosen.get("_id"))
                next_ep_url = f"/watch/{next_id}?autoplay=1"
                next_ep_num = next_part_num
                next_ep_title = f"Part {next_part_num} - {clean_title}"
                next_ep_btn_html = f'<a href="{next_ep_url}" class="btn btn-next-ep">⏭ Next: Part {next_part_num} ▶</a>'

            # Relevant prints to display in quality selector: ONLY for current part!
            relevant_prints = parts_map.get(curr_part, movie_prints)
        else:
            relevant_prints = movie_prints

        # 2. Quality / Print Switcher for current part or full movie
        if len(relevant_prints) > 1:
            qual_rank = {"4k": 6, "2160p": 6, "1080p": 5, "720p": 4, "540p": 3, "480p": 2, "360p": 1}
            def sort_key(f):
                f_m = parse_media_metadata(f.get("file_name", ""))
                q = (f_m.get("quality") or "").lower()
                r = qual_rank.get(q, 0)
                sz = int(f.get("file_size", 0))
                return (r, sz)

            sorted_prints = sorted(relevant_prints, key=sort_key, reverse=True)

            qual_counts = {}
            aud_counts = {}
            for f in sorted_prints:
                pf_name_val = f.get("file_name", "")
                f_m = parse_media_metadata(pf_name_val)
                q_cat = (f_m.get("quality") or "Other").upper()
                qual_counts[q_cat] = qual_counts.get(q_cat, 0) + 1

                pfn_l = pf_name_val.lower()
                if "multi" in pfn_l or f_m.get("is_multi_audio"):
                    aud_counts["Multi Audio"] = aud_counts.get("Multi Audio", 0) + 1
                elif "dual" in pfn_l or f_m.get("is_dual_audio"):
                    aud_counts["Dual Audio"] = aud_counts.get("Dual Audio", 0) + 1
                elif any(k in pfn_l for k in ("hindi", "hin")):
                    aud_counts["Hindi"] = aud_counts.get("Hindi", 0) + 1
                elif any(k in pfn_l for k in ("english", "eng")):
                    aud_counts["English"] = aud_counts.get("English", 0) + 1
                elif any(k in pfn_l for k in ("tamil", "tam")):
                    aud_counts["Tamil"] = aud_counts.get("Tamil", 0) + 1
                elif any(k in pfn_l for k in ("telugu", "tel")):
                    aud_counts["Telugu"] = aud_counts.get("Telugu", 0) + 1

            filter_tabs = [f'<button type="button" onclick="filterPrints(\'all\', this)" class="print-filter-btn active">All ({len(sorted_prints)})</button>']
            # Audio Language Filter Tabs
            for aud_name in ["Hindi", "Dual Audio", "Multi Audio", "English", "Tamil", "Telugu"]:
                if aud_name in aud_counts:
                    aud_slug = aud_name.lower().replace(" ", "")
                    filter_tabs.append(f'<button type="button" onclick="filterPrints(\'{aud_slug}\', this)" class="print-filter-btn audio-btn">🎧 {aud_name} ({aud_counts[aud_name]})</button>')
            # Resolution Filter Tabs
            for q_order in ["4K", "2160P", "1080P", "720P", "540P", "480P"]:
                if q_order in qual_counts:
                    filter_tabs.append(f'<button type="button" onclick="filterPrints(\'{q_order.lower()}\', this)" class="print-filter-btn">{q_order} ({qual_counts[q_order]})</button>')
            for q_k, q_v in qual_counts.items():
                if q_k not in ["4K", "2160P", "1080P", "720P", "540P", "480P", "OTHER"]:
                    filter_tabs.append(f'<button type="button" onclick="filterPrints(\'{q_k.lower()}\', this)" class="print-filter-btn">{q_k} ({q_v})</button>')
            if "OTHER" in qual_counts:
                filter_tabs.append(f'<button type="button" onclick="filterPrints(\'other\', this)" class="print-filter-btn">Other ({qual_counts["OTHER"]})</button>')

            filter_tabs_html = "\n".join(filter_tabs)

            print_cards = []
            for pf in sorted_prints:
                pf_uid = pf.get("file_unique_id") or str(pf.get("_id"))
                pf_name = pf.get("file_name", "")
                pf_sz = get_readable_size(int(pf.get("file_size", 0)))
                pf_m = parse_media_metadata(pf_name)
                pf_q = pf_m.get("quality") or "HD"
                pf_q_cat = pf_q.lower()

                badges_pills = [f'<span class="print-badge pbadge-res">{html_escape(pf_q)}</span>']

                codecs = [b for b in pf_m.get("badges", []) if b in ("HEVC", "10bit", "x265", "x264", "AV1")]
                if codecs:
                    badges_pills.append(f'<span class="print-badge pbadge-codec">{html_escape(codecs[0])}</span>')

                audio_tags = [b for b in pf_m.get("badges", []) if any(k in b for k in ("Audio", "Hindi", "English", "Dolby", "5.1", "Tamil", "Telugu"))]
                if audio_tags:
                    badges_pills.append(f'<span class="print-badge pbadge-audio">{html_escape(audio_tags[0])}</span>')
                elif pf_m.get("is_dual_audio"):
                    badges_pills.append('<span class="print-badge pbadge-audio">Dual Audio</span>')

                source_tags = [b for b in pf_m.get("badges", []) if b in ("WEB-DL", "WEBRip", "HDRip", "BluRay")]
                if source_tags:
                    badges_pills.append(f'<span class="print-badge pbadge-codec">{html_escape(source_tags[0])}</span>')

                is_active = (pf_uid == file_unique_id)
                active_class = "is-active-print" if is_active else ""

                if allow_direct_dl:
                    p_dl_url = f"/download/{pf_uid}?token={token}" if (token and is_vip_user) else f"/download/{pf_uid}"
                    p_dl_target = ""
                else:
                    p_dl_url = f"https://t.me/{Config.BOT_USERNAME or 'bot'}?start=file_{pf_uid}"
                    p_dl_target = 'target="_blank"'

                if is_active:
                    play_action_html = '<div class="print-play-btn now-playing">🟢 Now Playing</div>'
                else:
                    play_action_html = f'<a href="/watch/{pf_uid}?autoplay=1{token_param}" class="print-play-btn">▶ Play Quality</a>'

                pf_clean = re.sub(r'[^\w\-_\. ]', '_', pf_name).strip() or "video.mp4"
                pf_stream_url = f"{base_url}/stream/{pf_uid}/{urllib.parse.quote(pf_clean)}"

                pf_lower = pf_name.lower()
                aud_lbl = ""
                aud_slug = ""
                if "multi" in pf_lower or pf_m.get("is_multi_audio"):
                    aud_lbl = "Multi"
                    aud_slug = "multiaudio multi"
                elif "dual" in pf_lower or pf_m.get("is_dual_audio"):
                    aud_lbl = "Dual"
                    aud_slug = "dualaudio dual"
                elif any(k in pf_lower for k in ("hindi", "hin")):
                    aud_lbl = "Hindi"
                    aud_slug = "hindi"
                elif any(k in pf_lower for k in ("english", "eng")):
                    aud_lbl = "Eng"
                    aud_slug = "english"
                elif any(k in pf_lower for k in ("tamil", "tam")):
                    aud_lbl = "Tam"
                    aud_slug = "tamil"
                elif any(k in pf_lower for k in ("telugu", "tel")):
                    aud_lbl = "Tel"
                    aud_slug = "telugu"

                aud_suffix = f" • {aud_lbl}" if aud_lbl else ""
                artplayer_quality_json.append({
                    "default": is_active,
                    "html": f"{pf_q}{aud_suffix} ({pf_sz})".strip(),
                    "url": pf_stream_url
                })

                display_details = pf_name.replace("_", " ").replace(".", " ")
                clean_t = pf_m.get("clean_name") or ""
                if clean_t and clean_t.lower() in display_details.lower():
                    display_details = re.sub(re.escape(clean_t), "", display_details, flags=re.IGNORECASE).strip()
                display_details = re.sub(r'^\s*\(?\d{4}\)?\s*', '', display_details).strip()
                if not display_details or len(display_details) < 4:
                    display_details = pf_name

                print_cards.append(f"""
                    <div class="print-card {active_class}" data-quality="{html_escape(pf_q_cat)}" data-audio="{aud_slug}">
                        <div class="print-card-top">
                            <div class="min-w-0 flex-1">
                                <div class="print-card-title" title="{html_escape(pf_name)}">{html_escape(display_details)}</div>
                                <div class="print-card-badges">
                                    {''.join(badges_pills)}
                                </div>
                            </div>
                            <span class="pbadge-size">{html_escape(pf_sz)}</span>
                        </div>
                        <div class="print-card-actions">
                            {play_action_html}
                            <a href="{p_dl_url}" {p_dl_target} class="print-action-icon" title="Download">⬇️</a>
                            <a href="/player/vlc/{pf_uid}" class="print-action-icon" title="Play in VLC / MX Player">📱</a>
                        </div>
                    </div>
                """)

            curr_sz_str = get_readable_size(file_size)
            quality_selector_html = f"""
            <div class="movie-prints-section">
                <div class="prints-header">
                    <div class="prints-header-left">
                        <span class="prints-icon">🎞️</span>
                        <span class="prints-title">Choose Quality / Print</span>
                        <span class="prints-count-pill">{len(sorted_prints)} Prints Available</span>
                    </div>
                    <span class="prints-active-badge">Playing: {html_escape(quality or 'HD')} • {curr_sz_str}</span>
                </div>
                <div class="prints-filter-pills">
                    {filter_tabs_html}
                </div>
                <div class="prints-grid">
                    {''.join(print_cards)}
                </div>
            </div>
            """

    sponsor_banner_html = await get_web_sponsor_banner_html()

    dual_audio_banner_html = ""
    if is_dual or is_multi:
        dual_audio_banner_html = f"""
        <div class="dual-audio-banner">
            <div class="dab-left">
                <span class="dab-icon">🎧</span>
                <div class="dab-text">
                    <strong>Dual / Multi Audio Available</strong>
                    <span>Embedded Hindi + English audio tracks detected. If browser plays English, tap below or choose a Hindi print:</span>
                </div>
            </div>
            <div class="dab-actions">
                <a href="{vlc_intent}" class="dab-btn vlc">🧡 VLC Player</a>
                <a href="{mx_intent}" class="dab-btn mx">🍿 MX Player</a>
            </div>
        </div>
        """

    html = WEB_PLAYER_HTML.format(
        dual_audio_banner_html=dual_audio_banner_html,
        is_dual_audio_js=is_dual_audio_js,
        file_unique_id=file_unique_id,
        clean_title=html_escape(clean_title),
        raw_filename=html_escape(file_name),
        badges_html=badges_html,
        stream_url=stream_url,
        download_url=download_url,
        download_text=download_text,
        download_attr=download_attr,
        download_button_html=download_button_html,
        file_size_str=size_str,
        m3u_url=m3u_url,
        chooser_intent=chooser_intent,
        mx_intent=mx_intent,
        vlc_intent=vlc_intent,
        bot_username=Config.BOT_USERNAME or "bot",
        channel_url=channel_url,
        browse_url=browse_url,
        related_cards_html=related_cards_html,
        series_btn_html=series_btn_html,
        episodes_carousel_html=episodes_carousel_html,
        quality_selector_html=quality_selector_html,
        movie_parts_html=movie_parts_html,
        next_ep_btn_html=next_ep_btn_html,
        next_ep_url=next_ep_url,
        next_ep_num=next_ep_num,
        next_ep_title=html_escape(next_ep_title),
        current_ep_num=current_ep_num,
        episodes_json_str=json.dumps(episodes_json),
        artplayer_quality_json_str=json.dumps(artplayer_quality_json),
        sponsor_banner_html=sponsor_banner_html
    )
    return web.Response(text=html, content_type="text/html")


# In-memory cached catalog to keep response times < 20ms
_GROUPED_CATALOG_CACHE = {"timestamp": 0, "groups": []}
_CATALOG_CACHE_TTL = 300.0  # 5 minutes fresh in-memory cache

ANIME_KEYWORD_REGEX = re.compile(
    r"\b(anime|naruto|one[\s._-]*piece|bleach|dragon[\s._-]*ball|demon[\s._-]*slayer|jujutsu|"
    r"attack[\s._-]*on[\s._-]*titan|ghibli|pokemon|death[\s._-]*note|hero[\s._-]*academia|"
    r"solo[\s._-]*leveling|chainsaw|tokyo[\s._-]*ghoul|hunter[\s._-]*x[\s._-]*hunter|haikyuu|"
    r"beyblade|digimon|inuyasha|doraemon|shinchan|black[\s._-]*clover|steins[\s._-]*gate|"
    r"fullmetal|code[\s._-]*geass|vinland|sword[\s._-]*art|fate|evangelion|berserk|isekai)\b",
    re.IGNORECASE
)


def _group_file_docs(docs: list) -> list:
    """Group an arbitrary list of file documents into canonical Media Titles (Series & Movies)."""
    groups = {}
    current_time = datetime.datetime.utcnow()

    for d in docs:
        fname = d.get("file_name", "")
        caption = d.get("caption", "")
        meta = parse_media_metadata(fname, caption=caption)
        clean = meta.get("clean_name") or fname
        is_series = meta.get("is_series", False)
        s_num = meta.get("season")
        yr = meta.get("year")

        norm_key = re.sub(r"[^\w]", "", clean.lower())

        # Prevent generic/unnamed files and bare-code releases from hijacking the catalog into a giant single card or fake series
        if meta.get("is_bare_code") or not norm_key or norm_key in ["untitled", "movievideo", "video", "none", "clip", "mediaclip"]:
            fid = d.get("file_unique_id") or str(d.get("_id"))
            group_key = f"clip:{fid}"
            disp_title = clean or "Media Clip"
            is_series = False
        elif is_series:
            group_key = f"series:{norm_key}:s{s_num or 1}"
            disp_title = f"{clean} (Season {s_num or 1})"
        else:
            # Movie grouping: Merge with existing movie group if same normalized title and compatible year
            existing_movie_key = None
            for k, eg in groups.items():
                if not eg.get("is_series") and eg.get("clean_name") and re.sub(r"[^\w]", "", eg["clean_name"].lower()) == norm_key:
                    eg_yr = eg.get("year")
                    if not eg_yr or not yr or abs(eg_yr - yr) <= 1:
                        existing_movie_key = k
                        break

            if existing_movie_key:
                group_key = existing_movie_key
                g = groups[group_key]
                if not g.get("year") and yr:
                    g["year"] = yr
                    g["title"] = f"{g['clean_name']} ({yr})"
                    g["slug"] = re.sub(r"[^\w\-]", "-", g["title"].lower()).strip("-")
            else:
                yr_str = str(yr) if yr else ""
                group_key = f"movie:{norm_key}:{yr_str}"
                disp_title = f"{clean} ({yr})" if yr else clean

        gen_time = d.get("_id").generation_time if hasattr(d.get("_id"), "generation_time") else None
        if hasattr(gen_time, "replace"):
            gen_time = gen_time.replace(tzinfo=None)
        c_date = d.get("created_at") or gen_time
        if hasattr(c_date, "replace"):
            c_date = c_date.replace(tzinfo=None)

        if group_key not in groups:
            slug = re.sub(r"[^\w\-]", "-", disp_title.lower()).strip("-")
            slug = re.sub(r"-+", "-", slug)
            groups[group_key] = {
                "key": group_key,
                "slug": slug,
                "title": disp_title,
                "clean_name": clean,
                "is_series": is_series,
                "season": s_num or 1,
                "year": yr,
                "files": [],
                "qualities": set(),
                "languages": set(),
                "latest_date": c_date,
                "has_combined": False,
                "episodes_map": {},
                "combined_files": [],
                "parts_map": {},
                "has_parts": False,
                "total_size": 0,
                "primary_file_id": d.get("file_unique_id") or str(d.get("_id"))
            }

        g = groups[group_key]
        g["files"].append(d)
        g["total_size"] += int(d.get("file_size", 0))

        if meta.get("is_part"):
            p_val = meta.get("part") or 1
            g["parts_map"].setdefault(p_val, []).append(d)

        q = meta.get("quality")
        if q:
            g["qualities"].add(q)

        langs = meta.get("languages", [])
        if langs:
            g["languages"].update(langs)
        if meta.get("is_dual_audio"):
            g["languages"].add("Dual Audio")
        if meta.get("is_multi_audio"):
            g["languages"].add("Multi Audio")

        ep = meta.get("episode")
        is_comb = meta.get("is_combined", False)

        if is_comb or (is_series and ep is None):
            g["has_combined"] = True
            g["combined_files"].append(d)
        elif ep is not None:
            g["episodes_map"].setdefault(ep, []).append(d)

        if c_date and c_date > g["latest_date"]:
            g["latest_date"] = c_date
            g["primary_file_id"] = d.get("file_unique_id") or str(d.get("_id"))

    # Merge series groups that belong to the same franchise and season (e.g. "Akka" pack + "Akka The Protectors" episodes)
    series_keys = [k for k in list(groups.keys()) if groups[k]["is_series"]]
    to_delete = set()
    for i in range(len(series_keys)):
        k1 = series_keys[i]
        if k1 in to_delete or k1 not in groups:
            continue
        g1 = groups[k1]
        n1 = re.sub(r"[^\w]", "", g1["clean_name"].lower())

        for j in range(len(series_keys)):
            if i == j:
                continue
            k2 = series_keys[j]
            if k2 in to_delete or k2 not in groups:
                continue
            g2 = groups[k2]
            if g1.get("season") != g2.get("season"):
                continue
            n2 = re.sub(r"[^\w]", "", g2["clean_name"].lower())

            # SAFE GUARDS to prevent accidental merges of different shows (e.g. "Hostel" vs "Hostel Haadsa"):
            # 1. Do NOT merge if both groups have their own individual episodes (they are distinct shows)
            if g1["episodes_map"] and g2["episodes_map"]:
                continue

            # 2. At least one must be a complete pack (0 episodes) while the other has individual episodes
            is_pack_ep_pair = (
                (len(g1["episodes_map"]) == 0 and g1["has_combined"] and len(g2["episodes_map"]) > 0) or
                (len(g2["episodes_map"]) == 0 and g2["has_combined"] and len(g1["episodes_map"]) > 0)
            )
            if not is_pack_ep_pair:
                continue

            # 3. Check prefix match on word boundaries
            if len(n1) >= 3 and len(n2) >= 3 and (n2.startswith(n1) or n1.startswith(n2)):
                # Always prefer the SHORTER, cleaner, official title as canonical (e.g. "Akka" over "Akka The Protectors")
                if len(g1["clean_name"]) <= len(g2["clean_name"]):
                    target, source = g1, g2
                else:
                    target, source = g2, g1

                src_key = source["key"]
                target["files"].extend(source["files"])
                target["total_size"] += source["total_size"]
                target["combined_files"].extend(source["combined_files"])
                target["has_combined"] = bool(target["combined_files"])
                target["qualities"].update(source["qualities"])
                target["languages"].update(source["languages"])
                for ep, fl in source["episodes_map"].items():
                    target["episodes_map"].setdefault(ep, []).extend(fl)
                target["aliases"] = target.get("aliases", []) + [source["slug"], source["key"]]
                if source["latest_date"] and source["latest_date"] > target["latest_date"]:
                    target["latest_date"] = source["latest_date"]

                to_delete.add(src_key)
                break

    for k in to_delete:
        groups.pop(k, None)

    qual_order = {"2160p": 5, "1080p": 4, "720p": 3, "540p": 2, "480p": 1}
    for g in groups.values():
        diff = (current_time - g["latest_date"]).total_seconds() if g["latest_date"] else 999999
        new_window = getattr(Config, "STREAM_NEW_TAG_DAYS", 2) * 86400
        g["is_recent"] = (diff <= new_window)
        g["is_anime"] = bool(
            ANIME_KEYWORD_REGEX.search(g.get("clean_name", "")) or
            any(ANIME_KEYWORD_REGEX.search(f.get("file_name", "")) for f in g.get("files", []))
        )
        g["episodes_count"] = len(g["episodes_map"])
        g["languages_list"] = sorted(list(g["languages"]))
        g["sorted_qualities"] = sorted(
            list(g["qualities"]),
            key=lambda x: qual_order.get(x.lower(), 1),
            reverse=True
        )

        # Multi-part movies: ALWAYS guarantee primary_file_id is Part 1!
        g["has_parts"] = bool(g.get("parts_map") and len(g["parts_map"]) > 1)
        if g["has_parts"]:
            min_part = min(g["parts_map"].keys())
            part_files = g["parts_map"][min_part]
            part_files.sort(
                key=lambda x: qual_order.get((parse_media_metadata(x.get("file_name", "")).get("quality") or "").lower(), 1),
                reverse=True
            )
            g["primary_file_id"] = part_files[0].get("file_unique_id") or str(part_files[0].get("_id"))

        # Combined season packs: Sort chronologically by episode range (e.g. Ep 01-07, Ep 08-15...)
        if g.get("combined_files"):
            def pack_sort_key(f):
                f_meta = parse_media_metadata(f.get("file_name", ""))
                s_ep = f_meta.get("start_ep") or 0
                e_ep = f_meta.get("end_ep") or 9999
                q = (f_meta.get("quality") or "").lower()
                q_score = qual_order.get(q, 1)
                sz = int(f.get("file_size", 0))
                return (s_ep, e_ep, -q_score, -sz)

            g["combined_files"].sort(key=pack_sort_key)

            # If the series has NO individual episodes (pure combined packs like Hercai):
            # Guarantee primary_file_id is the FIRST pack (Ep 01-...) in highest quality!
            if not g.get("episodes_map") and g["combined_files"]:
                g["primary_file_id"] = g["combined_files"][0].get("file_unique_id") or str(g["combined_files"][0].get("_id"))

        # Individual episodes: Guarantee primary_file_id is Episode 1 in highest quality
        if g.get("episodes_map"):
            min_ep = min(g["episodes_map"].keys())
            ep_files = g["episodes_map"][min_ep]
            ep_files.sort(
                key=lambda x: qual_order.get((parse_media_metadata(x.get("file_name", "")).get("quality") or "").lower(), 1),
                reverse=True
            )
            g["primary_file_id"] = ep_files[0].get("file_unique_id") or str(ep_files[0].get("_id"))

    return sorted(groups.values(), key=lambda x: x["latest_date"] or datetime.datetime.min, reverse=True)


async def _preload_catalog_posters(items: list):
    """Background task to pre-warm in-memory & MongoDB poster cache for catalog items."""
    for it in items[:40]:
        t = it.get("clean_name")
        if t:
            try:
                await get_cached_poster_url(t, year=it.get("year"), is_series=it.get("is_series"))
            except Exception:
                pass
            await asyncio.sleep(0.05)


async def get_stream_catalog_settings() -> dict:
    """Retrieve dynamic streaming catalog filter settings from MongoDB with sensible defaults."""
    try:
        from database.mongo import get_bot_setting
        cutoff_id = await get_bot_setting("stream_catalog_cutoff_id", None)
        mode = await get_bot_setting("stream_catalog_mode", "auto")
        channels = await get_bot_setting("stream_catalog_channels", [])
        hide_bare = await get_bot_setting("stream_hide_bare_codes", True)
        is_paused = await get_bot_setting("stream_catalog_paused", False)
        return {
            "cutoff_id": cutoff_id,
            "mode": mode,
            "channels": channels,
            "hide_bare_codes": hide_bare,
            "is_paused": is_paused
        }
    except Exception as e:
        logger.debug(f"Error fetching stream catalog settings: {e}")
        return {"cutoff_id": None, "mode": "auto", "channels": [], "hide_bare_codes": True, "is_paused": False}


def clear_catalog_cache():
    """Bust in-memory grouped catalog cache so website reflects settings updates immediately."""
    _GROUPED_CATALOG_CACHE["groups"] = []
    _GROUPED_CATALOG_CACHE["timestamp"] = 0


async def get_grouped_catalog() -> list:
    """Scan files from MongoDB and group them into canonical Media Titles (Series, Movies & Anime)."""
    now = asyncio.get_event_loop().time()
    if _GROUPED_CATALOG_CACHE["groups"] and (now - _GROUPED_CATALOG_CACHE["timestamp"] < _CATALOG_CACHE_TTL):
        return _GROUPED_CATALOG_CACHE["groups"]

    fetch_limit = int(getattr(Config, 'STREAM_CATALOG_LIMIT', 25000))
    projection = {
        "file_name": 1,
        "file_size": 1,
        "file_unique_id": 1,
        "caption": 1,
        "created_at": 1,
        "channel_id": 1,
        "source": 1,
        "is_web_stream": 1
    }

    settings = await get_stream_catalog_settings()
    cutoff_id = settings.get("cutoff_id")
    mode = settings.get("mode", "auto")
    channels = settings.get("channels", [])

    if mode == "cleared":
        return []

    or_conditions = []

    # 1. Any file explicitly approved for web stream is ALWAYS included
    or_conditions.append({"is_web_stream": True})

    # 2. Whitelisted stream channels are ALWAYS included
    if channels:
        or_conditions.append({"channel_id": {"$in": channels}})

    # 3. Dynamic filter modes
    if mode == "auto":
        cond = {"source": "auto_index"}
        if cutoff_id:
            try:
                cond["_id"] = {"$gte": ObjectId(cutoff_id)}
            except Exception:
                pass
        or_conditions.append(cond)
    elif mode == "all":
        if cutoff_id:
            try:
                or_conditions.append({"_id": {"$gte": ObjectId(cutoff_id)}})
            except Exception:
                pass
        else:
            # All mode with no cutoff means entire database
            or_conditions = []

    base_query = {"$or": or_conditions} if or_conditions else {}

    try:
        anime_regex = (
            r"Anime|Naruto|One[\s._-]*Piece|Bleach|Dragon[\s._-]*Ball|Demon[\s._-]*Slayer|"
            r"Attack[\s._-]*on[\s._-]*Titan|Jujutsu|Tokyo[\s._-]*Ghoul|Hunter[\s._-]*x[\s._-]*Hunter|"
            r"Death[\s._-]*Note|Hero[\s._-]*Academia|Chainsaw|Solo[\s._-]*Leveling|Ghibli|Pokemon|"
            r"Beyblade|Digimon|Haikyuu|Black[\s._-]*Clover|Inuyasha|Doraemon|Shinchan"
        )
        anime_filter = {"file_name": {"$regex": anime_regex, "$options": "i"}}
        if base_query:
            anime_query = {"$and": [base_query, anime_filter]}
        else:
            anime_query = anime_filter

        if not mongo.has_secondary:
            t_recent = mongo.files.find(base_query, projection).sort("_id", -1).limit(fetch_limit).to_list(fetch_limit)
            t_anime = mongo.files.find(anime_query, projection).sort("_id", -1).limit(15000).to_list(15000)
            res_recent, res_anime = await asyncio.gather(t_recent, t_anime, return_exceptions=True)
            docs_recent = res_recent if isinstance(res_recent, list) else []
            docs_anime = res_anime if isinstance(res_anime, list) else []

            seen_ids = set()
            docs = []
            for d in docs_recent + docs_anime:
                did = str(d["_id"])
                if did not in seen_ids:
                    seen_ids.add(did)
                    docs.append(d)
        else:
            t1 = mongo.files.find(base_query, projection).sort("_id", -1).limit(fetch_limit).to_list(fetch_limit)
            t2 = mongo.files_secondary.find(base_query, projection).sort("_id", -1).limit(fetch_limit).to_list(fetch_limit)
            t_anime = mongo.files.find(anime_query, projection).sort("_id", -1).limit(15000).to_list(15000)
            res1, res2, res_anime = await asyncio.gather(t1, t2, t_anime, return_exceptions=True)
            docs1 = res1 if isinstance(res1, list) else []
            docs2 = res2 if isinstance(res2, list) else []
            docs_anime = res_anime if isinstance(res_anime, list) else []

            seen_ids = set()
            docs = []
            for d in docs1 + docs2 + docs_anime:
                did = str(d["_id"])
                if did not in seen_ids:
                    seen_ids.add(did)
                    docs.append(d)
            docs = sorted(docs, key=lambda d: d.get("created_at") or datetime.datetime.min, reverse=True)
    except Exception as e:
        logger.error(f"Error fetching catalog docs from MongoDB: {e}")
        docs = []

    sorted_catalog = _group_file_docs(docs)
    _GROUPED_CATALOG_CACHE["groups"] = sorted_catalog
    _GROUPED_CATALOG_CACHE["timestamp"] = now
    asyncio.create_task(_preload_catalog_posters(sorted_catalog))
    return sorted_catalog


async def post_handler(request: web.Request):
    """Serve responsive Netflix/EonMovies-style Media Post Page for both Movies and Web Series."""
    slug_or_id = request.match_info.get("item_slug", "").strip() or request.match_info.get("series_slug", "").strip()
    slug_or_id = urllib.parse.unquote(slug_or_id).strip()
    base_url = get_stream_base_url(request)
    browse_url = f"{base_url}/browse"
    channel_url = getattr(Config, "CHANNEL_URL", None) or "https://t.me/AkMovieVerse"
    bot_username = Config.BOT_USERNAME or "bot"

    catalog = await get_grouped_catalog()
    target_item = None
    for item in catalog:
        if item["slug"] == slug_or_id or item["key"] == slug_or_id or slug_or_id in item.get("aliases", []):
            target_item = item
            break
        for f in item["files"]:
            if (f.get("file_unique_id") == slug_or_id or str(f.get("_id")) == slug_or_id):
                target_item = item
                break
        if target_item:
            break

    # 3. Smart slug prefix or clean name fallback (guarded against short-name false positives like 'do' in 'doraemon')
    if not target_item and catalog:
        norm_s = re.sub(r"[^\w]", "", slug_or_id.lower())
        for item in catalog:
            item_clean = re.sub(r"[^\w]", "", item.get("clean_name", "").lower())
            item_slug_clean = re.sub(r"[^\w]", "", item.get("slug", "").lower())
            # Exact match (normalized)
            if norm_s and (norm_s == item_clean or norm_s == item_slug_clean):
                target_item = item
                break
            # Prefix match ONLY if both strings are substantial (>= 6 chars) and one strictly starts with the other
            if len(norm_s) >= 6 and len(item_clean) >= 6:
                if norm_s.startswith(item_clean) or item_clean.startswith(norm_s) or norm_s.startswith(item_slug_clean) or item_slug_clean.startswith(norm_s):
                    target_item = item
                    break

    # If still not found in grouped catalog, try direct mongo file lookup
    if not target_item:
        file_doc = await resolve_file_from_param(slug_or_id)
        if file_doc:
            target_item = {
                "key": f"single:{slug_or_id}",
                "slug": slug_or_id,
                "title": file_doc.get("file_name", "Movie Video"),
                "clean_name": parse_media_metadata(file_doc.get("file_name", "")).get("clean_name") or file_doc.get("file_name", "Movie Video"),
                "is_series": "season" in file_doc.get("file_name", "").lower(),
                "year": parse_media_metadata(file_doc.get("file_name", "")).get("year"),
                "files": [file_doc],
                "primary_file_id": file_doc.get("file_unique_id") or str(file_doc.get("_id")),
                "sorted_qualities": [parse_media_metadata(file_doc.get("file_name", "")).get("quality") or "HD"],
                "languages_list": ["Hindi Dubbed"],
                "episodes_map": {},
                "combined_files": [],
                "has_combined": False,
                "has_parts": False,
                "parts_map": {},
                "total_size": int(file_doc.get("file_size", 0))
            }

    # 4. Smart Direct Multi-Cluster MongoDB Title Search Fallback (Zero 404s for any movie/series across all 588k+ files)
    if not target_item:
        raw_slug_words = [w for w in re.split(r"[^\w]+", slug_or_id) if w and len(w) >= 2]
        ignored_tokens = {"season", "series", "episode", "episodes", "complete", "pack", "movie", "movies", "hindi", "english", "dual", "audio", "print", "prints", "part", "parts"}
        search_tokens = [w for w in raw_slug_words if w.lower() not in ignored_tokens and not w.isdigit()]
        if not search_tokens and raw_slug_words:
            search_tokens = [w for w in raw_slug_words if not w.isdigit()]

        if search_tokens:
            try:
                from database.files import get_search_results
                query_str = " ".join(search_tokens)
                direct_docs = await get_search_results(query_str, limit=60)
                if not direct_docs and len(search_tokens) >= 2:
                    direct_docs = await get_search_results(" ".join(search_tokens[:2]), limit=60)
                if not direct_docs and search_tokens:
                    direct_docs = await get_search_results(search_tokens[0], limit=40)

                if direct_docs:
                    grouped_matches = _group_file_docs(direct_docs)
                    if grouped_matches:
                        norm_slug = re.sub(r"[^\w]", "", slug_or_id.lower())
                        best_match = None
                        for gm in grouped_matches:
                            gm_norm = re.sub(r"[^\w]", "", gm.get("slug", "").lower())
                            gm_clean = re.sub(r"[^\w]", "", gm.get("clean_name", "").lower())
                            if norm_slug == gm_norm or norm_slug == gm_clean:
                                best_match = gm
                                break
                            if len(norm_slug) >= 6 and len(gm_clean) >= 6:
                                if norm_slug.startswith(gm_clean) or gm_clean.startswith(norm_slug):
                                    best_match = gm
                                    break
                        target_item = best_match or grouped_matches[0]
            except Exception as e:
                logger.error(f"Direct post_handler mongo search error for '{slug_or_id}': {e}")

    if not target_item:
        return web.Response(text="""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Not Found</title><script src="https://cdn.tailwindcss.com"></script></head><body class="bg-[#07090e] text-white flex flex-col items-center justify-center min-h-screen p-4 text-center" oncontextmenu="return false;" onselectstart="return false;" ondragstart="return false;"><div class="text-5xl mb-4">🔍</div><h1 class="text-2xl font-bold mb-2">Title Not Found</h1><p class="text-gray-400 mb-6">This media item was not found in the catalog.</p><a href="/browse" class="px-5 py-2.5 bg-red-600 rounded-xl text-white font-bold">Return to Browse Catalog</a></body></html>""", content_type="text/html", status=404)

    is_series = bool(target_item.get("is_series"))
    clean_title = target_item.get("clean_name") or target_item.get("title", "")
    item_year = target_item.get("year")

    # Fetch rich official TMDB metadata
    tmdb_meta = {}
    try:
        from plugins.channel_post import fetch_tmdb_post_metadata
        tmdb_meta = await fetch_tmdb_post_metadata(clean_title, year=item_year, is_series=is_series) or {}
    except Exception as tmdb_e:
        logger.debug(f"TMDB fetch error for post {clean_title}: {tmdb_e}")

    poster_url = tmdb_meta.get("poster_url") or await get_cached_poster_url(clean_title)
    if not poster_url:
        poster_url = getattr(Config, "START_PIC", "https://api.aniwallpaper.workers.dev/random")

    backdrop_url = tmdb_meta.get("backdrop_url") or poster_url
    rating_val = tmdb_meta.get("rating")
    rating_str = f"{rating_val}/10" if rating_val and float(rating_val) > 0 else ""

    overview_text = tmdb_meta.get("overview")
    if not overview_text:
        overview_text = f"Watch full HD stream and get direct download access for {target_item['title']}. Available in multiple resolutions with fast playback."

    # Extract source (WEB-DL, BluRay, HDRip, etc.)
    source_val = "WEB-DL"
    if target_item.get("files"):
        for f in target_item["files"]:
            fn = f.get("file_name", "")
            fmeta = parse_media_metadata(fn)
            if fmeta.get("source"):
                source_val = fmeta["source"]
                break

    # Build Badges exactly matching user's screenshot
    # Row 1: Date, Type, Source, Rating
    row1_badges = []
    rel_date = tmdb_meta.get("release_date") or (str(item_year) if item_year else "2026")
    row1_badges.append(f'<span class="badge-pill">📅 {html_escape(str(rel_date))}</span>')
    type_label = "🎬 Series" if is_series else "🎬 Movie"
    row1_badges.append(f'<span class="badge-pill">{type_label}</span>')
    row1_badges.append(f'<span class="badge-pill badge-source">★ {html_escape(source_val)}</span>')
    if rating_str:
        row1_badges.append(f'<span class="badge-pill badge-rating">⭐ {html_escape(rating_str)} IMDb</span>')
    row1_html = "\n".join(row1_badges)

    # Row 2: Qualities and Audio
    row2_badges = []
    qualities = target_item.get("sorted_qualities", [])
    if not qualities:
        qualities = ["HD"]
    for q in qualities[:4]:
        row2_badges.append(f'<span class="badge-pill badge-qual">🎬 {html_escape(q)}</span>')
    
    # Audio
    audio_label = "🔊 Multi Audio"
    if target_item.get("languages_list"):
        langs = target_item["languages_list"]
        if "Hindi" in langs:
            audio_label = "🔊 Hindi Dubbed" if len(langs) > 1 else "🔊 Hindi"
        elif "Dual Audio" in langs:
            audio_label = "🔊 Dual Audio"
        elif "Multi Audio" in langs:
            audio_label = "🔊 Multi Audio"
        else:
            audio_label = f"🔊 {' • '.join(langs[:2])}"
    row2_badges.append(f'<span class="badge-pill badge-audio">{html_escape(audio_label)}</span>')
    row2_html = "\n".join(row2_badges)

    # Row 3: Cast / Director
    cast_badges = []
    cast_info = tmdb_meta.get("cast") or tmdb_meta.get("director")
    if not cast_info and tmdb_meta.get("genres"):
        cast_info = " • ".join(tmdb_meta["genres"][:3])
    if cast_info:
        cast_badges.append(f'<span class="badge-pill badge-cast">👤 {html_escape(str(cast_info))}</span>')
    row3_html = "\n".join(cast_badges)

    # Search parameter for Telegram bot deep-link (100% Monetization & VIP protection!)
    clean_search_param = urllib.parse.quote(re.sub(r"[^\w\s]", "", clean_title).strip().replace(" ", "_")[:30])

    # Action buttons:
    primary_file_id = target_item.get("primary_file_id")

    # If series, pick first episode ID if available
    first_stream_id = primary_file_id
    if is_series and target_item.get("episodes_map"):
        min_ep = min(target_item["episodes_map"].keys())
        first_ep = target_item["episodes_map"][min_ep][0]
        first_stream_id = first_ep.get("file_unique_id") or str(first_ep.get("_id"))

    action_buttons_html = f'''
    <div class="flex flex-col sm:flex-row gap-3 w-full justify-center pt-2">
        <a href="/watch/{first_stream_id}" class="btn-play-primary py-3.5 px-7 rounded-xl font-bold text-sm sm:text-base text-white text-center flex items-center justify-center gap-2">
            <span>▶️</span> <span>Watch Online (Fast Stream)</span>
        </a>
        <a href="https://t.me/{bot_username}?start=search_{clean_search_param}" target="_blank" class="btn-bot-action py-3 px-6 rounded-xl font-semibold text-xs sm:text-sm text-center flex items-center justify-center gap-2">
            <span>🤖</span> <span>Get in Telegram Bot (VIP/Files)</span>
        </a>
        <a href="https://t.me/{bot_username}?start=plans" target="_blank" class="btn-vip-action py-3 px-5 rounded-xl font-semibold text-xs sm:text-sm text-center flex items-center justify-center gap-2">
            <span>💎</span> <span>Get Ad-Free VIP Pass</span>
        </a>
    </div>
    '''

    # Prints / Quality Selector or Episodes Grid
    prints_or_episodes_html = ""
    if is_series:
        # Episodes Grid
        ep_cards = []
        if target_item.get("episodes_map"):
            for ep_num in sorted(target_item["episodes_map"].keys()):
                ep_file_list = target_item["episodes_map"][ep_num]
                ep_file = ep_file_list[0]
                ep_id = ep_file.get("file_unique_id") or str(ep_file.get("_id"))
                ep_size = get_readable_size(int(ep_file.get("file_size", 0)))
                ep_meta = parse_media_metadata(ep_file.get("file_name", ""))
                ep_qual = ep_meta.get("quality") or "HD"
                ep_cards.append(f'''
                <div class="ep-card p-3.5 flex items-center justify-between gap-3">
                    <div class="flex items-center gap-2.5 min-w-0">
                        <span class="px-2.5 py-1 rounded-lg text-xs font-black bg-sky-500/20 text-sky-400 border border-sky-500/30">EP {ep_num}</span>
                        <div class="min-w-0">
                            <div class="text-xs sm:text-sm font-bold text-white truncate">{html_escape(clean_title)} - Ep {ep_num}</div>
                            <div class="text-[11px] text-gray-400 font-semibold">{ep_qual} • {ep_size}</div>
                        </div>
                    </div>
                    <a href="/watch/{ep_id}" class="px-3.5 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-bold text-xs transition flex items-center gap-1 shrink-0 shadow-md shadow-sky-600/30">
                        <span>▶</span> <span>Watch</span>
                    </a>
                </div>
                ''')
            prints_or_episodes_html = f'''
            <div class="w-full mt-6 space-y-3">
                <div class="flex items-center justify-between px-1">
                    <h2 class="text-base sm:text-lg font-bold text-sky-400 flex items-center gap-2">
                        <span>📺</span> <span>Episodes List ({len(target_item['episodes_map'])})</span>
                    </h2>
                    <span class="text-xs text-gray-400 font-medium">Click to stream any episode</span>
                </div>
                <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                    {"".join(ep_cards)}
                </div>
            </div>
            '''
    else:
        # Movie Prints Selector (if more than 1 file or multiple qualities or parts)
        if len(target_item.get("files", [])) > 1:
            print_cards = []
            qual_order_map = {"2160p": 5, "4k": 5, "1080p": 4, "720p": 3, "540p": 2, "480p": 1}

            def _sort_movie_file(f):
                fm = parse_media_metadata(f.get("file_name", ""))
                p_num = fm.get("part") or 0
                q_val = (fm.get("quality") or "").lower()
                q_score = qual_order_map.get(q_val, 1)
                sz = int(f.get("file_size", 0))
                return (p_num, -q_score, -sz)

            sorted_movie_files = sorted(target_item["files"], key=_sort_movie_file)

            for f in sorted_movie_files:
                fn = f.get("file_name", "Movie Print")
                fmeta = parse_media_metadata(fn)
                fq = fmeta.get("quality") or "HD"
                part_lbl = fmeta.get("part_label")
                card_badge = f"{part_lbl} • {fq}" if part_lbl else fq
                card_sub = f"{html_escape(clean_title)} ({part_lbl})" if part_lbl else html_escape(clean_title)
                fs = get_readable_size(int(f.get("file_size", 0)))
                fid = f.get("file_unique_id") or str(f.get("_id"))
                print_cards.append(f'''
                <a href="/watch/{fid}" class="print-card p-3.5 flex items-center justify-between gap-3 group">
                    <div class="flex items-center gap-2.5 min-w-0">
                        <span class="px-2.5 py-1 rounded-lg text-xs font-black bg-rose-500/20 text-rose-400 border border-rose-500/30">{html_escape(card_badge)}</span>
                        <div class="min-w-0">
                            <div class="text-xs sm:text-sm font-bold text-white group-hover:text-sky-300 transition truncate">{card_sub}</div>
                            <div class="text-[11px] text-gray-400 font-semibold">{fs} • {html_escape(source_val)}</div>
                        </div>
                    </div>
                    <span class="px-3.5 py-1.5 rounded-lg bg-white/10 group-hover:bg-red-600 text-white font-bold text-xs transition flex items-center gap-1 shrink-0">
                        <span>▶</span> <span>Stream</span>
                    </span>
                </a>
                ''')

            section_title = f"Available Parts & Qualities ({len(target_item['files'])})" if target_item.get("has_parts") else f"Available Prints & Qualities ({len(target_item['files'])})"
            prints_or_episodes_html = f'''
            <div class="w-full mt-6 space-y-3">
                <div class="flex items-center justify-between px-1">
                    <h2 class="text-base sm:text-lg font-bold text-amber-400 flex items-center gap-2">
                        <span>🎬</span> <span>{section_title}</span>
                    </h2>
                    <span class="text-xs text-gray-400 font-medium">Select your preferred video print</span>
                </div>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {"".join(print_cards)}
                </div>
            </div>
            '''

    sponsor_banner_html = await get_web_sponsor_banner_html()

    html = MEDIA_POST_HTML.format(
        sponsor_banner_html=sponsor_banner_html,
        post_title=html_escape(target_item["title"]),
        backdrop_url=html_escape(backdrop_url),
        poster_url=html_escape(poster_url),
        badges_row1_html=row1_html,
        badges_row2_html=row2_html,
        badges_row3_html=row3_html,
        overview_text=html_escape(overview_text),
        action_buttons_html=action_buttons_html,
        prints_or_episodes_html=prints_or_episodes_html,
        channel_url=html_escape(channel_url),
        bot_username=html_escape(bot_username),
        browse_url=browse_url
    )
    return web.Response(text=html, content_type="text/html")


async def series_handler(request: web.Request):
    """Alias for post_handler for backwards compatibility."""
    return await post_handler(request)


async def browse_handler(request: web.Request):
    """Serve responsive Netflix-style Web Cinema Catalog with live search and pagination."""
    base_url = get_stream_base_url(request)
    browse_url = f"{base_url}/browse"
    channel_url = getattr(Config, "CHANNEL_URL", None) or "https://t.me/AkMovieVerse"
    bot_username = Config.BOT_USERNAME or "bot"
    enable_web_dl = await is_web_download_enabled()

    query = request.query.get("q", "").strip()
    quality = request.query.get("quality", "").strip()
    filter_type = request.query.get("filter", "").strip().lower()

    try:
        page = max(1, int(request.query.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    limit = 16
    all_catalog = await get_grouped_catalog()
    filtered_catalog = []

    for item in all_catalog:
        # Hide bare clips without proper titles from main browse catalog unless user specifically searched for them
        if not query and item.get("key", "").startswith("clip:"):
            continue

        # 1. Search Query Filter
        if query:
            q_clean = query.lower()
            if q_clean not in item["title"].lower() and q_clean not in item["clean_name"].lower():
                continue

        # 2. Category / Filter Preset
        if filter_type == "series" and not item["is_series"]:
            continue
        if filter_type == "movies" and item["is_series"]:
            continue
        if filter_type == "anime" and not item.get("is_anime"):
            continue
        if filter_type == "recent" and not item["is_recent"]:
            continue
        if filter_type == "dualaudio":
            if not any(parse_media_metadata(f.get("file_name", "")).get("is_dual_audio") for f in item["files"]):
                continue

        # 3. Quality constraint
        if quality:
            if quality.lower() not in [q.lower() for q in item["qualities"]]:
                continue

        filtered_catalog.append(item)

    # If user searched for something not in the top cached catalog, query MongoDB directly across all files
    if query and len(filtered_catalog) < 4:
        tokens = [re.escape(t) for t in query.split() if len(t) >= 2]
        if tokens:
            mongo_filter = {"$and": [{"file_name": {"$regex": t, "$options": "i"}} for t in tokens]}
            try:
                direct_docs = await mongo.files.find(mongo_filter).sort("_id", -1).limit(40).to_list(40)
                if direct_docs:
                    existing_keys = {item["key"] for item in filtered_catalog}
                    extra_groups = _group_file_docs(direct_docs)
                    for g in extra_groups:
                        if g["key"] not in existing_keys:
                            filtered_catalog.append(g)
            except Exception as e:
                logger.debug(f"Direct browse search error: {e}")

    total_count = len(filtered_catalog)
    total_pages = max(1, (total_count + limit - 1) // limit) if total_count > 0 else 1
    page = min(page, total_pages)
    offset = (page - 1) * limit
    results = filtered_catalog[offset:offset+limit]

    # Fetch posters concurrently using TMDB CDN cache with year and media type accuracy
    posters = await asyncio.gather(*[
        get_cached_poster_url(item["clean_name"], year=item.get("year"), is_series=item.get("is_series"))
        for item in results
    ], return_exceptions=True)

    movie_cards = []
    for item, poster in zip(results, posters):
        title = item["title"]
        total_files = len(item["files"])
        total_size_str = get_readable_size(item["total_size"])
        poster_url = poster if isinstance(poster, str) and poster else ""

        badges_top_html = []
        if item.get("is_anime"):
            badges_top_html.append('<span class="cbadge cbadge-anime">🌸 ANIME</span>')
        if item["is_recent"]:
            badges_top_html.append('<span class="cbadge cbadge-new">🔥 NEW EPS</span>' if item["is_series"] else '<span class="cbadge cbadge-new">🔥 NEW</span>')
        
        if item["is_series"]:
            if item["episodes_count"] > 0:
                badges_top_html.append(f'<span class="cbadge cbadge-eps">📺 {item["episodes_count"]} Eps</span>')
            if item["has_combined"]:
                badges_top_html.append('<span class="cbadge cbadge-comb">📦 Pack</span>')
        else:
            if item.get("has_parts"):
                total_parts = len(item.get("parts_map", {}))
                badges_top_html.append(f'<span class="cbadge cbadge-comb">🧩 {total_parts} Parts</span>')
            if item["sorted_qualities"]:
                badges_top_html.append(f'<span class="cbadge cbadge-qual">{" • ".join(item["sorted_qualities"][:2])}</span>')

        if item.get("languages_list"):
            langs = item["languages_list"]
            if "Multi Audio" in langs:
                pref_lang = "Multi Audio"
            elif "Dual Audio" in langs:
                pref_lang = "Dual Audio"
            else:
                pref_lang = " • ".join(langs[:2])
            badges_top_html.append(f'<span class="cbadge cbadge-lang">🌐 {html_escape(pref_lang)}</span>')

        if poster_url:
            img_html = f'<img src="{poster_url}" class="poster-img" alt="{html_escape(title)}" loading="lazy" onerror="this.style.display=\'none\'; this.nextElementSibling.style.display=\'flex\';"><div class="poster-fallback" style="display:none;">🎬</div>'
        else:
            img_html = '<div class="poster-fallback" style="display:flex;">🎬</div>'

        badges_str = "\n".join(badges_top_html)

        card_url = f"{base_url}/post/{item['slug']}"
        if item["is_series"]:
            ep_c = item.get("episodes_count", 0)
            btn_label = f"📺 {ep_c} Episodes" if ep_c > 0 else "📦 View Series"
            btn_class = "card-series-btn"
        else:
            if item.get("has_parts"):
                total_parts = len(item.get("parts_map", {}))
                btn_label = f"▶ {total_parts} Parts"
            elif total_files > 1:
                btn_label = f"▶ {total_files} Prints"
            else:
                btn_label = "▶ Watch & Download"
            btn_class = "card-stream-btn"

        movie_cards.append(f"""
            <div class="catalog-card">
                <a href="{card_url}" class="poster-wrap" title="{html_escape(title)}">
                    <div class="card-badges-top">
                        {badges_str}
                    </div>
                    <div class="card-size-bottom">📦 {total_files} Files • {total_size_str}</div>
                    {img_html}
                    <div class="poster-play-overlay">
                        <div class="poster-play-icon">▶</div>
                    </div>
                </a>
                <div class="card-body">
                    <a href="{card_url}" class="card-title" title="{html_escape(title)}">{html_escape(title)}</a>
                    <a href="{card_url}" class="{btn_class}">{btn_label}</a>
                </div>
            </div>
        """)

    if not movie_cards:
        empty_msg = f'No movies found matching "{html_escape(query)}"' if query else "No files indexed in database yet."
        movie_cards_html = f"""
            <div class="empty-card">
                <div class="empty-icon">🔍</div>
                <div class="empty-title">No Results Found</div>
                <div class="empty-desc">{empty_msg}</div>
                <a href="{browse_url}" class="empty-btn">Clear Filters & Browse All</a>
            </div>
        """
    else:
        movie_cards_html = "\n".join(movie_cards)

    # Build pagination URLs preserving search & filters
    def build_page_url(p: int) -> str:
        params = []
        if query:
            params.append(f"q={urllib.parse.quote(query)}")
        if quality:
            params.append(f"quality={urllib.parse.quote(quality)}")
        if filter_type:
            params.append(f"filter={urllib.parse.quote(filter_type)}")
        params.append(f"page={p}")
        return f"{browse_url}?{'&'.join(params)}"

    if page > 1:
        prev_btn_html = f'<a href="{build_page_url(page - 1)}" class="page-btn">« Previous</a>'
    else:
        prev_btn_html = '<span class="page-btn disabled">« Previous</span>'

    if page < total_pages:
        next_btn_html = f'<a href="{build_page_url(page + 1)}" class="page-btn">Next »</a>'
    else:
        next_btn_html = '<span class="page-btn disabled">Next »</span>'

    # Filter active classes
    def get_filter_class(target_f: str, target_q: str = "") -> str:
        if target_q and quality == target_q:
            return "active"
        if not target_q and not quality and filter_type == target_f:
            return "active"
        if not target_q and not quality and not filter_type and target_f == "all":
            return "active"
        return ""

    start_num = (page - 1) * limit + 1 if total_count > 0 else 0
    end_num = min(page * limit, total_count)
    if query:
        status_text = f'Showing <b>{start_num}–{end_num}</b> of <b>{total_count}</b> titles for "<b>{html_escape(query)}</b>"'
    else:
        status_text = f'Showing <b>{start_num}–{end_num}</b> of <b>{total_count}</b> total series & movies'

    page_info_text = f"Page {page} of {total_pages}"
    page_title = f'Search: {query}' if query else 'Full Movie & Web Series Catalog'

    sponsor_banner_html = await get_web_sponsor_banner_html()

    html = CATALOG_HTML.format(
        sponsor_banner_html=sponsor_banner_html,
        page_title=html_escape(page_title),
        browse_url=browse_url,
        channel_url=channel_url,
        bot_username=bot_username,
        search_query=html_escape(query),
        active_filter_all=get_filter_class("all"),
        active_filter_recent=get_filter_class("recent"),
        active_filter_series=get_filter_class("series"),
        active_filter_movies=get_filter_class("movies"),
        active_filter_anime=get_filter_class("anime"),
        active_filter_1080p=get_filter_class("", "1080p"),
        active_filter_720p=get_filter_class("", "720p"),
        active_filter_4k=get_filter_class("", "2160p"),
        status_text=status_text,
        movie_cards_html=movie_cards_html,
        prev_btn_html=prev_btn_html,
        next_btn_html=next_btn_html,
        page_info_text=page_info_text
    )
    return web.Response(text=html, content_type="text/html")


async def mx_redirect_handler(request: web.Request):
    """Smart launcher for MX Player on Android with fallback."""
    param = request.match_info.get("file_unique_id")
    file_doc = await resolve_file_from_param(param)
    if not file_doc:
        return web.Response(text="File not found in database", status=404)

    base_url = get_stream_base_url(request)
    file_unique_id = file_doc.get("file_unique_id") or str(file_doc.get("_id"))
    file_name = file_doc.get("file_name", "Movie Video.mp4")
    quoted_name = urllib.parse.quote(file_name)
    stream_url = f"{base_url}/stream/{file_unique_id}/{quoted_name}"

    clean_url = re.sub(r'^https?://', '', stream_url)
    protocol = "https" if stream_url.startswith("https") else "http"
    safe_title = urllib.parse.quote(file_name)

    mx_free_intent = f"intent://{clean_url}#Intent;action=android.intent.action.VIEW;scheme={protocol};type=video/*;package=com.mxtech.videoplayer.ad;S.title={safe_title};end"
    mx_pro_intent = f"intent://{clean_url}#Intent;action=android.intent.action.VIEW;scheme={protocol};type=video/*;package=com.mxtech.videoplayer.pro;S.title={safe_title};end"
    android_chooser_intent = f"intent://{clean_url}#Intent;action=android.intent.action.VIEW;scheme={protocol};type=video/*;S.title={safe_title};end"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Launching MX Player...</title>
    <style>
        body {{
            background: #0f172a;
            color: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            text-align: center;
            padding: 20px;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 20px;
            padding: 30px;
            max-width: 440px;
            width: 100%;
            box-shadow: 0 15px 35px rgba(0,0,0,0.6);
        }}
        .title {{
            font-size: 15px;
            font-weight: 600;
            color: #94a3b8;
            margin-bottom: 20px;
            word-break: break-word;
        }}
        .btn {{
            display: block;
            width: 100%;
            margin-top: 12px;
            padding: 14px 20px;
            border-radius: 12px;
            font-weight: 600;
            text-decoration: none;
            color: white;
            box-sizing: border-box;
            cursor: pointer;
        }}
        .btn-mx {{ background: linear-gradient(135deg, #0284c7, #2563eb); }}
        .btn-pro {{ background: linear-gradient(135deg, #7c3aed, #6d28d9); }}
        .btn-chooser {{ background: linear-gradient(135deg, #059669, #047857); }}
    </style>
</head>
<body oncontextmenu="return false;" onselectstart="return false;" ondragstart="return false;">
    <div class="card">
        <div class="title">{html_escape(file_name)}</div>
        
        <a id="mx-btn" href="{mx_free_intent}" class="btn btn-mx">🚀 Open in MX Player</a>
        <a href="{mx_pro_intent}" class="btn btn-pro">⭐ Open in MX Player Pro</a>
        <a href="{android_chooser_intent}" class="btn btn-chooser">📱 Open in Any Video Player</a>
    </div>

    <script>
        document.addEventListener("DOMContentLoaded", function () {{
            const isAndroid = /Android/i.test(navigator.userAgent || "");
            if (!isAndroid) {{
                window.location.href = "{stream_url}";
            }}
        }});
        // Bulletproof Anti-Right-Click & Stealth URL Inspection Shield
        (function () {{
            function killEvent(e) {{
                if (e) {{
                    if (e.preventDefault) e.preventDefault();
                    if (e.stopPropagation) e.stopPropagation();
                    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                }}
                return false;
            }}
            window.addEventListener("contextmenu", killEvent, true);
            document.addEventListener("contextmenu", killEvent, true);
            window.addEventListener("selectstart", killEvent, true);
            document.addEventListener("selectstart", killEvent, true);
            window.addEventListener("dragstart", killEvent, true);
            document.addEventListener("dragstart", killEvent, true);
            window.oncontextmenu = killEvent;
            document.oncontextmenu = killEvent;
            window.addEventListener("keydown", function (e) {{
                if (
                    e.keyCode === 123 ||
                    (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74 || e.keyCode === 75 || e.keyCode === 69)) ||
                    (e.metaKey && e.altKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74)) ||
                    ((e.ctrlKey || e.metaKey) && (e.keyCode === 85 || e.keyCode === 83 || e.keyCode === 80))
                ) {{
                    return killEvent(e);
                }}
            }}, true);

            // Stealth URL Cloaker: Masks href for desktop status bar, preserves native app & intent schemes
            function maskLink(el) {{
                if (!el || !el.getAttribute) return;
                const href = el.getAttribute('href');
                if (!href || href.startsWith('javascript:') || href === '#' || href.startsWith('#')) return;
                if (href.startsWith('intent:') || href.startsWith('vlc:') || href.startsWith('vlc-x-callback:') || href.startsWith('tg:') || href.startsWith('market:') || href.startsWith('whatsapp:') || href.includes('/playlist/') || href.includes('/player/')) return;
                el.setAttribute('data-target-url', href);
                el.removeAttribute('href');
                el.style.cursor = 'pointer';
                el.setAttribute('role', 'link');
                el.setAttribute('tabindex', '0');
            }}

            function maskAll(root) {{
                const scope = root || document;
                if (!scope.querySelectorAll) return;
                scope.querySelectorAll('a[href]').forEach(maskLink);
            }}

            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', function () {{ maskAll(); }});
            }} else {{
                maskAll();
            }}

            // Pre-emptively mask links before hover triggers the status bar
            document.addEventListener('mouseover', function (e) {{
                const a = e.target && e.target.closest && e.target.closest('a[href]');
                if (a) maskLink(a);
            }}, true);

            window.openSafeUrl = function (url, newTab) {{
                if (!url) return;
                if (newTab) {{
                    const a = document.createElement('a');
                    a.href = url;
                    a.target = '_blank';
                    a.rel = 'noopener noreferrer';
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => {{
                        try {{ document.body.removeChild(a); }} catch (e) {{}}
                    }}, 250);
                }} else {{
                    window.location.href = url;
                }}
            }};

            if (window.MutationObserver) {{
                new MutationObserver(function (mutations) {{
                    for (let i = 0; i < mutations.length; i++) {{
                        const added = mutations[i].addedNodes;
                        for (let j = 0; j < added.length; j++) {{
                            if (added[j].nodeType === 1) {{
                                if (added[j].tagName === 'A' && added[j].hasAttribute('href')) {{
                                    maskLink(added[j]);
                                }} else if (added[j].querySelectorAll) {{
                                    maskAll(added[j]);
                                }}
                            }}
                        }}
                    }}
                }}).observe(document.documentElement, {{ childList: true, subtree: true }});
            }}

            document.addEventListener('click', function (e) {{
                const el = e.target && e.target.closest && e.target.closest('[data-target-url]');
                if (!el) return;
                if (e.defaultPrevented) return;

                const url = el.getAttribute('data-target-url');
                if (!url) return;

                const target = el.getAttribute('target');
                const isNewTab = (target === '_blank' || e.ctrlKey || e.metaKey || e.button === 1);
                window.openSafeUrl(url, isNewTab);
            }}, false);

            document.addEventListener('keydown', function (e) {{
                if (e.key === 'Enter') {{
                    const el = document.activeElement && document.activeElement.closest && document.activeElement.closest('[data-target-url]');
                    if (el) el.click();
                }}
            }});
        }})();
    </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def chooser_redirect_handler(request: web.Request):
    """Smart launcher for Android System App Chooser (Open in Any Video Player)."""
    param = request.match_info.get("file_unique_id")
    file_doc = await resolve_file_from_param(param)
    if not file_doc:
        return web.Response(text="File not found in database", status=404)

    base_url = get_stream_base_url(request)
    file_unique_id = file_doc.get("file_unique_id") or str(file_doc.get("_id"))
    file_name = file_doc.get("file_name", "Movie Video.mp4")
    quoted_name = urllib.parse.quote(file_name)
    stream_url = f"{base_url}/stream/{file_unique_id}/{quoted_name}"

    clean_url = re.sub(r'^https?://', '', stream_url)
    protocol = "https" if stream_url.startswith("https") else "http"
    safe_title = urllib.parse.quote(file_name)

    android_chooser_intent = f"intent://{clean_url}#Intent;action=android.intent.action.VIEW;scheme={protocol};type=video/*;S.title={safe_title};end"
    m3u_url = f"{base_url}/playlist/{file_unique_id}.m3u"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Launching Video Player...</title>
    <style>
        body {{
            background: #0b0f19;
            color: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            text-align: center;
            padding: 20px;
        }}
        .card {{
            background: rgba(22, 27, 34, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 20px;
            padding: 30px;
            max-width: 440px;
            width: 100%;
            box-shadow: 0 15px 35px rgba(0,0,0,0.6);
        }}
        .title {{
            font-size: 15px;
            font-weight: 600;
            color: #94a3b8;
            margin-bottom: 20px;
            word-break: break-word;
        }}
        .btn {{
            display: block;
            width: 100%;
            margin-top: 12px;
            padding: 14px 20px;
            border-radius: 12px;
            font-weight: 600;
            text-decoration: none;
            color: white;
            box-sizing: border-box;
            cursor: pointer;
        }}
        .btn-chooser {{ background: linear-gradient(135deg, #10b981, #059669); }}
        .btn-m3u {{ background: linear-gradient(135deg, #0284c7, #2563eb); }}
    </style>
</head>
<body oncontextmenu="return false;" onselectstart="return false;" ondragstart="return false;">
    <div class="card">
        <h2 style="margin-bottom:8px;">📱 Open in Any Video Player</h2>
        <div class="title">{html_escape(file_name)}</div>
        <p style="color:#94a3b8;font-size:13px;margin-bottom:15px;">Opening your phone's installed video players (PlayIt, MX, VLC, KMPlayer, Phone Player)...</p>
        <a id="chooser-btn" href="{android_chooser_intent}" class="btn btn-chooser">🚀 Open Player Selection</a>
        <a href="{m3u_url}" class="btn btn-m3u">📺 Download M3U (PC / TV)</a>
    </div>

    <script>
        document.addEventListener("DOMContentLoaded", function () {{
            const isAndroid = /Android/i.test(navigator.userAgent || "");
            if (!isAndroid) {{
                window.location.href = "{stream_url}";
            }}
        }});
        // Bulletproof Anti-Right-Click & Stealth URL Inspection Shield
        (function () {{
            function killEvent(e) {{
                if (e) {{
                    if (e.preventDefault) e.preventDefault();
                    if (e.stopPropagation) e.stopPropagation();
                    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                }}
                return false;
            }}
            window.addEventListener("contextmenu", killEvent, true);
            document.addEventListener("contextmenu", killEvent, true);
            window.addEventListener("selectstart", killEvent, true);
            document.addEventListener("selectstart", killEvent, true);
            window.addEventListener("dragstart", killEvent, true);
            document.addEventListener("dragstart", killEvent, true);
            window.oncontextmenu = killEvent;
            document.oncontextmenu = killEvent;
            window.addEventListener("keydown", function (e) {{
                if (
                    e.keyCode === 123 ||
                    (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74 || e.keyCode === 75 || e.keyCode === 69)) ||
                    (e.metaKey && e.altKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74)) ||
                    ((e.ctrlKey || e.metaKey) && (e.keyCode === 85 || e.keyCode === 83 || e.keyCode === 80))
                ) {{
                    return killEvent(e);
                }}
            }}, true);

            // Stealth URL Cloaker: Masks href for desktop status bar, preserves native app & intent schemes
            function maskLink(el) {{
                if (!el || !el.getAttribute) return;
                const href = el.getAttribute('href');
                if (!href || href.startsWith('javascript:') || href === '#' || href.startsWith('#')) return;
                if (href.startsWith('intent:') || href.startsWith('vlc:') || href.startsWith('vlc-x-callback:') || href.startsWith('tg:') || href.startsWith('market:') || href.startsWith('whatsapp:') || href.includes('/playlist/') || href.includes('/player/')) return;
                el.setAttribute('data-target-url', href);
                el.removeAttribute('href');
                el.style.cursor = 'pointer';
                el.setAttribute('role', 'link');
                el.setAttribute('tabindex', '0');
            }}

            function maskAll(root) {{
                const scope = root || document;
                if (!scope.querySelectorAll) return;
                scope.querySelectorAll('a[href]').forEach(maskLink);
            }}

            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', function () {{ maskAll(); }});
            }} else {{
                maskAll();
            }}

            // Pre-emptively mask links before hover triggers the status bar
            document.addEventListener('mouseover', function (e) {{
                const a = e.target && e.target.closest && e.target.closest('a[href]');
                if (a) maskLink(a);
            }}, true);

            window.openSafeUrl = function (url, newTab) {{
                if (!url) return;
                if (newTab) {{
                    const a = document.createElement('a');
                    a.href = url;
                    a.target = '_blank';
                    a.rel = 'noopener noreferrer';
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => {{
                        try {{ document.body.removeChild(a); }} catch (e) {{}}
                    }}, 250);
                }} else {{
                    window.location.href = url;
                }}
            }};

            if (window.MutationObserver) {{
                new MutationObserver(function (mutations) {{
                    for (let i = 0; i < mutations.length; i++) {{
                        const added = mutations[i].addedNodes;
                        for (let j = 0; j < added.length; j++) {{
                            if (added[j].nodeType === 1) {{
                                if (added[j].tagName === 'A' && added[j].hasAttribute('href')) {{
                                    maskLink(added[j]);
                                }} else if (added[j].querySelectorAll) {{
                                    maskAll(added[j]);
                                }}
                            }}
                        }}
                    }}
                }}).observe(document.documentElement, {{ childList: true, subtree: true }});
            }}

            document.addEventListener('click', function (e) {{
                const el = e.target && e.target.closest && e.target.closest('[data-target-url]');
                if (!el) return;
                if (e.defaultPrevented) return;

                const url = el.getAttribute('data-target-url');
                if (!url) return;

                const target = el.getAttribute('target');
                const isNewTab = (target === '_blank' || e.ctrlKey || e.metaKey || e.button === 1);
                window.openSafeUrl(url, isNewTab);
            }}, false);

            document.addEventListener('keydown', function (e) {{
                if (e.key === 'Enter') {{
                    const el = document.activeElement && document.activeElement.closest && document.activeElement.closest('[data-target-url]');
                    if (el) el.click();
                }}
            }});
        }})();
    </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def vlc_redirect_handler(request: web.Request):
    """Smart launcher for VLC Player across Android, iOS, and Desktop."""
    param = request.match_info.get("file_unique_id")
    file_doc = await resolve_file_from_param(param)
    if not file_doc:
        return web.Response(text="File not found in database", status=404)

    base_url = get_stream_base_url(request)
    file_unique_id = file_doc.get("file_unique_id") or str(file_doc.get("_id"))
    file_name = file_doc.get("file_name", "Movie Video.mp4")
    quoted_name = urllib.parse.quote(file_name)
    stream_url = f"{base_url}/stream/{file_unique_id}/{quoted_name}"
    m3u_url = f"{base_url}/playlist/{file_unique_id}.m3u"

    clean_url = re.sub(r'^https?://', '', stream_url)
    protocol = "https" if stream_url.startswith("https") else "http"
    safe_title = urllib.parse.quote(file_name)

    android_vlc_intent = f"intent://{clean_url}#Intent;action=android.intent.action.VIEW;scheme={protocol};type=video/*;package=org.videolan.vlc;S.title={safe_title};end"
    android_chooser_intent = f"intent://{clean_url}#Intent;action=android.intent.action.VIEW;scheme={protocol};type=video/*;S.title={safe_title};end"
    ios_vlc_url = f"vlc-x-callback://x-callback-url/stream?url={urllib.parse.quote(stream_url)}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Launching VLC Player...</title>
    <style>
        body {{
            background: #0f172a;
            color: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            text-align: center;
            padding: 20px;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 20px;
            padding: 30px;
            max-width: 440px;
            width: 100%;
            box-shadow: 0 15px 35px rgba(0,0,0,0.6);
        }}
        .title {{
            font-size: 15px;
            font-weight: 600;
            color: #94a3b8;
            margin-bottom: 20px;
            word-break: break-word;
        }}
        .btn {{
            display: block;
            width: 100%;
            margin-top: 12px;
            padding: 14px 20px;
            border-radius: 12px;
            font-weight: 600;
            text-decoration: none;
            color: white;
            box-sizing: border-box;
            cursor: pointer;
        }}
        .btn-vlc {{ background: linear-gradient(135deg, #ea580c, #c2410c); }}
        .btn-chooser {{ background: linear-gradient(135deg, #0284c7, #2563eb); }}
        .btn-m3u {{ background: linear-gradient(135deg, #059669, #047857); }}
    </style>
</head>
<body oncontextmenu="return false;" onselectstart="return false;" ondragstart="return false;">
    <div class="card">
        <h2 style="margin-bottom:8px;">🧡 Open in VLC Player</h2>
        <div class="title">{html_escape(file_name)}</div>
        
        <a id="vlc-btn" href="{android_vlc_intent}" class="btn btn-vlc">🚀 Open in VLC Player (App)</a>
        <a href="vlc://{clean_url}" class="btn btn-vlc" style="background: linear-gradient(135deg, #f97316, #ea580c);">🧡 Direct VLC Link</a>
        <a href="{android_chooser_intent}" class="btn btn-chooser">📱 Open in Any Video Player</a>
        <a href="{m3u_url}" class="btn btn-m3u">📺 Download M3U (PC / TV)</a>
    </div>

    <script>
        document.addEventListener("DOMContentLoaded", function () {{
            const ua = navigator.userAgent || "";
            const isAndroid = /Android/i.test(ua);
            const isIOS = /iPhone|iPad|iPod/i.test(ua);
            const vlcBtn = document.getElementById("vlc-btn");

            if (isIOS) {{
                if (vlcBtn) vlcBtn.href = "{ios_vlc_url}";
                window.location.href = "{ios_vlc_url}";
            }} else if (!isAndroid) {{
                if (vlcBtn) vlcBtn.href = "{m3u_url}";
                window.location.href = "{m3u_url}";
            }}
        }});
        // Bulletproof Anti-Right-Click & Stealth URL Inspection Shield
        (function () {{
            function killEvent(e) {{
                if (e) {{
                    if (e.preventDefault) e.preventDefault();
                    if (e.stopPropagation) e.stopPropagation();
                    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                }}
                return false;
            }}
            window.addEventListener("contextmenu", killEvent, true);
            document.addEventListener("contextmenu", killEvent, true);
            window.addEventListener("selectstart", killEvent, true);
            document.addEventListener("selectstart", killEvent, true);
            window.addEventListener("dragstart", killEvent, true);
            document.addEventListener("dragstart", killEvent, true);
            window.oncontextmenu = killEvent;
            document.oncontextmenu = killEvent;
            window.addEventListener("keydown", function (e) {{
                if (
                    e.keyCode === 123 ||
                    (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74 || e.keyCode === 75 || e.keyCode === 69)) ||
                    (e.metaKey && e.altKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74)) ||
                    ((e.ctrlKey || e.metaKey) && (e.keyCode === 85 || e.keyCode === 83 || e.keyCode === 80))
                ) {{
                    return killEvent(e);
                }}
            }}, true);

            // Stealth URL Cloaker: Masks href for desktop status bar, preserves native app & intent schemes
            function maskLink(el) {{
                if (!el || !el.getAttribute) return;
                const href = el.getAttribute('href');
                if (!href || href.startsWith('javascript:') || href === '#' || href.startsWith('#')) return;
                if (href.startsWith('intent:') || href.startsWith('vlc:') || href.startsWith('vlc-x-callback:') || href.startsWith('tg:') || href.startsWith('market:') || href.startsWith('whatsapp:') || href.includes('/playlist/') || href.includes('/player/')) return;
                el.setAttribute('data-target-url', href);
                el.removeAttribute('href');
                el.style.cursor = 'pointer';
                el.setAttribute('role', 'link');
                el.setAttribute('tabindex', '0');
            }}

            function maskAll(root) {{
                const scope = root || document;
                if (!scope.querySelectorAll) return;
                scope.querySelectorAll('a[href]').forEach(maskLink);
            }}

            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', function () {{ maskAll(); }});
            }} else {{
                maskAll();
            }}

            // Pre-emptively mask links before hover triggers the status bar
            document.addEventListener('mouseover', function (e) {{
                const a = e.target && e.target.closest && e.target.closest('a[href]');
                if (a) maskLink(a);
            }}, true);

            window.openSafeUrl = function (url, newTab) {{
                if (!url) return;
                if (newTab) {{
                    const a = document.createElement('a');
                    a.href = url;
                    a.target = '_blank';
                    a.rel = 'noopener noreferrer';
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => {{
                        try {{ document.body.removeChild(a); }} catch (e) {{}}
                    }}, 250);
                }} else {{
                    window.location.href = url;
                }}
            }};

            if (window.MutationObserver) {{
                new MutationObserver(function (mutations) {{
                    for (let i = 0; i < mutations.length; i++) {{
                        const added = mutations[i].addedNodes;
                        for (let j = 0; j < added.length; j++) {{
                            if (added[j].nodeType === 1) {{
                                if (added[j].tagName === 'A' && added[j].hasAttribute('href')) {{
                                    maskLink(added[j]);
                                }} else if (added[j].querySelectorAll) {{
                                    maskAll(added[j]);
                                }}
                            }}
                        }}
                    }}
                }}).observe(document.documentElement, {{ childList: true, subtree: true }});
            }}

            document.addEventListener('click', function (e) {{
                const el = e.target && e.target.closest && e.target.closest('[data-target-url]');
                if (!el) return;
                if (e.defaultPrevented) return;

                const url = el.getAttribute('data-target-url');
                if (!url) return;

                const target = el.getAttribute('target');
                const isNewTab = (target === '_blank' || e.ctrlKey || e.metaKey || e.button === 1);
                window.openSafeUrl(url, isNewTab);
            }}, false);

            document.addEventListener('keydown', function (e) {{
                if (e.key === 'Enter') {{
                    const el = document.activeElement && document.activeElement.closest && document.activeElement.closest('[data-target-url]');
                    if (el) el.click();
                }}
            }});
        }})();
    </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def playlist_handler(request: web.Request):
    """Generate M3U playlist file for VLC, PotPlayer, Kodi, and IINA."""
    param = request.match_info.get("file_unique_id")
    file_doc = await resolve_file_from_param(param)
    if not file_doc:
        return web.Response(text="File not found", status=404)

    base_url = get_stream_base_url(request)
    file_unique_id = file_doc.get("file_unique_id") or str(file_doc.get("_id"))
    file_name = file_doc.get("file_name", "Movie Video.mp4")
    quoted_name = urllib.parse.quote(file_name)
    stream_url = f"{base_url}/stream/{file_unique_id}/{quoted_name}"

    clean_title = re.sub(r'[^\w\-_\. ]', '_', file_name).strip()
    m3u_content = f"#EXTM3U\n#EXTINF:-1,{file_name}\n{stream_url}\n"
    return web.Response(
        text=m3u_content,
        content_type="audio/x-mpegurl",
        headers={
            "Content-Disposition": f'attachment; filename="{clean_title}.m3u"',
            "Access-Control-Allow-Origin": "*"
        }
    )


async def health_handler(request):
    """Health-check endpoint for Koyeb, Heroku, and Render monitoring probes."""
    return web.json_response({
        "status": "online",
        "version": "1.0.6",
        "service": "AutoFilterBot",
        "streaming_enabled": Config.ENABLE_STREAMING,
        "max_concurrent_streams": Config.MAX_CONCURRENT_STREAMS,
        "port": Config.PORT
    })


async def verify_redirect_handler(request):
    """Handle /verify/{token} with 3-second animated countdown and automatic shortlink redirect."""
    token = request.match_info.get("token")
    if not token:
        return web.Response(text="Missing token", status=400)

    try:
        doc = await mongo.verify.find_one({"token": token})
        if not doc:
            doc = await mongo.db["gift_task_tokens"].find_one({"token": token})

        if not doc:
            html = VERIFY_ERROR_HTML.format(bot_username=Config.BOT_USERNAME or "bot")
            return web.Response(text=html, content_type="text/html", status=404)

        # Record click timestamp for anti-cheat verification on gift task tokens
        if str(token).startswith("gtok_"):
            try:
                await mongo.db["gift_task_tokens"].update_one(
                    {"token": token},
                    {"$set": {"clicked_at": datetime.datetime.utcnow()}}
                )
            except Exception as e_clk:
                logger.debug(f"Error recording clicked_at for {token}: {e_clk}")

        target_url = doc.get("short_link") or doc.get("target_url")
        if not target_url:
            bot_username = Config.BOT_USERNAME or "bot"
            if str(token).startswith("gtok_"):
                target_url = f"https://t.me/{bot_username}?start=vgtok_{token}"
            else:
                target_url = f"https://t.me/{bot_username}?start=verify_{token}"

        # If this is specifically a setgiftad (ad_task) direct sponsor link,
        # skip the 5-second countdown gateway and redirect immediately!
        # For shorteners and general bot pass verifications, retain the full 5s gateway.
        task_type = str(doc.get("task_type", ""))
        if task_type == "ad_task" or task_type.startswith("ad_task_"):
            return web.HTTPFound(location=target_url)

        import base64
        target_b64 = base64.b64encode(target_url.encode("utf-8")).decode("utf-8")
        html = VERIFY_GATEWAY_HTML.format(target_b64=target_b64, target_url=target_url)
        return web.Response(text=html, content_type="text/html")
    except Exception as e:
        logger.error(f"Error serving verification redirect for token {token}: {e}")
        return web.Response(text="Internal Server Error", status=500)


ONLINE_PLAYER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Watching {title} - AkMovieVerse Cinema</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23e50914'><path d='M8 5v14l11-7z'/></svg>">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{
            background: radial-gradient(circle at top, #111827, #030712 90%);
            color: #f3f4f6;
            min-height: 100vh;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            overflow-x: hidden;
        }}
        .player-stage {{
            position: relative;
            width: 100%;
            padding-bottom: 56.25%;
            border-radius: 16px;
            overflow: hidden;
            background: #000;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.8), 0 0 30px rgba(229, 9, 20, 0.15);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }}
        .player-stage iframe {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            border: none;
        }}
        .server-btn {{
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            user-select: none;
            -webkit-user-select: none;
        }}
        .server-btn.active {{
            background: linear-gradient(135deg, #e50914, #b91c1c) !important;
            color: #ffffff !important;
            box-shadow: 0 0 16px rgba(229, 9, 20, 0.5) !important;
            border-color: #ef4444 !important;
            font-weight: 700 !important;
        }}
        .no-scrollbar::-webkit-scrollbar {{
            display: none;
        }}
        .no-scrollbar {{
            -ms-overflow-style: none;
            scrollbar-width: none;
        }}
        .glass-panel {{
            background: rgba(17, 24, 39, 0.7);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }}
        .sponsor-banner-bar {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.14), rgba(239, 68, 68, 0.14));
            border: 1px solid rgba(245, 158, 11, 0.4);
            padding: 11px 16px;
            border-radius: 12px;
            text-decoration: none;
            margin-bottom: 14px;
            transition: all 0.2s ease;
        }}
        .sponsor-banner-bar:hover {{
            border-color: rgba(245, 158, 11, 0.8);
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.25), rgba(239, 68, 68, 0.25));
            transform: translateY(-1px);
        }}
        .sponsor-tag {{
            font-size: 11px;
            font-weight: 900;
            background: #f59e0b;
            color: #000;
            padding: 3px 8px;
            border-radius: 5px;
            letter-spacing: 0.5px;
            margin-right: 10px;
            flex-shrink: 0;
        }}
        .sponsor-text {{
            color: #fef3c7;
            font-size: 14.5px;
            font-weight: 700;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            flex: 1;
        }}
        .sponsor-arrow {{
            color: #f59e0b;
            font-size: 16px;
            font-weight: 800;
            margin-left: 10px;
        }}
    </style>
</head>
<body class="p-2.5 sm:p-6 flex flex-col items-center" oncontextmenu="return false;" onselectstart="return false;" ondragstart="return false;">
    <div class="w-full max-w-5xl space-y-3 sm:space-y-4">
        <!-- Header -->
        <header class="flex items-center justify-between glass-panel px-3.5 py-2.5 sm:px-6 sm:py-4 rounded-2xl">
            <div class="flex items-center space-x-2 sm:space-x-3 min-w-0">
                <div class="text-lg sm:text-2xl font-black text-red-500 tracking-wider flex items-center gap-1.5 sm:gap-2 whitespace-nowrap">
                    <span>🍿</span> <span>AkMovieVerse</span>
                </div>
            </div>
            <div class="flex items-center gap-1.5 sm:gap-2 flex-shrink-0">
                <a href="{bot_url}" class="text-xs sm:text-sm font-medium px-2.5 sm:px-3.5 py-1.5 bg-white/10 hover:bg-white/20 text-gray-200 rounded-xl transition flex items-center gap-1.5 border border-white/10 whitespace-nowrap">
                    <span>🤖</span> <span>Bot</span><span class="hidden sm:inline">&nbsp;Help</span>
                </a>
            </div>
        </header>

        {sponsor_banner_html}

        <!-- Player Stage Container (TOP PRIORITY - ALWAYS FIRST) -->
        <div class="player-stage">
            <iframe id="cinema-iframe" src="{initial_stream_url}" allowfullscreen allow="autoplay; encrypted-media; fullscreen; picture-in-picture"></iframe>
        </div>

        <!-- Server Selector Bar (Horizontally scrollable swipe strip directly below player) -->
        <div class="glass-panel p-2.5 sm:p-3 rounded-2xl space-y-2">
            <div class="flex items-center justify-between px-1">
                <span class="text-xs font-semibold uppercase tracking-wider text-gray-400 flex items-center gap-1.5">
                    <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                    <span>Streaming Servers:</span>
                </span>
                <span id="active-server-name" class="text-xs font-bold text-red-400 truncate max-w-[190px] sm:max-w-none">⚡ Server 1: VidLink Pro (Fast / HD)</span>
            </div>
            <div class="flex items-center gap-2 overflow-x-auto pb-1.5 pt-0.5 no-scrollbar flex-nowrap" id="server-buttons-container">
                {server_buttons_html}
            </div>
        </div>

        {series_controls_html}

        <!-- Movie Details & Quick Launch -->
        <div class="glass-panel p-3.5 sm:p-6 rounded-2xl flex flex-col sm:flex-row gap-4 sm:gap-5 items-start">
            {poster_html}
            <div class="flex-1 space-y-3 w-full">
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/5 pb-3">
                    <div>
                        <h1 class="text-base sm:text-2xl font-black text-white flex items-center gap-2 flex-wrap">
                            {title}
                            {year_badge}
                        </h1>
                        <div class="flex items-center gap-2.5 text-xs sm:text-sm text-gray-400 mt-1 flex-wrap">
                            {rating_badge}
                            <span class="w-1 h-1 rounded-full bg-gray-600"></span>
                            <span>{genres_info}</span>
                        </div>
                    </div>
                    <div class="flex items-center gap-2 flex-wrap">
                        <button onclick="toggleFullscreen()" class="px-3.5 py-1.5 text-xs font-semibold bg-zinc-800 hover:bg-zinc-700 text-gray-200 rounded-xl transition border border-white/10 flex items-center gap-1.5 shadow-sm">
                            <span>⛶</span> <span>Fullscreen</span>
                        </button>
                        <a href="{bot_url}" class="px-3.5 py-1.5 text-xs font-semibold bg-red-600 hover:bg-red-500 text-white rounded-xl transition shadow-lg shadow-red-600/30 flex items-center gap-1.5">
                            <span>💬</span> <span>Request File</span>
                        </a>
                    </div>
                </div>
                <div class="space-y-1">
                    <h3 class="text-xs font-bold uppercase tracking-wider text-gray-400">Storyline:</h3>
                    <p class="text-xs sm:text-sm text-gray-300 leading-relaxed">
                        {overview_text}
                    </p>
                </div>
            </div>
        </div>

        <!-- Third-Party Stream Disclaimer & Server Switch Tip -->
        <div class="glass-panel p-3 sm:p-3.5 rounded-2xl border-l-4 border-l-amber-500/80 bg-amber-950/20 text-amber-200/90 text-xs space-y-1 shadow-sm">
            <div class="flex items-center gap-1.5 font-bold text-amber-400">
                <span>💡</span> <span>Streaming Tips:</span>
            </div>
            <p class="leading-relaxed text-[11px] sm:text-xs text-amber-100/70">
                Stream sources are aggregated via third-party web scrapers. If video buffers or fails to load, <strong>swipe and switch between the streaming servers above</strong>, or request the high-speed file on our Telegram bot!
            </p>
        </div>

        <footer class="text-center text-[11px] text-gray-500 py-2">
            Powered by AkMovieVerse Bot & Multi-Stream Gateways • Non-commercial streaming interface
        </footer>
    </div>

    <script>
        const servers = {servers_json};
        let currentServerKey = 'vidlink';

        function switchServer(key) {{
            if (!servers[key]) return;
            currentServerKey = key;
            const iframe = document.getElementById('cinema-iframe');
            if (iframe) {{
                iframe.src = servers[key].url;
            }}
            document.querySelectorAll('.server-btn').forEach(btn => {{
                btn.classList.remove('active');
                if (btn.dataset.key === key) {{
                    btn.classList.add('active');
                    btn.scrollIntoView({{ behavior: 'smooth', block: 'nearest', inline: 'center' }});
                }}
            }});
            const label = document.getElementById('active-server-name');
            if (label) {{
                label.innerText = servers[key].name;
            }}
        }}

        function toggleFullscreen() {{
            const iframe = document.getElementById('cinema-iframe');
            if (!iframe) return;
            if (iframe.requestFullscreen) {{
                iframe.requestFullscreen();
            }} else if (iframe.webkitRequestFullscreen) {{
                iframe.webkitRequestFullscreen();
            }} else if (iframe.msRequestFullscreen) {{
                iframe.msRequestFullscreen();
            }}
        }}
        // Bulletproof Anti-Right-Click & Stealth URL Inspection Shield
        (function () {{
            function killEvent(e) {{
                if (e) {{
                    if (e.preventDefault) e.preventDefault();
                    if (e.stopPropagation) e.stopPropagation();
                    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                }}
                return false;
            }}
            window.addEventListener("contextmenu", killEvent, true);
            document.addEventListener("contextmenu", killEvent, true);
            window.addEventListener("selectstart", killEvent, true);
            document.addEventListener("selectstart", killEvent, true);
            window.addEventListener("dragstart", killEvent, true);
            document.addEventListener("dragstart", killEvent, true);
            window.oncontextmenu = killEvent;
            document.oncontextmenu = killEvent;
            window.addEventListener("keydown", function (e) {{
                if (
                    e.keyCode === 123 ||
                    (e.ctrlKey && e.shiftKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74 || e.keyCode === 75 || e.keyCode === 69)) ||
                    (e.metaKey && e.altKey && (e.keyCode === 73 || e.keyCode === 67 || e.keyCode === 74)) ||
                    ((e.ctrlKey || e.metaKey) && (e.keyCode === 85 || e.keyCode === 83 || e.keyCode === 80))
                ) {{
                    return killEvent(e);
                }}
            }}, true);

            // Stealth URL Cloaker: Masks href for desktop status bar, preserves native app & intent schemes
            function maskLink(el) {{
                if (!el || !el.getAttribute) return;
                const href = el.getAttribute('href');
                if (!href || href.startsWith('javascript:') || href === '#' || href.startsWith('#')) return;
                if (href.startsWith('intent:') || href.startsWith('vlc:') || href.startsWith('vlc-x-callback:') || href.startsWith('tg:') || href.startsWith('market:') || href.startsWith('whatsapp:') || href.includes('/playlist/') || href.includes('/player/')) return;
                el.setAttribute('data-target-url', href);
                el.removeAttribute('href');
                el.style.cursor = 'pointer';
                el.setAttribute('role', 'link');
                el.setAttribute('tabindex', '0');
            }}

            function maskAll(root) {{
                const scope = root || document;
                if (!scope.querySelectorAll) return;
                scope.querySelectorAll('a[href]').forEach(maskLink);
            }}

            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', function () {{ maskAll(); }});
            }} else {{
                maskAll();
            }}

            // Pre-emptively mask links before hover triggers the status bar
            document.addEventListener('mouseover', function (e) {{
                const a = e.target && e.target.closest && e.target.closest('a[href]');
                if (a) maskLink(a);
            }}, true);

            window.openSafeUrl = function (url, newTab) {{
                if (!url) return;
                if (newTab) {{
                    const a = document.createElement('a');
                    a.href = url;
                    a.target = '_blank';
                    a.rel = 'noopener noreferrer';
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => {{
                        try {{ document.body.removeChild(a); }} catch (e) {{}}
                    }}, 250);
                }} else {{
                    window.location.href = url;
                }}
            }};

            if (window.MutationObserver) {{
                new MutationObserver(function (mutations) {{
                    for (let i = 0; i < mutations.length; i++) {{
                        const added = mutations[i].addedNodes;
                        for (let j = 0; j < added.length; j++) {{
                            if (added[j].nodeType === 1) {{
                                if (added[j].tagName === 'A' && added[j].hasAttribute('href')) {{
                                    maskLink(added[j]);
                                }} else if (added[j].querySelectorAll) {{
                                    maskAll(added[j]);
                                }}
                            }}
                        }}
                    }}
                }}).observe(document.documentElement, {{ childList: true, subtree: true }});
            }}

            document.addEventListener('click', function (e) {{
                const el = e.target && e.target.closest && e.target.closest('[data-target-url]');
                if (!el) return;
                if (e.defaultPrevented) return;

                const url = el.getAttribute('data-target-url');
                if (!url) return;

                const target = el.getAttribute('target');
                const isNewTab = (target === '_blank' || e.ctrlKey || e.metaKey || e.button === 1);
                window.openSafeUrl(url, isNewTab);
            }}, false);

            document.addEventListener('keydown', function (e) {{
                if (e.key === 'Enter') {{
                    const el = e.target && e.target.closest && e.target.closest('[data-target-url]');
                    if (el) {{
                        const url = el.getAttribute('data-target-url');
                        if (url) {{
                            const target = el.getAttribute('target');
                            const isNewTab = (target === '_blank');
                            window.openSafeUrl(url, isNewTab);
                        }}
                    }}
                }}
            }}, false);
        }})();
    </script>
</body>
</html>
"""

async def watch_online_handler(request: web.Request):
    """Serve responsive multi-server online cinema player for movies/series not found locally."""
    imdb_id = request.match_info.get("imdb_id")
    if not imdb_id:
        return web.Response(text="Missing IMDb ID", status=400)

    import json
    from utils.online_stream import get_online_servers, get_series_episodes_meta, get_meta_by_imdb, search_online_meta

    media_type = request.query.get("type", "movie")
    try:
        season = int(request.query.get("s", "1") or 1)
    except ValueError:
        season = 1
    try:
        episode = int(request.query.get("e", "1") or 1)
    except ValueError:
        episode = 1
    title_param = request.query.get("title", "")
    clean_title = urllib.parse.unquote(title_param) if title_param else ""

    tmdb_param = request.query.get("tmdb")
    tmdb_id = int(tmdb_param) if tmdb_param and tmdb_param.isdigit() else None

    # Handle dynamic search queries: e.g. /watch_online/search?q=movie_name
    if imdb_id == "search" or not imdb_id.startswith("tt"):
        search_query = request.query.get("q") or imdb_id
        if search_query:
            online_search_res = await search_online_meta(search_query)
            if online_search_res and online_search_res.get("imdb_id"):
                imdb_id = online_search_res["imdb_id"]
                if not tmdb_id and online_search_res.get("tmdb_id"):
                    tmdb_id = online_search_res["tmdb_id"]
                if not clean_title:
                    clean_title = online_search_res.get("title", "")
                media_type = online_search_res.get("media_type", media_type)
                if online_search_res.get("season"):
                    season = online_search_res["season"]
                if online_search_res.get("episode"):
                    episode = online_search_res["episode"]

    # Auto-enrich metadata from Cinemeta using IMDb ID
    imdb_meta = await get_meta_by_imdb(imdb_id, media_type)
    if not clean_title or clean_title == "Online Cinema":
        clean_title = imdb_meta.get("title") or "Online Cinema"

    if imdb_meta.get("media_type"):
        media_type = imdb_meta["media_type"]

    if not tmdb_id and imdb_meta.get("moviedb_id"):
        tmdb_id = imdb_meta["moviedb_id"]

    servers = get_online_servers(imdb_id=imdb_id, tmdb_id=tmdb_id, media_type=media_type, season=season, episode=episode)
    initial_url = servers.get("vidlink", {}).get("url") or (list(servers.values())[0]["url"] if servers else "")

    btns = []
    short_labels = {
        "vidlink": ("⚡", "S1: VidLink Pro"),
        "videm": ("🎬", "S2: VidEm"),
        "vidsrc": ("🌐", "S3: VidSrc.pm"),
        "smashystream": ("🚀", "S4: Smashy"),
        "twoembed": ("🍿", "S5: 2Embed"),
        "autoembed": ("🔥", "S6: AutoEmbed"),
        "vidsrc_su": ("🛰️", "S7: VidSrc.su"),
        "vidy": ("🎥", "S8: Vidy Stream"),
        "vidzee": ("⚡", "S9: VidZee"),
        "nontongo": ("💎", "S10: NontonGo"),
        "embedsu": ("✨", "S11: SuperEmbed")
    }

    for key, s in servers.items():
        is_active = " active" if key == "vidlink" else ""
        icon, label = short_labels.get(key, (s.get("icon", "⚡"), s.get("name", key)))
        btns.append(
            f'<button class="server-btn{is_active} shrink-0 px-3.5 py-2 text-xs font-semibold rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-gray-200 transition-all flex items-center gap-1.5 whitespace-nowrap cursor-pointer" data-key="{key}" onclick="switchServer(\'{key}\')">'
            f'<span>{icon}</span> <span>{html_escape(label)}</span>'
            f'</button>'
        )
    server_buttons_html = "\n".join(btns)

    series_controls_html = ""
    if media_type == "series":
        series_meta = await get_series_episodes_meta(imdb_id)
        if series_meta and series_meta.get("seasons"):
            seasons = series_meta.get("seasons", [1])
            curr_season_eps = series_meta.get("episodes_by_season", {}).get(str(season), [])
            ep_btns = []
            tmdb_str = f"&tmdb={tmdb_id}" if tmdb_id else ""
            for ep in curr_season_eps[:24]:
                ep_num = ep.get("episode", 1)
                active_ep = " bg-red-600 text-white font-bold" if ep_num == episode else " bg-white/5 hover:bg-white/10 text-gray-300"
                ep_url = f"/watch_online/{imdb_id}?type=series&s={season}&e={ep_num}&title={urllib.parse.quote(clean_title)}{tmdb_str}"
                ep_btns.append(
                    f'<a href="{ep_url}" class="px-2.5 py-1 text-xs rounded-lg border border-white/10 transition{active_ep}">'
                    f'EP {ep_num}'
                    f'</a>'
                )
            ep_btns_html = "".join(ep_btns) if ep_btns else '<span class="text-xs text-gray-400">Episode 1</span>'

            series_controls_html = f"""
            <div class="glass-panel p-3 rounded-2xl space-y-2">
                <div class="flex items-center justify-between text-xs text-gray-400 font-semibold px-1">
                    <span>📺 Season {season} Episodes:</span>
                    <span>Total {len(curr_season_eps)} Episodes</span>
                </div>
                <div class="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto">
                    {ep_btns_html}
                </div>
            </div>
            """

    channel_url = getattr(Config, "CHANNEL_URL", None) or "https://t.me/AkMovieVerse"
    bot_username = getattr(Config, "BOT_USERNAME", None) or "bot"
    bot_url = f"https://t.me/{bot_username}"

    # Rich Movie Metadata & Poster
    poster_url = imdb_meta.get("poster")
    if poster_url:
        poster_html = f'''
        <div class="w-28 sm:w-36 flex-shrink-0 rounded-xl overflow-hidden border border-white/10 shadow-2xl hidden sm:block">
            <img src="{html_escape(poster_url)}" alt="{html_escape(clean_title)}" class="w-full h-auto object-cover" onerror="this.parentElement.style.display=\'none\';">
        </div>
        '''
    else:
        poster_html = ""

    year_val = imdb_meta.get("year")
    year_badge = f'<span class="text-xs px-2.5 py-0.5 rounded-full bg-red-600/20 text-red-400 border border-red-500/30 font-bold">{year_val}</span>' if year_val else '<span class="text-xs px-2.5 py-0.5 rounded-full bg-red-600/20 text-red-400 border border-red-500/30 font-bold">HD</span>'

    rating_val = imdb_meta.get("rating")
    rating_badge = f'<span class="inline-flex items-center gap-1 text-amber-400 font-bold bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded-lg text-xs">⭐ {rating_val} / 10 IMDb</span>' if rating_val else '<span class="inline-flex items-center gap-1 text-emerald-400 font-bold bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-lg text-xs">⚡ HD Stream</span>'

    genres_info = html_escape(imdb_meta.get("genres") or "⚡ Instant Multi-Server Web Stream")
    overview_text = html_escape(imdb_meta.get("overview") or "Stream online directly with your browser. Switch servers if playback buffers or is slow.")

    sponsor_banner_html = await get_web_sponsor_banner_html()

    html = ONLINE_PLAYER_HTML.format(
        title=html_escape(clean_title),
        channel_url=html_escape(channel_url),
        bot_url=html_escape(bot_url),
        server_buttons_html=server_buttons_html,
        series_controls_html=series_controls_html,
        initial_stream_url=html_escape(initial_url),
        poster_html=poster_html,
        year_badge=year_badge,
        rating_badge=rating_badge,
        genres_info=genres_info,
        overview_text=overview_text,
        servers_json=json.dumps(servers),
        sponsor_banner_html=sponsor_banner_html
    )
    return web.Response(text=html, content_type="text/html")


def get_client_ip(request: web.Request) -> str:
    """Accurately extract client's real public IP behind Cloudflare, Nginx, or direct VPS."""
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    x_forwarded = request.headers.get("X-Forwarded-For")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return getattr(request, "remote", None) or "127.0.0.1"


STREMIO_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Content-Type": "application/json; charset=utf-8"
}


async def stremio_options_handler(request: web.Request):
    """Handle CORS preflight requests for Stremio players."""
    return web.Response(status=200, headers=STREMIO_CORS_HEADERS)



async def stremio_install_handler(request: web.Request):
    """Handle 1-click Stremio installation bridge from Telegram button without BUTTON_URL_INVALID."""
    token = request.match_info.get("token")
    base_url = get_stream_base_url(request)
    host_no_scheme = base_url.replace("https://", "").replace("http://", "")
    stremio_deep_url = f"stremio://{host_no_scheme}/stremio/{token}/manifest.json"
    manifest_https_url = f"{base_url}/stremio/{token}/manifest.json"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Installing AkMovieVerse VIP Addon...</title>
    <meta http-equiv="refresh" content="0;url={stremio_deep_url}">
    <script>
        window.location.href = "{stremio_deep_url}";
    </script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #07090e;
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
            text-align: center;
        }}
        .card {{
            background: rgba(18, 24, 38, 0.85);
            border: 1px solid rgba(56, 189, 248, 0.3);
            border-radius: 20px;
            padding: 30px 24px;
            max-width: 480px;
            width: 100%;
            box-shadow: 0 16px 40px rgba(0,0,0,0.8);
        }}
        .icon {{ font-size: 42px; margin-bottom: 12px; }}
        h2 {{ color: #38bdf8; font-size: 20px; margin-bottom: 8px; }}
        p {{ color: #94a3b8; font-size: 14px; line-height: 1.5; margin-bottom: 20px; }}
        .btn {{
            display: inline-block;
            background: linear-gradient(135deg, #0284c7, #2563eb);
            color: #ffffff;
            font-weight: 700;
            text-decoration: none;
            padding: 12px 24px;
            border-radius: 12px;
            font-size: 15px;
            transition: transform 0.15s;
        }}
        .btn:active {{ transform: scale(0.97); }}
        .manifest-box {{
            margin-top: 24px;
            background: rgba(0,0,0,0.5);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px;
            padding: 10px;
            font-family: monospace;
            font-size: 11px;
            color: #38bdf8;
            word-break: break-all;
            user-select: all;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">📺</div>
        <h2>Opening Stremio App...</h2>
        <p>If the Stremio app didn't open automatically on your device, tap the button below:</p>
        <a href="{stremio_deep_url}" class="btn">📲 Open in Stremio App</a>
        <div class="manifest-box">{manifest_https_url}</div>
    </div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def stremio_manifest_handler(request: web.Request):
    """Serve Stremio Addon manifest JSON with VIP authentication check."""
    token = request.match_info.get("token")
    from database.stremio import verify_stremio_access

    is_ok, reason, _ = await verify_stremio_access(token, client_ip=None)
    if not is_ok:
        manifest = {
            "id": "org.akmovieverse.stream",
            "version": "1.0.0",
            "name": "AkMovieVerse (VIP Required)",
            "description": f"Access Denied: {reason}. Renew or get VIP access on Telegram bot.",
            "resources": [],
            "types": ["movie", "series"],
            "catalogs": []
        }
    else:
        manifest = {
            "id": "org.akmovieverse.stream",
            "version": "1.0.0",
            "name": "AkMovieVerse VIP",
            "description": "High-Speed Direct Cloud Streaming for Movies & Series from AkMovieVerse Telegram Library.",
            "resources": ["stream"],
            "types": ["movie", "series"],
            "idPrefixes": ["tt"],
            "catalogs": []
        }

    return web.Response(
        text=json.dumps(manifest),
        headers=STREMIO_CORS_HEADERS
    )


async def stremio_stream_handler(request: web.Request):
    """Resolve and return direct stream URLs for Stremio by IMDb ID with 1-IP concurrency protection."""
    token = request.match_info.get("token")
    media_type = request.match_info.get("media_type", "movie")
    raw_id = request.match_info.get("item_id", "")

    # Strip optional .json extension from item_id
    item_id = raw_id[:-5] if raw_id.endswith(".json") else raw_id

    client_ip = get_client_ip(request)
    from database.stremio import verify_stremio_access
    is_ok, reason, _ = await verify_stremio_access(token, client_ip=client_ip)

    if not is_ok:
        err_stream = {
            "name": f"AkMovieVerse\n⚠️ {reason[:20]}",
            "title": f"⚠️ {reason}\nRenew or check your VIP status on @AkMovieVerseBot",
            "externalUrl": getattr(Config, "CHANNEL_URL", None) or "https://t.me/AkMovieVerse"
        }
        return web.Response(
            text=json.dumps({"streams": [err_stream]}),
            headers=STREMIO_CORS_HEADERS
        )

    season, episode = None, None
    if ":" in item_id:
        parts = item_id.split(":")
        imdb_id = parts[0]
        try:
            season = int(parts[1])
            episode = int(parts[2])
        except (IndexError, ValueError):
            pass
    else:
        imdb_id = item_id

    from utils.online_stream import get_meta_by_imdb
    meta = await get_meta_by_imdb(imdb_id, media_type=media_type)
    title = meta.get("title") if meta else None
    year = meta.get("year") if meta else None

    streams = []
    base_url = get_stream_base_url(request)

    candidate_titles = []
    if meta:
        main_title = meta.get("title")
        if main_title:
            candidate_titles.append(main_title)
        for at in meta.get("alt_titles", []):
            if at and at not in candidate_titles:
                candidate_titles.append(at)

    def matches_series_doc(file_name: str, req_season: int, req_episode: int) -> tuple[bool, str]:
        fn = file_name.lower()

        # 1. Season validation: if another season is explicitly named, skip
        seasons_found = [int(s) for s in re.findall(r'(?<![a-z])(?:s|season)\s*0?(\d+)(?=[e\s\.\-_]|)', fn)]
        if seasons_found and req_season not in seasons_found:
            return False, ""

        # 2. Episode range validation e.g. E01-07, E08-E13, [01-08], E01~E12
        range_match = re.search(r'(?<![a-z])(?:e|ep)?\s*0?(\d{1,3})\s*[-~_to]\s*(?:e|ep)?\s*0?(\d{1,3})', fn)
        if range_match:
            start_ep = int(range_match.group(1))
            end_ep = int(range_match.group(2))
            if start_ep < end_ep and end_ep <= 1000:
                if start_ep <= req_episode <= end_ep:
                    return True, f" • Pack [E{start_ep:02d}-E{end_ep:02d}]"
                else:
                    return False, ""

        # 3. Single episode validation e.g. S01E01, E01, EP01, Episode 1
        eps_found = [int(e) for e in re.findall(r'(?<![a-z])(?:e|ep|episode)\s*0?(\d+)(?=[\s\.\-_]|)', fn)]
        if eps_found:
            if req_episode in eps_found:
                return True, ""
            else:
                return False, ""

        # 4. Complete / Combined Season Packs
        if any(k in fn for k in ["combined", "complete", "batch", "pack", "full season", "all episodes"]):
            return True, " • Full Season Combined"

        # 5. Full season files with season tag
        if seasons_found and req_season in seasons_found:
            return True, " • Season Pack"

        return True, ""

    if candidate_titles:
        queries = []
        is_series_request = (season is not None and episode is not None)

        for t in candidate_titles:
            clean_t = re.sub(r"[:\-_/\'\"]", " ", t).strip()
            clean_t = re.sub(r"[:\-_/\'\"]", " ", t).strip()

            if is_series_request:
                # Exact episode queries
                queries.append(f"{t} S{season:02d}E{episode:02d}")
                queries.append(f"{t} S{season} E{episode}")
                queries.append(f"{t} E{episode:02d}")
                queries.append(f"{clean_t} S{season:02d}E{episode:02d}")

                # Season batch, combined files, and complete packs
                queries.append(f"{t} S{season:02d} COMBINED")
                queries.append(f"{t} S{season:02d}")
                queries.append(f"{clean_t} S{season:02d}")
                queries.append(f"{t} COMPLETE")
                queries.append(f"{t} Season {season}")
                queries.append(f"{t}")
            else:
                if year:
                    queries.append(f"{t} {year}")
                queries.append(t)
                if clean_t != t:
                    queries.append(clean_t)

        matched_docs = []
        seen_file_ids = set()

        for q in queries:
            try:
                found = await get_search_results(q, limit=20)
                for doc in found:
                    fid = doc.get("file_unique_id") or str(doc.get("_id"))
                    if fid not in seen_file_ids:
                        f_name = doc.get("file_name", "")
                        if is_series_request:
                            is_match, pack_note = matches_series_doc(f_name, season, episode)
                            if not is_match:
                                continue
                            doc["_pack_note"] = pack_note
                        else:
                            doc["_pack_note"] = ""

                        seen_file_ids.add(fid)
                        matched_docs.append(doc)
            except Exception as e_search:
                logger.debug(f"Stremio DB search error for query {q}: {e_search}")

            if len(matched_docs) >= 20:
                break

        for doc in matched_docs:
            f_name = doc.get("file_name", "Video.mp4")
            f_size = doc.get("file_size", 0)
            f_uid = doc.get("file_unique_id") or str(doc.get("_id"))
            readable_size = get_readable_size(f_size)
            pack_note = doc.get("_pack_note", "")

            q_tag = "1080p FHD"
            f_lower = f_name.lower()
            if "2160p" in f_lower or "4k" in f_lower:
                q_tag = "4K UHD"
            elif "1080p" in f_lower:
                q_tag = "1080p FHD"
            elif "720p" in f_lower:
                q_tag = "720p HD"
            elif "540p" in f_lower:
                q_tag = "540p SD"
            elif "480p" in f_lower or "360p" in f_lower:
                q_tag = "480p SD"

            audio_tag = ""
            if any(k in f_lower for k in ("dual", "multi", "hindi", "korean", "japanese", "tamil", "telugu")):
                if "multi" in f_lower:
                    audio_tag = " • Multi Audio"
                elif "dual" in f_lower:
                    audio_tag = " • Dual Audio"
                elif "hindi" in f_lower:
                    audio_tag = " • Hindi"
                elif "korean" in f_lower:
                    audio_tag = " • Korean"
                elif "japanese" in f_lower:
                    audio_tag = " • Japanese"

            stream_url = f"{base_url}/stream/{f_uid}/{urllib.parse.quote(f_name)}?token={token}"

            streams.append({
                "name": f"AkMovieVerse VIP\n{q_tag} | {readable_size}",
                "title": f"🎬 {f_name}\n⚡ Fast VIP Cloud Stream{pack_note}{audio_tag}",
                "url": stream_url
            })

    return web.Response(
        text=json.dumps({"streams": streams}),
        headers=STREMIO_CORS_HEADERS
    )


async def web_spin_handler(request: web.Request) -> web.Response:
    """Serve the Flixify 3D Lucky Wheel Telegram Mini App (WebApp)."""
    uid_str = request.query.get("uid", "").strip()
    token = request.query.get("tok", "").strip()

    try:
        user_id = int(uid_str)
    except (ValueError, TypeError):
        return web.Response(
            text="<h3>⛔ Access Denied</h3><p>Missing or invalid user ID. Open /spin in your bot chat.</p>",
            content_type="text/html",
            status=403
        )

    from plugins.spin import verify_spin_token
    if not verify_spin_token(user_id, token):
        return web.Response(
            text="<h3>⛔ Session Invalid or Expired</h3><p>Please open /spin in your bot chat to generate a fresh session link.</p>",
            content_type="text/html",
            status=403
        )

    from database.loyalty import can_spin_today, record_daily_activity
    from utils.spin_webapp import render_spin_webapp

    # Advance daily activity streak
    profile = await record_daily_activity(user_id)
    allowed, spin_type, ref_spins, cooldown_secs = await can_spin_today(user_id)

    # Fetch user's first name from bot client cache if available
    user_name = "Player"
    client = getattr(Config, "MASTER_CLIENT", None)
    if client:
        try:
            tg_user = await client.get_users(user_id)
            if tg_user and getattr(tg_user, "first_name", None):
                user_name = tg_user.first_name
        except Exception:
            pass

    html = render_spin_webapp(
        user_id=user_id,
        token=token,
        user_name=user_name,
        profile=profile,
        allowed=allowed,
        cooldown_secs=cooldown_secs
    )
    return web.Response(text=html, content_type="text/html")


async def web_spin_roll_api(request: web.Request) -> web.Response:
    """Backend API to resolve an authorized wheel spin under server-side probability gate."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON body"}, status=400)

    try:
        user_id = int(body.get("uid", 0))
    except (ValueError, TypeError):
        return web.json_response({"success": False, "error": "Invalid user ID"}, status=400)

    token = str(body.get("tok", "")).strip()

    from plugins.spin import verify_spin_token, execute_spin_roll
    if not verify_spin_token(user_id, token):
        return web.json_response({"success": False, "error": "Invalid or expired session token"}, status=403)

    user_name = "Player"
    client = getattr(Config, "MASTER_CLIENT", None)
    if client:
        try:
            tg_user = await client.get_users(user_id)
            if tg_user and getattr(tg_user, "first_name", None):
                user_name = tg_user.first_name
        except Exception:
            pass

    success, msg, details = await execute_spin_roll(client, user_id, user_name)
    if not success:
        return web.json_response({
            "success": False,
            "error": "Cooldown active or spin already consumed",
            "reason": msg,
            "details": details
        })

    return web.json_response({
        "success": True,
        "target_segment": details.get("target_segment", 0),
        "prize_type": details.get("prize_type", "coins"),
        "prize_val": details.get("prize_val", 5),
        "item_title": details.get("item_title", "Reward"),
        "new_balance": details.get("new_balance", 0),
        "streak": details.get("streak", 1),
        "rank": details.get("rank", "🌟 Newbie"),
        "result_text": msg
    })


def format_galaxy_item(item: dict, bot_username: str, poster_url: str = "") -> dict:
    """Format catalog item with complete episodes, qualities, and bot deep links for 3D MovieVerse."""
    import urllib.parse
    clean = item.get("clean_name", "")
    title = item.get("title", clean)
    is_series = bool(item.get("is_series", False))
    total_sz = get_readable_size(int(item.get("total_size", 0))) if item.get("total_size") else ""

    encoded_clean = urllib.parse.quote_plus(clean)
    bot_url = f"https://t.me/{bot_username}?start=filter_{encoded_clean}"

    # Build quality-specific download buttons for quick summary
    qual_files = []
    seen_quals = set()
    files_list = item.get("files", [])

    for f in files_list:
        meta = parse_media_metadata(f.get("file_name", ""))
        q = meta.get("quality") or "HD"
        if q not in seen_quals:
            seen_quals.add(q)
            f_uid = f.get("file_unique_id") or str(f.get("_id"))
            f_sz = get_readable_size(int(f.get("file_size", 0)))
            qual_files.append({
                "quality": q,
                "size": f_sz,
                "bot_url": f"https://t.me/{bot_username}?start=file_{f_uid}"
            })

    q_rank = {"2160p": 5, "4k": 5, "1080p": 4, "720p": 3, "540p": 2, "480p": 1}
    qual_files.sort(key=lambda x: q_rank.get(x["quality"].lower(), 0), reverse=True)

    # Detailed Movie Files
    movie_files = []
    if not is_series:
        for f in files_list:
            f_uid = f.get("file_unique_id") or str(f.get("_id"))
            f_meta = parse_media_metadata(f.get("file_name", ""))
            f_qual = f_meta.get("quality") or "HD"
            f_sz = get_readable_size(int(f.get("file_size", 0)))
            part_lbl = f_meta.get("part_label") or ""
            movie_files.append({
                "quality": f_qual,
                "part_label": part_lbl,
                "size": f_sz,
                "file_name": f.get("file_name", "Movie Print"),
                "bot_url": f"https://t.me/{bot_username}?start=file_{f_uid}"
            })
        movie_files.sort(key=lambda x: q_rank.get(x["quality"].lower(), 0), reverse=True)

    # Detailed Episodes & Packs for Series
    episodes = []
    packs = []
    if is_series:
        if item.get("episodes_map"):
            for ep_num in sorted(item["episodes_map"].keys()):
                for ef in item["episodes_map"][ep_num]:
                    ef_uid = ef.get("file_unique_id") or str(ef.get("_id"))
                    ef_meta = parse_media_metadata(ef.get("file_name", ""))
                    ef_qual = ef_meta.get("quality") or "HD"
                    ef_sz = get_readable_size(int(ef.get("file_size", 0)))
                    episodes.append({
                        "episode": ep_num,
                        "quality": ef_qual,
                        "size": ef_sz,
                        "file_name": ef.get("file_name", f"Episode {ep_num}"),
                        "bot_url": f"https://t.me/{bot_username}?start=file_{ef_uid}"
                    })

        if item.get("combined_files"):
            for pf in item["combined_files"]:
                pf_uid = pf.get("file_unique_id") or str(pf.get("_id"))
                pf_meta = parse_media_metadata(pf.get("file_name", ""))
                pf_qual = pf_meta.get("quality") or "HD"
                pf_sz = get_readable_size(int(pf.get("file_size", 0)))
                packs.append({
                    "title": f"Season {item.get('season', 1)} Complete Pack",
                    "quality": pf_qual,
                    "size": pf_sz,
                    "file_name": pf.get("file_name", "Season Pack"),
                    "bot_url": f"https://t.me/{bot_username}?start=file_{pf_uid}"
                })

    p_url = poster_url or item.get("poster_url") or ""
    storyline = f"Get verified high-definition releases of {title} with multi-audio and instant Telegram bot delivery."
    if is_series:
        storyline = f"Explore complete season episodes and packs of {title} in crystal clear HD audio and video prints."

    return {
        "title": title,
        "clean_name": clean,
        "is_series": is_series,
        "poster_url": p_url,
        "backdrop_url": p_url,
        "year": item.get("year"),
        "rating": "8.2",
        "storyline": storyline,
        "total_size": total_sz,
        "qualities": item.get("sorted_qualities", []),
        "languages": item.get("languages_list", []),
        "bot_url": bot_url,
        "quality_files": qual_files,
        "movie_files": movie_files,
        "episodes": episodes,
        "packs": packs
    }


async def search_galaxy_catalog(query: str = "", limit: int = 30) -> list:
    """Search catalog items or MongoDB documents for 3D MovieVerse display."""
    all_catalog = await get_grouped_catalog()
    matching_items = []

    if query:
        q_clean = query.lower()
        for item in all_catalog:
            if q_clean in item.get("title", "").lower() or q_clean in item.get("clean_name", "").lower():
                matching_items.append(item)

        if len(matching_items) < 8:
            tokens = [re.escape(t) for t in query.split() if len(t) >= 2]
            if tokens:
                mongo_filter = {"$and": [{"file_name": {"$regex": t, "$options": "i"}} for t in tokens]}
                try:
                    direct_docs = await mongo.files.find(mongo_filter).sort("_id", -1).limit(40).to_list(40)
                    if direct_docs:
                        existing_keys = {item["key"] for item in matching_items}
                        extra_groups = _group_file_docs(direct_docs)
                        for g in extra_groups:
                            if g["key"] not in existing_keys:
                                matching_items.append(g)
                except Exception as e:
                    logger.debug(f"Direct galaxy search error: {e}")
    else:
        matching_items = all_catalog[:limit]

    return matching_items[:limit]


async def galaxy_search_api(request: web.Request) -> web.Response:
    """Live search API for MovieVerse 3D WebApp."""
    q = request.query.get("q", "").strip()
    bot_username = Config.BOT_USERNAME or "bot"

    matching_items = await search_galaxy_catalog(q, limit=28)
    posters = await asyncio.gather(*[
        get_cached_poster_url(item.get("clean_name", ""), year=item.get("year"), is_series=item.get("is_series"))
        for item in matching_items
    ], return_exceptions=True)

    results = []
    for item, poster in zip(matching_items, posters):
        p_url = poster if isinstance(poster, str) and poster else ""
        results.append(format_galaxy_item(item, bot_username, p_url))

    return web.json_response({
        "status": "ok",
        "query": q,
        "count": len(results),
        "results": results
    })


async def galaxy_handler(request: web.Request) -> web.Response:
    """Serve the 3D MovieVerse interactive WebGL space experience with direct bot file delivery."""
    base_url = get_stream_base_url(request)
    bot_username = Config.BOT_USERNAME or "bot"
    q = request.query.get("q", "").strip()

    matching_items = await search_galaxy_catalog(q, limit=28)
    posters = await asyncio.gather(*[
        get_cached_poster_url(item.get("clean_name", ""), year=item.get("year"), is_series=item.get("is_series"))
        for item in matching_items
    ], return_exceptions=True)

    enriched_items = []
    for item, poster in zip(matching_items, posters):
        p_url = poster if isinstance(poster, str) and poster else ""
        enriched_items.append(format_galaxy_item(item, bot_username, p_url))

    from utils.galaxy_movieverse import render_galaxy_movieverse
    html = render_galaxy_movieverse(
        items=enriched_items,
        base_url=base_url,
        bot_username=bot_username,
        initial_query=q
    )
    return web.Response(text=html, content_type="text/html")


async def run_web_server():
    """Start background aiohttp server with health check, verification, and streaming routes."""
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/verify/{token}", verify_redirect_handler)

    # 3D Galaxy Movieverse Routes
    app.router.add_get("/galaxy", galaxy_handler)
    app.router.add_get("/galaxy/", galaxy_handler)
    app.router.add_get("/api/galaxy/search", galaxy_search_api)

    # Flixify 3D Lucky Wheel Telegram Mini App Routes
    app.router.add_get("/spin", web_spin_handler)
    app.router.add_get("/spin/", web_spin_handler)
    app.router.add_post("/api/spin/roll", web_spin_roll_api)
    app.router.add_route("OPTIONS", "/api/spin/roll", options_handler)

    # Fast Streaming & Web Player Routes
    app.router.add_get("/stream/{file_unique_id}", stream_handler)
    app.router.add_get("/stream/{file_unique_id}/{file_name}", stream_handler)
    app.router.add_head("/stream/{file_unique_id}", stream_handler)
    app.router.add_head("/stream/{file_unique_id}/{file_name}", stream_handler)
    app.router.add_route("OPTIONS", "/stream/{file_unique_id}", options_handler)
    app.router.add_route("OPTIONS", "/stream/{file_unique_id}/{file_name}", options_handler)
    app.router.add_get("/download/{file_unique_id}", stream_handler)
    app.router.add_get("/download/{file_unique_id}/{file_name}", stream_handler)
    app.router.add_head("/download/{file_unique_id}", stream_handler)
    app.router.add_head("/download/{file_unique_id}/{file_name}", stream_handler)
    app.router.add_get("/watch/{file_unique_id}", watch_handler)
    app.router.add_get("/watch_online/{imdb_id}", watch_online_handler)
    app.router.add_get("/browse", browse_handler)
    app.router.add_get("/browse/", browse_handler)
    app.router.add_get("/post/{item_slug}", post_handler)
    app.router.add_get("/post/{item_slug}/", post_handler)
    app.router.add_get("/series/{series_slug}", series_handler)
    app.router.add_get("/series/{series_slug}/", series_handler)
    app.router.add_get("/playlist/{file_unique_id}.m3u", playlist_handler)
    app.router.add_get("/player/mx/{file_unique_id}", mx_redirect_handler)
    app.router.add_get("/player/vlc/{file_unique_id}", vlc_redirect_handler)
    app.router.add_get("/player/open/{file_unique_id}", chooser_redirect_handler)

    # Official Stremio v3 VIP Addon Routes
    app.router.add_get("/stremio/{token}/install", stremio_install_handler)
    app.router.add_get("/stremio/{token}/manifest.json", stremio_manifest_handler)
    app.router.add_route("OPTIONS", "/stremio/{token}/manifest.json", stremio_options_handler)
    app.router.add_get("/stremio/{token}/stream/{media_type}/{item_id}", stremio_stream_handler)
    app.router.add_route("OPTIONS", "/stremio/{token}/stream/{media_type}/{item_id}", stremio_options_handler)

    # Pre-warm media catalog cache in background for instant < 10ms browse page loads
    asyncio.create_task(get_grouped_catalog())

    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "0.0.0.0", Config.PORT, reuse_address=True)
        await site.start()
        logger.info(f"Health-check, Verification & Streaming web server successfully bound to port {Config.PORT}")
    except OSError as e_bind:
        if getattr(e_bind, "errno", None) == 98 or "already in use" in str(e_bind).lower():
            logger.error(
                f"❌ Port {Config.PORT} is already occupied! Another bot process is running in background. "
                f"Run 'fuser -k {Config.PORT}/tcp' or 'pkill -9 -f bot.py' to release it."
            )
        else:
            logger.error(f"Failed to bind web server on port {Config.PORT}: {e_bind}")
