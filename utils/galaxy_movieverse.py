"""Flixify / AkMovieVerse 3D — Futuristic 3D Cinema Showcase & File Delivery Mini App.
Features:
1. Hero 3D Card Mode for single searched titles with interactive 3D parallax tilt & cosmic aura.
2. CineFlow 3D Horizontal Slider for multi-title browsing with zero card clipping / overlap.
3. Top Brand Header with centered full-width search bar below it.
4. Vertical optical centering of cards.
5. Rich Full-Screen Cinema Post Modal on tap with complete episodes, season packs, and quality prints.
6. Pinned non-intrusive bottom delivery button that never blocks scrollable content.
7. High-res graceful canvas fallback posters with zero missing images.
"""

import json
from html import escape as html_escape

GALAXY_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>MovieVerse 3D — Futuristic Cinema & File Delivery</title>
    <!-- Telegram Mini App SDK -->
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <!-- Three.js 3D WebGL Engine -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            -webkit-tap-highlight-color: transparent;
            user-select: none;
            -webkit-user-select: none;
        }

        body, html {
            width: 100%;
            height: 100%;
            overflow: hidden;
            background: #04060c;
            color: #ffffff;
        }

        #webglCanvas {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 1;
        }

        /* Ambient Cosmic Vignette */
        .vignette-overlay {
            position: fixed;
            inset: 0;
            pointer-events: none;
            background: radial-gradient(circle at 50% 45%, transparent 25%, rgba(4, 6, 12, 0.65) 70%, #04060c 100%);
            z-index: 2;
        }

        /* Top HUD Navigation Bar */
        .top-nav {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 20;
            padding: 14px 16px 12px 16px;
            display: flex;
            flex-direction: column;
            align-items: center;
            background: linear-gradient(180deg, rgba(4, 6, 12, 0.96) 0%, rgba(4, 6, 12, 0.7) 75%, rgba(4, 6, 12, 0) 100%);
        }

        .brand-title {
            font-size: 17px;
            font-weight: 900;
            color: #f43f5e;
            letter-spacing: 0.8px;
            text-shadow: 0 0 20px rgba(244, 63, 94, 0.65);
            display: flex;
            align-items: center;
            gap: 7px;
            margin-bottom: 10px;
        }

        /* Full-Width Search Bar directly beneath Brand */
        .search-box-wrap {
            position: relative;
            width: 100%;
            max-width: 440px;
        }

        .search-input {
            width: 100%;
            background: rgba(15, 20, 32, 0.88);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border: 1px solid rgba(244, 63, 94, 0.35);
            border-radius: 22px;
            padding: 9px 36px 9px 38px;
            color: #ffffff;
            font-size: 13px;
            font-weight: 600;
            outline: none;
            transition: all 0.25s ease;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
            user-select: auto;
            -webkit-user-select: auto;
        }

        .search-input:focus {
            border-color: #f43f5e;
            box-shadow: 0 0 20px rgba(244, 63, 94, 0.5);
            background: rgba(18, 25, 42, 0.96);
        }

        .search-input::placeholder {
            color: #64748b;
            font-weight: 500;
        }

        .search-icon-left {
            position: absolute;
            left: 13px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 13px;
            pointer-events: none;
            opacity: 0.75;
        }

        .search-clear-btn {
            position: absolute;
            right: 11px;
            top: 50%;
            transform: translateY(-50%);
            background: rgba(255, 255, 255, 0.15);
            border: none;
            color: #cbd5e1;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            display: none;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            cursor: pointer;
        }

        .search-spinner {
            position: absolute;
            right: 36px;
            top: 50%;
            transform: translateY(-50%);
            width: 13px;
            height: 13px;
            border: 2px solid rgba(244, 63, 94, 0.3);
            border-top-color: #f43f5e;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            display: none;
        }

        @keyframes spin {
            to { transform: translateY(-50%) rotate(360deg); }
        }

        /* Bottom Floating Prompt Pill */
        .bottom-hint-bar {
            position: fixed;
            bottom: 22px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 20;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 7px;
            width: 100%;
            max-width: 360px;
            padding: 0 16px;
            pointer-events: none;
            transition: opacity 0.25s ease;
        }

        .movie-title-preview {
            font-size: 16px;
            font-weight: 800;
            color: #ffffff;
            text-shadow: 0 2px 14px rgba(0, 0, 0, 0.95);
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            text-align: center;
        }

        .hud-sub-badges {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            flex-wrap: wrap;
        }

        .hud-pill {
            font-size: 10.5px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 6px;
            background: rgba(15, 23, 42, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #94a3b8;
        }

        .hud-pill-gold {
            color: #fbbf24;
            border-color: rgba(245, 158, 11, 0.4);
            background: rgba(245, 158, 11, 0.15);
        }

        .hud-pill-cyan {
            color: #38bdf8;
            border-color: rgba(56, 189, 248, 0.4);
            background: rgba(56, 189, 248, 0.15);
        }

        .hud-actions-row {
            display: flex;
            align-items: center;
            gap: 8px;
            pointer-events: auto;
        }

        .tap-prompt-badge {
            background: linear-gradient(135deg, rgba(244, 63, 94, 0.3) 0%, rgba(225, 29, 72, 0.45) 100%);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(244, 63, 94, 0.55);
            color: #ffffff;
            font-size: 11.5px;
            font-weight: 800;
            padding: 7px 15px;
            border-radius: 20px;
            box-shadow: 0 4px 20px rgba(244, 63, 94, 0.35);
            display: flex;
            align-items: center;
            gap: 6px;
            animation: pulseTap 2s infinite ease-in-out;
            cursor: pointer;
        }

        .share-prompt-badge {
            background: rgba(56, 189, 248, 0.2);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(56, 189, 248, 0.45);
            color: #38bdf8;
            font-size: 11.5px;
            font-weight: 800;
            padding: 7px 14px;
            border-radius: 20px;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
            display: flex;
            align-items: center;
            gap: 5px;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .share-prompt-badge:active {
            transform: scale(0.95);
            background: rgba(56, 189, 248, 0.35);
        }

        @keyframes pulseTap {
            0% { transform: scale(0.98); opacity: 0.9; box-shadow: 0 0 10px rgba(244, 63, 94, 0.2); }
            50% { transform: scale(1.02); opacity: 1; box-shadow: 0 0 24px rgba(244, 63, 94, 0.5); }
            100% { transform: scale(0.98); opacity: 0.9; box-shadow: 0 0 10px rgba(244, 63, 94, 0.2); }
        }

        /* ------------------------------------------------------------- */
        /* FULL-SCREEN CINEMA POST MODAL (Rock-Solid Flex Viewport Shell) */
        /* ------------------------------------------------------------- */
        .cinema-post-modal {
            position: fixed;
            inset: 0;
            z-index: 100;
            background: #060911;
            color: #f1f5f9;
            display: flex;
            flex-direction: column;
            height: 100vh;
            height: 100dvh;
            overflow: hidden;
            opacity: 0;
            pointer-events: none;
            transform: translateY(100%);
            transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .cinema-post-modal.active {
            opacity: 1;
            pointer-events: auto;
            transform: translateY(0);
        }

        /* 1. Pinned Top Bar */
        .modal-top-bar {
            flex-shrink: 0;
            z-index: 50;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 13px 18px;
            background: rgba(10, 14, 24, 0.95);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }

        .modal-brand {
            font-size: 14.5px;
            font-weight: 800;
            color: #f43f5e;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .modal-top-actions {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .modal-share-icon-btn {
            background: rgba(56, 189, 248, 0.15);
            border: 1px solid rgba(56, 189, 248, 0.35);
            color: #38bdf8;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s ease;
        }

        .modal-share-icon-btn:active {
            transform: scale(0.9);
            background: rgba(56, 189, 248, 0.35);
        }

        .modal-close-btn {
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: #ffffff;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 14px;
            font-weight: 700;
            transition: all 0.2s ease;
        }

        .modal-close-btn:active {
            transform: scale(0.9);
            background: rgba(244, 63, 94, 0.35);
        }

        /* 2. Scrollable Middle Area */
        .modal-scroll-area {
            flex: 1;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
            padding-bottom: 24px;
        }

        /* Hero Backdrop & Poster Banner */
        .modal-hero {
            position: relative;
            padding: 22px 16px 20px 16px;
            display: flex;
            flex-direction: column;
            align-items: center;
            overflow: hidden;
        }

        .modal-backdrop-img {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            object-fit: cover;
            filter: blur(34px) brightness(0.25) saturate(1.4);
            transform: scale(1.2);
            z-index: 1;
        }

        .modal-hero-content {
            position: relative;
            z-index: 2;
            width: 100%;
            max-width: 480px;
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
        }

        .modal-poster-wrap {
            width: 165px;
            aspect-ratio: 2/3;
            border-radius: 14px;
            overflow: hidden;
            border: 1px solid rgba(255, 255, 255, 0.2);
            box-shadow: 0 16px 36px rgba(0, 0, 0, 0.85), 0 0 25px rgba(244, 63, 94, 0.25);
            background: #0f172a;
            margin-bottom: 12px;
        }

        .modal-poster-img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }

        .modal-title {
            font-size: 19px;
            font-weight: 900;
            color: #ffffff;
            line-height: 1.3;
            margin-bottom: 8px;
            text-shadow: 0 2px 10px rgba(0, 0, 0, 0.8);
        }

        .modal-badges-row {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 6px;
            margin-bottom: 12px;
        }

        .badge-pill {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 4px 10px;
            border-radius: 8px;
            font-size: 11.5px;
            font-weight: 700;
            border: 1px solid rgba(255, 255, 255, 0.1);
            background: rgba(18, 24, 38, 0.85);
            color: #e2e8f0;
        }

        .badge-pill-rating {
            background: rgba(245, 158, 11, 0.2);
            border-color: rgba(245, 158, 11, 0.45);
            color: #fbbf24;
        }

        .badge-pill-type {
            background: rgba(168, 85, 247, 0.2);
            border-color: rgba(168, 85, 247, 0.45);
            color: #c084fc;
        }

        .badge-pill-audio {
            background: rgba(16, 185, 129, 0.2);
            border-color: rgba(16, 185, 129, 0.45);
            color: #34d399;
        }

        .badge-pill-size {
            background: rgba(56, 189, 248, 0.2);
            border-color: rgba(56, 189, 248, 0.45);
            color: #38bdf8;
        }

        .modal-storyline {
            font-size: 12.5px;
            line-height: 1.5;
            color: #cbd5e1;
            font-style: italic;
            background: rgba(15, 23, 42, 0.65);
            border-left: 3px solid #f43f5e;
            padding: 8px 12px;
            border-radius: 0 10px 10px 0;
            margin-top: 4px;
            text-align: left;
            width: 100%;
        }

        /* Content Section: Prints or Episodes */
        .modal-body {
            padding: 14px 18px 24px 18px;
            width: 100%;
            max-width: 600px;
            margin: 0 auto;
        }

        .section-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 12px;
        }

        .section-title {
            font-size: 13.5px;
            font-weight: 800;
            color: #fbbf24;
            display: flex;
            align-items: center;
            gap: 6px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .section-subtitle {
            font-size: 11px;
            color: #94a3b8;
            font-weight: 600;
        }

        /* Print / Episode Glassmorphic Cards */
        .items-grid {
            display: flex;
            flex-direction: column;
            gap: 9px;
            margin-bottom: 20px;
        }

        .item-card {
            background: rgba(20, 26, 42, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px;
            padding: 12px 14px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            transition: all 0.2s ease;
        }

        .item-card:active {
            background: rgba(28, 38, 62, 0.95);
            border-color: rgba(56, 189, 248, 0.5);
            transform: scale(0.99);
        }

        .item-info {
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
        }

        .quality-tag {
            padding: 5px 9px;
            border-radius: 8px;
            font-size: 11px;
            font-weight: 900;
            flex-shrink: 0;
            background: rgba(244, 63, 94, 0.2);
            color: #f43f5e;
            border: 1px solid rgba(244, 63, 94, 0.35);
        }

        .quality-tag-4k {
            background: rgba(245, 158, 11, 0.25);
            color: #fbbf24;
            border-color: rgba(245, 158, 11, 0.45);
        }

        .quality-tag-1080 {
            background: rgba(56, 189, 248, 0.2);
            color: #38bdf8;
            border-color: rgba(56, 189, 248, 0.4);
        }

        .quality-tag-720 {
            background: rgba(16, 185, 129, 0.2);
            color: #34d399;
            border-color: rgba(16, 185, 129, 0.4);
        }

        .item-details {
            min-width: 0;
        }

        .item-name {
            font-size: 13px;
            font-weight: 700;
            color: #ffffff;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .item-sub {
            font-size: 11px;
            color: #94a3b8;
            font-weight: 600;
            margin-top: 2px;
        }

        .btn-download-action {
            background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
            border: 1px solid rgba(56, 189, 248, 0.4);
            color: #ffffff;
            font-size: 12px;
            font-weight: 800;
            padding: 8px 14px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
            flex-shrink: 0;
            box-shadow: 0 4px 12px rgba(2, 132, 199, 0.35);
            transition: all 0.15s ease;
        }

        .btn-download-action:active {
            transform: scale(0.95);
        }

        /* 3. Pinned Bottom Action Bar (Forever Anchored at Bottom, NEVER Floats in Middle) */
        .modal-bottom-bar {
            flex-shrink: 0;
            position: relative;
            z-index: 60;
            padding: 12px 18px max(14px, env(safe-area-inset-bottom)) 18px;
            background: rgba(10, 14, 24, 0.98);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-top: 1px solid rgba(255, 255, 255, 0.12);
            box-shadow: 0 -12px 35px rgba(0, 0, 0, 0.92);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 7px;
        }

        .modal-action-buttons {
            width: 100%;
            max-width: 500px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .btn-all-in-bot {
            flex: 1;
            padding: 13px;
            border-radius: 14px;
            border: none;
            background: linear-gradient(135deg, #f43f5e 0%, #e11d48 50%, #be123c 100%);
            color: #ffffff;
            font-size: 13.5px;
            font-weight: 800;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            cursor: pointer;
            box-shadow: 0 6px 22px rgba(225, 29, 72, 0.45);
            text-decoration: none;
            transition: transform 0.15s ease;
            white-space: nowrap;
        }

        .btn-all-in-bot:active {
            transform: scale(0.97);
        }

        .btn-share-movie {
            flex: 0 0 auto;
            padding: 13px 18px;
            border-radius: 14px;
            border: 1px solid rgba(56, 189, 248, 0.45);
            background: linear-gradient(135deg, rgba(2, 132, 199, 0.35) 0%, rgba(37, 99, 235, 0.5) 100%);
            color: #38bdf8;
            font-size: 13px;
            font-weight: 800;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            cursor: pointer;
            box-shadow: 0 4px 16px rgba(2, 132, 199, 0.25);
            white-space: nowrap;
            transition: transform 0.15s ease, background 0.15s ease;
        }

        .btn-share-movie:active {
            transform: scale(0.95);
            background: rgba(2, 132, 199, 0.65);
        }

        .bot-notice {
            font-size: 10.5px;
            color: #64748b;
            font-weight: 500;
        }
    </style>
</head>
<body>

    <!-- 3D WebGL Canvas Layer -->
    <canvas id="webglCanvas"></canvas>
    <div class="vignette-overlay"></div>

    <!-- Top Navigation Header with Full-Width Search Bar Directly Below Title -->
    <div class="top-nav">
        <div class="brand-title">
            <span>🪐</span>
            <span>MovieVerse 3D</span>
        </div>
        <div class="search-box-wrap">
            <span class="search-icon-left">🔍</span>
            <input type="text" id="galaxySearchInput" class="search-input" placeholder="Search any movie or series..." value="__INITIAL_QUERY__" />
            <div class="search-spinner" id="searchSpinner"></div>
            <button class="search-clear-btn" id="clearSearchBtn" onclick="clearSearch()">✕</button>
        </div>
    </div>

    <!-- Bottom Discrete Floating Title & Prompt Pill (Non-overlapping) -->
    <div class="bottom-hint-bar" id="bottomHintBar">
        <div class="movie-title-preview" id="movieTitlePreview">Loading Cosmos...</div>
        <div class="hud-sub-badges" id="hudSubBadges"></div>
        <div class="hud-actions-row">
            <div class="tap-prompt-badge" onclick="triggerActiveModal()">
                <span>🍿</span>
                <span>View Episodes &amp; Files</span>
            </div>
            <div class="share-prompt-badge" onclick="shareActiveFromHud()">
                <span>🚀</span>
                <span>Share</span>
            </div>
        </div>
    </div>

    <!-- ------------------------------------------------------------- -->
    <!-- FULL-SCREEN CINEMA POST MODAL (Rock-Solid Flex Viewport Shell) -->
    <!-- ------------------------------------------------------------- -->
    <div class="cinema-post-modal" id="cinemaModal">
        <!-- 1. Pinned Top Bar -->
        <div class="modal-top-bar">
            <div class="modal-brand">
                <span>🍿</span> <span>AkMovieVerse Cinema</span>
            </div>
            <div class="modal-top-actions">
                <button class="modal-share-icon-btn" onclick="shareCurrentMovie()" title="Share with Friends">
                    <span>🚀</span>
                </button>
                <button class="modal-close-btn" onclick="closeCinemaModal()" title="Close">✕</button>
            </div>
        </div>

        <!-- 2. Smooth Scrollable Content Container -->
        <div class="modal-scroll-area" id="modalScrollArea">
            <!-- Hero Banner with Blurred Backdrop -->
            <div class="modal-hero">
                <img id="modalBackdropImg" class="modal-backdrop-img" src="" alt="Backdrop" />
                <div class="modal-hero-content">
                    <div class="modal-poster-wrap">
                        <img id="modalPosterImg" class="modal-poster-img" src="" alt="Poster" />
                    </div>
                    <h1 class="modal-title" id="modalTitleText">Title</h1>
                    <div class="modal-badges-row" id="modalBadgesContainer">
                        <!-- Populated dynamically -->
                    </div>
                    <p class="modal-storyline" id="modalStorylineText">Description</p>
                </div>
            </div>

            <!-- Content Body: Prints or Episodes & Packs -->
            <div class="modal-body" id="modalBodyContainer">
                <!-- Populated dynamically -->
            </div>
        </div>

        <!-- 3. Pinned Bottom Delivery Button & Share Row -->
        <div class="modal-bottom-bar">
            <div class="modal-action-buttons">
                <button id="modalBotAllBtn" class="btn-all-in-bot">
                    <span>🤖</span> <span>Get All Files / Episodes in Bot ↗️</span>
                </button>
                <button class="btn-share-movie" onclick="shareCurrentMovie()">
                    <span>🚀</span> <span>Share</span>
                </button>
            </div>
            <div class="bot-notice">
                🔒 Fast &amp; verified file delivery directly into your Telegram chat
            </div>
        </div>
    </div>

    <script>
        // Telegram Mini App Initialization
        if (window.Telegram && window.Telegram.WebApp) {
            window.Telegram.WebApp.ready();
            window.Telegram.WebApp.expand();
            try {
                window.Telegram.WebApp.setHeaderColor('#04060c');
                window.Telegram.WebApp.setBackgroundColor('#04060c');
            } catch (e) {}
        }

        // Web Audio Synthesizer for Space Audio & Haptics
        let audioCtx = null;
        function getAudioContext() {
            if (!audioCtx) {
                audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (audioCtx.state === 'suspended') {
                audioCtx.resume();
            }
            return audioCtx;
        }

        function playOrbTick() {
            try {
                const actx = getAudioContext();
                const osc = actx.createOscillator();
                const gain = actx.createGain();
                osc.type = "sine";
                osc.frequency.setValueAtTime(460, actx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(160, actx.currentTime + 0.04);
                gain.gain.setValueAtTime(0.06, actx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, actx.currentTime + 0.04);
                osc.connect(gain);
                gain.connect(actx.destination);
                osc.start();
                osc.stop(actx.currentTime + 0.04);
            } catch (e) {}
        }

        function playChime() {
            try {
                const actx = getAudioContext();
                [659.25, 880].forEach((freq, idx) => {
                    const osc = actx.createOscillator();
                    const gain = actx.createGain();
                    osc.type = "sine";
                    osc.frequency.setValueAtTime(freq, actx.currentTime + idx * 0.07);
                    gain.gain.setValueAtTime(0.08, actx.currentTime + idx * 0.07);
                    gain.gain.exponentialRampToValueAtTime(0.001, actx.currentTime + idx * 0.07 + 0.2);
                    osc.connect(gain);
                    gain.connect(actx.destination);
                    osc.start(actx.currentTime + idx * 0.07);
                    osc.stop(actx.currentTime + idx * 0.07 + 0.2);
                });
            } catch (e) {}
        }

        function playHologramWhoosh() {
            try {
                const actx = getAudioContext();
                const now = actx.currentTime;
                const osc = actx.createOscillator();
                const gain = actx.createGain();
                const filter = actx.createBiquadFilter();

                osc.type = "sawtooth";
                osc.frequency.setValueAtTime(880, now);
                osc.frequency.exponentialRampToValueAtTime(220, now + 0.22);

                filter.type = "lowpass";
                filter.frequency.setValueAtTime(3200, now);
                filter.frequency.exponentialRampToValueAtTime(400, now + 0.22);

                gain.gain.setValueAtTime(0.09, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.22);

                osc.connect(filter);
                filter.connect(gain);
                gain.connect(actx.destination);

                osc.start(now);
                osc.stop(now + 0.22);
            } catch (e) {}
        }

        const BOT_USERNAME = "__BOT_USERNAME__";
        const BASE_URL = "__BASE_URL__";

        function triggerHaptic(style) {
            try {
                if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.HapticFeedback) {
                    const hf = window.Telegram.WebApp.HapticFeedback;
                    if (style === "selection") {
                        if (typeof hf.selectionChanged === "function") hf.selectionChanged();
                        else hf.impactOccurred("light");
                    } else if (style === "light" || style === "medium" || style === "heavy" || style === "rigid" || style === "soft") {
                        hf.impactOccurred(style);
                    } else if (style === "success" || style === "warning" || style === "error") {
                        if (typeof hf.notificationOccurred === "function") hf.notificationOccurred(style);
                        else hf.impactOccurred("medium");
                    } else {
                        hf.impactOccurred("light");
                    }
                }
            } catch (e) {}
        }

        // Dynamic Raw Media Data from Backend Catalog
        let RAW_CATALOG = __CATALOG_JSON__;

        // Three.js 3D Engine Setup
        const canvas = document.getElementById("webglCanvas");
        const scene = new THREE.Scene();
        scene.fog = new THREE.FogExp2(0x04060c, 0.022);

        const camera = new THREE.PerspectiveCamera(46, window.innerWidth / window.innerHeight, 0.1, 1000);
        // Position camera to frame poster right in optical center (y = 0.4)
        camera.position.set(0, 0.4, 13.5);
        camera.lookAt(0, 0.4, 0);

        const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

        // Ambient & Cosmic Studio Lights
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.85);
        scene.add(ambientLight);

        // Left Cyan Rim Light
        const cyanRimLight = new THREE.PointLight(0x38bdf8, 2.2, 45);
        cyanRimLight.position.set(-6, 2.5, 4);
        scene.add(cyanRimLight);

        // Right Neon Rose Rim Light
        const roseRimLight = new THREE.PointLight(0xf43f5e, 2.4, 45);
        roseRimLight.position.set(6, 2, 4);
        scene.add(roseRimLight);

        // Front Soft Fill Light
        const frontFillLight = new THREE.PointLight(0xffffff, 0.9, 35);
        frontFillLight.position.set(0, 0.4, 9);
        scene.add(frontFillLight);

        // 1. Particle Starfield
        const starGeo = new THREE.BufferGeometry();
        const starCount = 2200;
        const starPos = new Float32Array(starCount * 3);
        for (let i = 0; i < starCount * 3; i += 3) {
            starPos[i] = (Math.random() - 0.5) * 160;
            starPos[i + 1] = (Math.random() - 0.5) * 160;
            starPos[i + 2] = (Math.random() - 0.5) * 160;
        }
        starGeo.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
        const starMat = new THREE.PointsMaterial({ color: 0x94a3b8, size: 0.65, transparent: true, opacity: 0.85 });
        const starField = new THREE.Points(starGeo, starMat);
        scene.add(starField);

        // 2. Cosmic Glowing Ring Halo (Smooth Luminous Glow, Zero Jagged Lines)
        const haloGeo = new THREE.TorusGeometry(3.6, 0.08, 16, 80);
        const haloMat = new THREE.MeshBasicMaterial({
            color: 0xf43f5e,
            transparent: true,
            opacity: 0.6,
            blending: THREE.AdditiveBlending
        });
        const cosmicHalo = new THREE.Mesh(haloGeo, haloMat);
        cosmicHalo.position.set(0, 0.4, -0.6);
        scene.add(cosmicHalo);

        // Second Cyan Outer Halo for Ethereal Glow
        const haloOuterGeo = new THREE.TorusGeometry(3.85, 0.04, 16, 80);
        const haloOuterMat = new THREE.MeshBasicMaterial({
            color: 0x38bdf8,
            transparent: true,
            opacity: 0.45,
            blending: THREE.AdditiveBlending
        });
        const cosmicHaloOuter = new THREE.Mesh(haloOuterGeo, haloOuterMat);
        cosmicHaloOuter.position.set(0, 0.4, -0.65);
        scene.add(cosmicHaloOuter);

        // Orbiting Stardust Particles
        const dustCount = 140;
        const dustGeo = new THREE.BufferGeometry();
        const dustPos = new Float32Array(dustCount * 3);
        for (let i = 0; i < dustCount * 3; i += 3) {
            const rad = 3.4 + Math.random() * 0.9;
            const theta = Math.random() * Math.PI * 2;
            dustPos[i] = Math.cos(theta) * rad;
            dustPos[i + 1] = Math.sin(theta) * rad;
            dustPos[i + 2] = (Math.random() - 0.5) * 0.6;
        }
        dustGeo.setAttribute("position", new THREE.BufferAttribute(dustPos, 3));
        const dustMat = new THREE.PointsMaterial({ color: 0xfbbf24, size: 0.12, transparent: true, opacity: 0.75, blending: THREE.AdditiveBlending });
        const stardust = new THREE.Points(dustGeo, dustMat);
        stardust.position.set(0, 0.4, -0.6);
        scene.add(stardust);

        // -------------------------------------------------------------
        // FEATURE 4: 3D HOLOGRAM PARTICLE BURST & SHOCKWAVE SYSTEM
        // -------------------------------------------------------------
        let activeBursts = [];
        let activeShockwaves = [];
        let targetCameraZ = 13.5;
        const shockwaveRingGeo = new THREE.RingGeometry(0.8, 1.05, 48);

        function triggerHologramBurst(originX, originY, originZ) {
            try {
                const ox = originX || 0;
                const oy = (originY !== undefined) ? originY : 0.4;
                const oz = (originZ !== undefined) ? originZ + 0.2 : 0.2;

                const count = 140;
                const geo = new THREE.BufferGeometry();
                const positions = new Float32Array(count * 3);
                const colors = new Float32Array(count * 3);
                const velocities = [];

                const palette = [
                    new THREE.Color(0x38bdf8), // Electric Cyan
                    new THREE.Color(0xf43f5e), // Cyber Rose
                    new THREE.Color(0xec4899), // Neon Pink
                    new THREE.Color(0xfacc15), // Solar Gold
                    new THREE.Color(0xffffff)  // Pure Starlight
                ];

                for (let i = 0; i < count; i++) {
                    positions[i * 3] = ox;
                    positions[i * 3 + 1] = oy;
                    positions[i * 3 + 2] = oz;

                    const col = palette[Math.floor(Math.random() * palette.length)];
                    colors[i * 3] = col.r;
                    colors[i * 3 + 1] = col.g;
                    colors[i * 3 + 2] = col.b;

                    const theta = Math.random() * Math.PI * 2;
                    const phi = Math.acos((Math.random() * 2) - 1);
                    const speed = 0.16 + Math.random() * 0.32;

                    velocities.push({
                        vx: speed * Math.sin(phi) * Math.cos(theta),
                        vy: speed * Math.sin(phi) * Math.sin(theta),
                        vz: speed * Math.cos(phi) * 0.7 + (Math.random() * 0.12)
                    });
                }

                geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
                geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));

                const mat = new THREE.PointsMaterial({
                    size: 0.55,
                    vertexColors: true,
                    transparent: true,
                    opacity: 1.0,
                    blending: THREE.AdditiveBlending,
                    depthWrite: false
                });

                const burstPoints = new THREE.Points(geo, mat);
                scene.add(burstPoints);

                activeBursts.push({
                    mesh: burstPoints,
                    velocities: velocities,
                    life: 1.0,
                    decay: 0.038
                });

                // Holographic Expanding Shockwave Ring
                const ringMat = new THREE.MeshBasicMaterial({
                    color: 0x38bdf8,
                    transparent: true,
                    opacity: 0.85,
                    side: THREE.DoubleSide,
                    blending: THREE.AdditiveBlending,
                    depthWrite: false
                });
                const shockRing = new THREE.Mesh(shockwaveRingGeo, ringMat);
                shockRing.position.set(ox, oy, oz + 0.05);
                shockRing.scale.set(0.4, 0.4, 0.4);
                scene.add(shockRing);

                activeShockwaves.push({
                    mesh: shockRing,
                    scale: 0.4,
                    maxScale: 3.8,
                    opacity: 0.85
                });

                // Camera Focus Surge
                targetCameraZ = 12.2;
                setTimeout(() => {
                    targetCameraZ = 13.5;
                }, 220);
            } catch (err) {
                console.debug("Hologram burst error:", err);
            }
        }

        // Group holding 3D Card(s)
        const cardsGroup = new THREE.Group();
        cardsGroup.position.set(0, 0.4, 0);
        scene.add(cardsGroup);

        const textureLoader = new THREE.TextureLoader();
        textureLoader.crossOrigin = "anonymous";
        let cardMeshes = [];
        let isSingleHeroMode = true;

        // CineFlow Slider State
        let currentScroll = 0;
        let targetScroll = 0;

        // High-Definition Studio Poster Canvas Generator (Zero Missing Posters, Gorgeous Styling)
        function createPosterCanvas(titleText, isSeries, ratingText, qualText) {
            const c = document.createElement("canvas");
            c.width = 600;
            c.height = 900;
            const cx = c.getContext("2d");

            // Rich Cosmic Gradient Background
            const grad = cx.createLinearGradient(0, 0, 600, 900);
            grad.addColorStop(0, "#080c18");
            grad.addColorStop(0.5, "#181f38");
            grad.addColorStop(1, "#080c18");
            cx.fillStyle = grad;
            cx.fillRect(0, 0, 600, 900);

            // Ambient Starlight Sparkles on Canvas
            cx.fillStyle = "rgba(255, 255, 255, 0.25)";
            for (let i = 0; i < 35; i++) {
                const sx = (i * 73) % 600;
                const sy = (i * 127) % 900;
                const sr = (i % 3) + 1;
                cx.beginPath();
                cx.arc(sx, sy, sr, 0, Math.PI * 2);
                cx.fill();
            }

            // Top Header Brand Emblem
            cx.fillStyle = "#f43f5e";
            cx.font = "900 24px sans-serif";
            cx.textAlign = "center";
            cx.fillText("🪐 AK MOVIEVERSE CINEMA", 300, 110);

            // Center Big Cinema Emblem
            cx.font = "80px sans-serif";
            cx.fillText(isSeries ? "📺" : "🎬", 300, 340);

            // Category Pill
            cx.fillStyle = isSeries ? "rgba(168, 85, 247, 0.35)" : "rgba(56, 189, 248, 0.35)";
            cx.strokeStyle = isSeries ? "#c084fc" : "#38bdf8";
            cx.lineWidth = 2;
            cx.beginPath();
            cx.roundRect ? cx.roundRect(200, 380, 200, 42, 12) : cx.rect(200, 380, 200, 42);
            cx.fill();
            cx.stroke();

            cx.fillStyle = "#ffffff";
            cx.font = "bold 18px sans-serif";
            cx.fillText(isSeries ? "WEB SERIES" : "FEATURE FILM", 300, 407);

            // Clean Wrapped Title
            cx.fillStyle = "#ffffff";
            cx.font = "900 36px sans-serif";
            cx.shadowColor = "rgba(0, 0, 0, 0.9)";
            cx.shadowBlur = 16;

            const words = (titleText || "Cinema Feature").split(" ");
            let line = "";
            let y = 500;
            const lineHeight = 46;

            for (let n = 0; n < words.length; n++) {
                const testLine = line + words[n] + " ";
                const metrics = cx.measureText(testLine);
                if (metrics.width > 500 && n > 0) {
                    cx.fillText(line.trim(), 300, y);
                    line = words[n] + " ";
                    y += lineHeight;
                    if (y > 670) {
                        line += "...";
                        break;
                    }
                } else {
                    line = testLine;
                }
            }
            cx.fillText(line.trim(), 300, y);
            cx.shadowBlur = 0;

            // Bottom Badges (Rating & HD)
            cx.fillStyle = "#fbbf24";
            cx.font = "bold 22px sans-serif";
            cx.fillText(`⭐ ${ratingText || '8.2'} IMDb  •  4K UHD`, 300, 780);

            const texture = new THREE.CanvasTexture(c);
            texture.minFilter = THREE.LinearFilter;
            texture.magFilter = THREE.LinearFilter;
            return texture;
        }

        // Texture Loader with Safe Error Fallback
        function createCardMaterial(item) {
            const edgeMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.25, metalness: 0.85 });
            const backMat = new THREE.MeshStandardMaterial({ color: 0x060911, roughness: 0.4, metalness: 0.9 });

            let frontTex;
            if (item.poster_url) {
                frontTex = textureLoader.load(
                    item.poster_url,
                    function(t) {
                        t.minFilter = THREE.LinearFilter;
                        t.magFilter = THREE.LinearFilter;
                    },
                    undefined,
                    function(err) {
                        // Safe fallback on network drop / CORS / 404: Never show black card!
                        const fallback = createPosterCanvas(item.clean_name, item.is_series, item.rating, item.qualities);
                        frontMat.map = fallback;
                        frontMat.needsUpdate = true;
                    }
                );
                frontTex.minFilter = THREE.LinearFilter;
                frontTex.magFilter = THREE.LinearFilter;
            } else {
                frontTex = createPosterCanvas(item.clean_name, item.is_series, item.rating, item.qualities);
            }

            const frontMat = new THREE.MeshBasicMaterial({ map: frontTex });
            // BoxGeometry face ordering: [+X, -X, +Y, -Y, +Z (Front), -Z (Back)]
            return [edgeMat, edgeMat, edgeMat, edgeMat, frontMat, backMat];
        }

        function updateBottomHud(item) {
            if (!item) return;
            document.getElementById("movieTitlePreview").innerText = item.title || item.clean_name;
            const hudBadges = document.getElementById("hudSubBadges");
            hudBadges.innerHTML = "";

            const b1 = document.createElement("span");
            b1.className = "hud-pill hud-pill-gold";
            b1.innerText = `⭐ ${item.rating || '8.2'}`;
            hudBadges.appendChild(b1);

            const b2 = document.createElement("span");
            b2.className = "hud-pill hud-pill-cyan";
            b2.innerText = item.is_series ? "Series" : "Movie";
            hudBadges.appendChild(b2);

            if (item.languages && item.languages.length > 0) {
                const b3 = document.createElement("span");
                b3.className = "hud-pill";
                b3.innerText = item.languages[0];
                hudBadges.appendChild(b3);
            }
        }

        // Build 3D Cards Scene (Hero Mode for 1 result vs Smooth Non-Clipping CineFlow for multiple)
        function build3DScene() {
            while (cardsGroup.children.length > 0) {
                cardsGroup.remove(cardsGroup.children[0]);
            }
            cardMeshes = [];

            if (!RAW_CATALOG || RAW_CATALOG.length === 0) {
                document.getElementById("movieTitlePreview").innerText = "No Matching Files Found";
                document.getElementById("hudSubBadges").innerHTML = "";
                cosmicHalo.visible = false;
                cosmicHaloOuter.visible = false;
                stardust.visible = false;
                return;
            }

            const total = RAW_CATALOG.length;
            isSingleHeroMode = (total === 1);
            cosmicHalo.visible = true;
            cosmicHaloOuter.visible = true;
            stardust.visible = true;

            const cardW = 3.6;
            const cardH = 5.4;
            const cardD = 0.12;

            if (isSingleHeroMode) {
                // HERO MODE: 1 Single Card perfectly centered with floating oscillation and touch tilt
                const item = RAW_CATALOG[0];
                const cardBox = new THREE.BoxGeometry(cardW, cardH, cardD);
                const materials = createCardMaterial(item);

                const mesh = new THREE.Mesh(cardBox, materials);
                mesh.position.set(0, 0, 0);
                mesh.userData = { item: item, index: 0 };

                cardsGroup.add(mesh);
                cardMeshes.push(mesh);
                cardsGroup.rotation.set(0, 0, 0);
                updateBottomHud(item);
            } else {
                // CINEFLOW SLIDER MODE: Smooth horizontal arc slider with ZERO clipping / collision
                currentScroll = 0;
                targetScroll = 0;

                for (let i = 0; i < total; i++) {
                    const item = RAW_CATALOG[i];
                    const cardBox = new THREE.BoxGeometry(cardW, cardH, cardD);
                    const materials = createCardMaterial(item);

                    const mesh = new THREE.Mesh(cardBox, materials);
                    mesh.userData = { item: item, index: i };
                    cardsGroup.add(mesh);
                    cardMeshes.push(mesh);
                }

                if (cardMeshes.length > 0) {
                    updateBottomHud(cardMeshes[0].userData.item);
                }
            }
        }

        build3DScene();

        // 3D Parallax Tilt & Drag Interaction
        let isDragging = false;
        let startX = 0;
        let startY = 0;
        let previousMouseX = 0;
        let scrollVelocity = 0;
        let heroTiltX = 0;
        let heroTiltY = 0;
        let targetHeroTiltX = 0;
        let targetHeroTiltY = 0;
        let lastSnapIndex = 0;

        // Pointer Events
        window.addEventListener("mousedown", (e) => {
            if (e.target.closest(".top-nav") || e.target.closest(".cinema-post-modal")) return;
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            previousMouseX = e.clientX;
            scrollVelocity = 0;
            getAudioContext();
        });

        window.addEventListener("mousemove", (e) => {
            if (!isDragging) return;
            const deltaX = e.clientX - previousMouseX;
            previousMouseX = e.clientX;

            if (isSingleHeroMode) {
                targetHeroTiltY = (e.clientX - window.innerWidth / 2) * 0.0016;
                targetHeroTiltX = -(e.clientY - window.innerHeight / 2) * 0.0016;
            } else {
                scrollVelocity = -deltaX * 0.0055;
                targetScroll += scrollVelocity;
                targetScroll = Math.max(-0.2, Math.min(cardMeshes.length - 0.8, targetScroll));
            }
        });

        window.addEventListener("mouseup", () => {
            if (isDragging) {
                isDragging = false;
                if (!isSingleHeroMode) {
                    targetScroll = Math.round(targetScroll);
                    targetScroll = Math.max(0, Math.min(cardMeshes.length - 1, targetScroll));
                }
                targetHeroTiltX = 0;
                targetHeroTiltY = 0;
            }
        });

        // Touch Listeners for Mobile Devices
        window.addEventListener("touchstart", (e) => {
            if (e.target.closest(".top-nav") || e.target.closest(".cinema-post-modal")) return;
            if (e.touches.length === 1) {
                isDragging = true;
                startX = e.touches[0].clientX;
                startY = e.touches[0].clientY;
                previousMouseX = e.touches[0].clientX;
                scrollVelocity = 0;
                getAudioContext();
            }
        }, { passive: true });

        window.addEventListener("touchmove", (e) => {
            if (!isDragging || e.touches.length !== 1) return;
            const deltaX = e.touches[0].clientX - previousMouseX;
            previousMouseX = e.touches[0].clientX;

            if (isSingleHeroMode) {
                targetHeroTiltY = (e.touches[0].clientX - window.innerWidth / 2) * 0.002;
                targetHeroTiltX = -(e.touches[0].clientY - window.innerHeight / 2) * 0.002;
            } else {
                scrollVelocity = -deltaX * 0.0065;
                targetScroll += scrollVelocity;
                targetScroll = Math.max(-0.2, Math.min(cardMeshes.length - 0.8, targetScroll));
            }
        }, { passive: true });

        window.addEventListener("touchend", () => {
            if (isDragging) {
                isDragging = false;
                if (!isSingleHeroMode) {
                    targetScroll = Math.round(targetScroll);
                    targetScroll = Math.max(0, Math.min(cardMeshes.length - 1, targetScroll));
                }
                targetHeroTiltX = 0;
                targetHeroTiltY = 0;
            }
        });

        // Raycasting for Card Click Selection
        const raycaster = new THREE.Raycaster();
        const mouseVec = new THREE.Vector2();

        function handleCardSelection(clientX, clientY) {
            mouseVec.x = (clientX / window.innerWidth) * 2 - 1;
            mouseVec.y = -(clientY / window.innerHeight) * 2 + 1;
            raycaster.setFromCamera(mouseVec, camera);

            const visibleMeshes = cardMeshes.filter(m => m.visible);
            const intersects = raycaster.intersectObjects(visibleMeshes);

            if (intersects.length > 0) {
                const clickedMesh = intersects[0].object;
                const clickedIndex = clickedMesh.userData.index;

                if (isSingleHeroMode) {
                    playChime();
                    playHologramWhoosh();
                    triggerHaptic("medium");
                    triggerHologramBurst(clickedMesh.position.x, clickedMesh.position.y, clickedMesh.position.z);
                    openCinemaModal(clickedMesh.userData.item);
                } else {
                    const activeIdx = Math.round(currentScroll);
                    if (clickedIndex === activeIdx) {
                        playChime();
                        playHologramWhoosh();
                        triggerHaptic("medium");
                        triggerHologramBurst(clickedMesh.position.x, clickedMesh.position.y, clickedMesh.position.z);
                        openCinemaModal(clickedMesh.userData.item);
                    } else {
                        // Snap clicked card to center
                        targetScroll = clickedIndex;
                        playOrbTick();
                        triggerHaptic("light");
                    }
                }
            }
        }

        window.addEventListener("click", (e) => {
            if (e.target.closest(".top-nav") || e.target.closest(".cinema-post-modal")) return;
            const dist = Math.hypot(e.clientX - startX, e.clientY - startY);
            if (dist > 8) return; // Ignore drag release
            handleCardSelection(e.clientX, e.clientY);
        });

        function triggerActiveModal() {
            if (cardMeshes.length === 0) return;
            const activeIdx = isSingleHeroMode ? 0 : Math.round(currentScroll);
            const targetMesh = cardMeshes[activeIdx] || cardMeshes[0];
            if (targetMesh && targetMesh.userData.item) {
                playChime();
                playHologramWhoosh();
                triggerHaptic("medium");
                triggerHologramBurst(targetMesh.position.x, targetMesh.position.y, targetMesh.position.z);
                openCinemaModal(targetMesh.userData.item);
            }
        }

        // Deliver File to Bot Function
        function downloadQualityFile(botUrl) {
            if (!botUrl) return;
            playChime();
            triggerHaptic("heavy");
            if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.openTelegramLink) {
                window.Telegram.WebApp.openTelegramLink(botUrl);
            } else {
                window.open(botUrl, '_blank');
            }
        }

        // -------------------------------------------------------------
        // 1-CLICK SHARE WITH FRIENDS (Native Telegram Share Sheet)
        // -------------------------------------------------------------
        let currentModalItem = null;

        function shareMovie(title, year, isSeries, cleanName) {
            triggerHaptic("success");
            playChime();

            const botUname = BOT_USERNAME || "TheFlixifyBot";
            const safeTitle = (cleanName || title || "Movie").trim();
            const yearStr = year ? ` (${year})` : "";

            const effectiveBase = (BASE_URL && !BASE_URL.includes("__BASE_URL__") && !BASE_URL.includes("127.0.0.1") && !BASE_URL.includes("localhost"))
                ? BASE_URL.replace(/\/+$/, "")
                : (window.location && window.location.origin ? window.location.origin.replace(/\/+$/, "") : "https://akmovieverse.duckdns.org");

            const galaxyDirectUrl = `${effectiveBase}/galaxy?q=${encodeURIComponent(safeTitle)}`;
            const shareText = `🍿 Hey! Watch & Download: ${title}${yearStr}\n⚡ High-Quality HD Prints Available on @${botUname}!\n\n👇 Tap to explore in 3D Galaxy:`;

            const tgShareUrl = `https://t.me/share/url?url=${encodeURIComponent(galaxyDirectUrl)}&text=${encodeURIComponent(shareText)}`;

            if (window.Telegram && window.Telegram.WebApp && typeof window.Telegram.WebApp.openTelegramLink === "function") {
                window.Telegram.WebApp.openTelegramLink(tgShareUrl);
            } else {
                window.open(tgShareUrl, "_blank");
            }
        }

        function shareCurrentMovie() {
            if (!currentModalItem) return;
            shareMovie(
                currentModalItem.title,
                currentModalItem.year,
                currentModalItem.is_series,
                currentModalItem.clean_name
            );
        }

        function shareActiveFromHud() {
            if (cardMeshes.length === 0) return;
            const activeIdx = isSingleHeroMode ? 0 : Math.round(currentScroll);
            const targetMesh = cardMeshes[activeIdx] || cardMeshes[0];
            if (targetMesh && targetMesh.userData && targetMesh.userData.item) {
                const it = targetMesh.userData.item;
                shareMovie(it.title, it.year, it.is_series, it.clean_name);
            }
        }

        // -------------------------------------------------------------
        // OPEN FULL CINEMA POST MODAL (Styled like Website Post Page)
        // -------------------------------------------------------------
        function openCinemaModal(item) {
            const modal = document.getElementById("cinemaModal");
            currentModalItem = item;
            const title = item.title || item.clean_name;

            // Set Title & Images
            document.getElementById("modalTitleText").innerText = title;
            const posterImg = document.getElementById("modalPosterImg");
            const backdropImg = document.getElementById("modalBackdropImg");
            const pUrl = item.poster_url || "https://api.aniwallpaper.workers.dev/random";
            posterImg.src = pUrl;
            backdropImg.src = pUrl;

            // Badges
            const badgesBox = document.getElementById("modalBadgesContainer");
            badgesBox.innerHTML = "";

            const ratingPill = document.createElement("span");
            ratingPill.className = "badge-pill badge-pill-rating";
            ratingPill.innerText = `⭐ ${item.rating || '8.2'} IMDb`;
            badgesBox.appendChild(ratingPill);

            const typePill = document.createElement("span");
            typePill.className = "badge-pill badge-pill-type";
            typePill.innerText = item.is_series ? "📺 Web Series" : "🎬 Movie";
            badgesBox.appendChild(typePill);

            if (item.total_size) {
                const sizePill = document.createElement("span");
                sizePill.className = "badge-pill badge-pill-size";
                sizePill.innerText = `📦 ${item.total_size}`;
                badgesBox.appendChild(sizePill);
            }

            if (item.languages && item.languages.length > 0) {
                const audPill = document.createElement("span");
                audPill.className = "badge-pill badge-pill-audio";
                audPill.innerText = item.languages.includes("Multi Audio") ? "🌐 Multi Audio" : `🌐 ${item.languages.slice(0, 2).join(" • ")}`;
                badgesBox.appendChild(audPill);
            }

            // Storyline
            document.getElementById("modalStorylineText").innerText = item.storyline || `Get verified releases of ${title} in crystal clear HD audio and video prints.`;

            // Content Body: Prints or Episodes
            const bodyBox = document.getElementById("modalBodyContainer");
            bodyBox.innerHTML = "";

            if (item.is_series) {
                // Web Series View: Complete Packs + Individual Episodes
                if (item.packs && item.packs.length > 0) {
                    const packSec = document.createElement("div");
                    packSec.innerHTML = `
                        <div class="section-header">
                            <span class="section-title">📦 Complete Season Packs (${item.packs.length})</span>
                            <span class="section-subtitle">1-Click Full Pack Download</span>
                        </div>
                    `;
                    const packGrid = document.createElement("div");
                    packGrid.className = "items-grid";

                    item.packs.forEach(pk => {
                        const card = document.createElement("div");
                        card.className = "item-card";
                        card.innerHTML = `
                            <div class="item-info">
                                <span class="quality-tag quality-tag-1080">${pk.quality || 'HD'}</span>
                                <div class="item-details">
                                    <div class="item-name">${pk.title}</div>
                                    <div class="item-sub">${pk.size} • Full Season Complete</div>
                                </div>
                            </div>
                            <button class="btn-download-action" onclick="downloadQualityFile('${pk.bot_url}')">
                                <span>📥</span> <span>Get Pack</span>
                            </button>
                        `;
                        packGrid.appendChild(card);
                    });
                    packSec.appendChild(packGrid);
                    bodyBox.appendChild(packSec);
                }

                if (item.episodes && item.episodes.length > 0) {
                    const epSec = document.createElement("div");
                    epSec.innerHTML = `
                        <div class="section-header">
                            <span class="section-title">📺 All Episodes (${item.episodes.length})</span>
                            <span class="section-subtitle">Episode-by-Episode Selection</span>
                        </div>
                    `;
                    const epGrid = document.createElement("div");
                    epGrid.className = "items-grid";

                    item.episodes.forEach(ep => {
                        const card = document.createElement("div");
                        card.className = "item-card";
                        card.innerHTML = `
                            <div class="item-info">
                                <span class="quality-tag quality-tag-720">EP ${ep.episode}</span>
                                <div class="item-details">
                                    <div class="item-name">${item.clean_name} - Episode ${ep.episode}</div>
                                    <div class="item-sub">${ep.quality} • ${ep.size}</div>
                                </div>
                            </div>
                            <button class="btn-download-action" onclick="downloadQualityFile('${ep.bot_url}')">
                                <span>📥</span> <span>Get Ep</span>
                            </button>
                        `;
                        epGrid.appendChild(card);
                    });
                    epSec.appendChild(epGrid);
                    bodyBox.appendChild(epSec);
                } else if (!item.packs || item.packs.length === 0) {
                    renderQualityCardsFallback(item, bodyBox);
                }
            } else {
                // Movie View: Prints & Qualities List
                const movieSec = document.createElement("div");
                const mFiles = item.movie_files && item.movie_files.length > 0 ? item.movie_files : item.quality_files || [];
                movieSec.innerHTML = `
                    <div class="section-header">
                        <span class="section-title">🎬 Available Prints &amp; Qualities (${mFiles.length})</span>
                        <span class="section-subtitle">Select Resolution</span>
                    </div>
                `;
                const mGrid = document.createElement("div");
                mGrid.className = "items-grid";

                mFiles.forEach(f => {
                    const q = f.quality || "HD";
                    const is4k = q.toLowerCase().includes("2160") || q.toLowerCase().includes("4k");
                    const is1080 = q.toLowerCase().includes("1080");
                    const tagClass = is4k ? "quality-tag-4k" : (is1080 ? "quality-tag-1080" : "quality-tag-720");
                    const partText = f.part_label ? ` • ${f.part_label}` : '';

                    const card = document.createElement("div");
                    card.className = "item-card";
                    card.innerHTML = `
                        <div class="item-info">
                            <span class="quality-tag ${tagClass}">${q}</span>
                            <div class="item-details">
                                <div class="item-name">${title}${partText}</div>
                                <div class="item-sub">${f.size || ''} • Verified Clean Audio</div>
                            </div>
                        </div>
                        <button class="btn-download-action" onclick="downloadQualityFile('${f.bot_url}')">
                            <span>📥</span> <span>Get File</span>
                        </button>
                    `;
                    mGrid.appendChild(card);
                });
                movieSec.appendChild(mGrid);
                bodyBox.appendChild(movieSec);
            }

            // Bottom Bot Button
            document.getElementById("modalBotAllBtn").onclick = () => downloadQualityFile(item.bot_url);

            // Reset scroll position to top
            document.getElementById("modalScrollArea").scrollTop = 0;

            modal.classList.add("active");
            document.getElementById("bottomHintBar").style.opacity = "0";
        }

        function renderQualityCardsFallback(item, bodyBox) {
            const sec = document.createElement("div");
            sec.innerHTML = `
                <div class="section-header">
                    <span class="section-title">⚡ Available Qualities</span>
                </div>
            `;
            const grid = document.createElement("div");
            grid.className = "items-grid";
            (item.quality_files || []).forEach(qf => {
                const card = document.createElement("div");
                card.className = "item-card";
                card.innerHTML = `
                    <div class="item-info">
                        <span class="quality-tag quality-tag-1080">${qf.quality}</span>
                        <div class="item-details">
                            <div class="item-name">${item.clean_name}</div>
                            <div class="item-sub">${qf.size}</div>
                        </div>
                    </div>
                    <button class="btn-download-action" onclick="downloadQualityFile('${qf.bot_url}')">
                        <span>📥</span> <span>Get File</span>
                    </button>
                `;
                grid.appendChild(card);
            });
            sec.appendChild(grid);
            bodyBox.appendChild(sec);
        }

        function closeCinemaModal() {
            document.getElementById("cinemaModal").classList.remove("active");
            document.getElementById("bottomHintBar").style.opacity = "1";
            triggerHaptic("light");
        }

        // Live Real-Time Search Handler
        let searchTimeout = null;
        const searchInput = document.getElementById("galaxySearchInput");
        const clearBtn = document.getElementById("clearSearchBtn");
        const searchSpinner = document.getElementById("searchSpinner");

        if (searchInput.value.trim()) {
            clearBtn.style.display = "flex";
        }

        searchInput.addEventListener("input", (e) => {
            const query = e.target.value.trim();
            clearBtn.style.display = query ? "flex" : "none";

            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                performLiveSearch(query);
            }, 300);
        });

        function clearSearch() {
            searchInput.value = "";
            clearBtn.style.display = "none";
            performLiveSearch("");
        }

        async function performLiveSearch(query) {
            searchSpinner.style.display = "inline-block";
            try {
                const url = `/api/galaxy/search?q=${encodeURIComponent(query)}`;
                const res = await fetch(url);
                const data = await res.json();
                if (data && Array.isArray(data.results)) {
                    RAW_CATALOG = data.results;
                    build3DScene();
                    playChime();
                    triggerHaptic("medium");
                }
            } catch (err) {
                console.error("Galaxy search error:", err);
            } finally {
                searchSpinner.style.display = "none";
            }
        }

        // Window Resize
        window.addEventListener("resize", () => {
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight);
        });

        // Animation Loop with Smooth Floating Physics & CineFlow Arc
        let clock = 0;
        function animate() {
            requestAnimationFrame(animate);
            clock += 0.016;

            // Celestial rotations
            starField.rotation.y += 0.0003;
            cosmicHalo.rotation.z += 0.004;
            cosmicHaloOuter.rotation.z -= 0.003;
            stardust.rotation.z += 0.006;

            if (isSingleHeroMode && cardMeshes.length > 0) {
                // HERO MODE:
                const heroCard = cardMeshes[0];
                heroCard.position.set(0, Math.sin(clock * 1.6) * 0.12, 0);

                // Parallax 3D spring tilt on touch/drag
                heroTiltX += (targetHeroTiltX - heroTiltX) * 0.12;
                heroTiltY += (targetHeroTiltY - heroTiltY) * 0.12;
                heroCard.rotation.x = heroTiltX;
                heroCard.rotation.y = heroTiltY;

                // Pulsing Halo behind card
                const scalePulse = 1 + Math.sin(clock * 2) * 0.035;
                cosmicHalo.scale.set(scalePulse, scalePulse, 1);
                cosmicHaloOuter.scale.set(scalePulse * 1.02, scalePulse * 1.02, 1);
            } else if (cardMeshes.length > 0) {
                // CINEFLOW SLIDER MODE: Smooth lerp to target scroll
                currentScroll += (targetScroll - currentScroll) * 0.12;

                const activeSnap = Math.round(currentScroll);
                if (activeSnap !== lastSnapIndex && Math.abs(currentScroll - activeSnap) < 0.15) {
                    lastSnapIndex = activeSnap;
                    playOrbTick();
                    triggerHaptic("selection");
                    if (cardMeshes[activeSnap]) {
                        updateBottomHud(cardMeshes[activeSnap].userData.item);
                    }
                }

                // Render each card along the smooth CineFlow Arc (Zero clipping!)
                const cardSpacing = 4.0;
                cardMeshes.forEach((mesh, idx) => {
                    const offset = idx - currentScroll;

                    // Frustum culling: Only draw cards in front-view range [-3.5, 3.5]
                    if (Math.abs(offset) > 3.5) {
                        mesh.visible = false;
                        return;
                    }

                    mesh.visible = true;
                    // Spacing along X, curved depth along Z:
                    mesh.position.x = offset * cardSpacing;
                    mesh.position.z = -Math.abs(offset) * 1.65;
                    mesh.position.y = Math.sin(clock * 1.6 + idx * 0.4) * 0.08;

                    // Tilted smoothly toward user
                    mesh.rotation.y = -Math.sign(offset) * Math.min(Math.abs(offset) * 0.32, 0.55);
                    mesh.rotation.x = 0;

                    // Scale: center card is 1.0, side cards step down
                    const sc = Math.max(0.68, 1.0 - Math.abs(offset) * 0.12);
                    mesh.scale.set(sc, sc, sc);
                });
            }

            // Smooth Camera Focus Surge
            camera.position.z += (targetCameraZ - camera.position.z) * 0.15;

            // Animate Active Particle Bursts
            for (let bIdx = activeBursts.length - 1; bIdx >= 0; bIdx--) {
                const b = activeBursts[bIdx];
                b.life -= b.decay;
                if (b.life <= 0) {
                    scene.remove(b.mesh);
                    b.mesh.geometry.dispose();
                    b.mesh.material.dispose();
                    activeBursts.splice(bIdx, 1);
                    continue;
                }
                b.mesh.material.opacity = Math.max(0, b.life);
                const posAttr = b.mesh.geometry.attributes.position;
                const posArr = posAttr.array;
                for (let p = 0; p < b.velocities.length; p++) {
                    const vel = b.velocities[p];
                    posArr[p * 3] += vel.vx;
                    posArr[p * 3 + 1] += vel.vy;
                    posArr[p * 3 + 2] += vel.vz;
                    vel.vx *= 0.94;
                    vel.vy *= 0.94;
                    vel.vz *= 0.94;
                }
                posAttr.needsUpdate = true;
            }

            // Animate Active Shockwave Rings
            for (let sIdx = activeShockwaves.length - 1; sIdx >= 0; sIdx--) {
                const sw = activeShockwaves[sIdx];
                sw.scale += 0.22;
                sw.opacity -= 0.045;
                if (sw.opacity <= 0 || sw.scale >= sw.maxScale) {
                    scene.remove(sw.mesh);
                    sw.mesh.material.dispose();
                    activeShockwaves.splice(sIdx, 1);
                    continue;
                }
                sw.mesh.scale.set(sw.scale, sw.scale, sw.scale);
                sw.mesh.material.opacity = Math.max(0, sw.opacity);
            }

            renderer.render(scene, camera);
        }

        animate();
    </script>
</body>
</html>
"""


def render_galaxy_movieverse(items: list, base_url: str, bot_username: str, initial_query: str = "") -> str:
    """Format and render the 3D MovieVerse Search page with dynamic MongoDB catalog."""
    html = GALAXY_HTML_TEMPLATE
    html = html.replace("__CATALOG_JSON__", json.dumps(items))
    html = html.replace("__INITIAL_QUERY__", html_escape(initial_query))
    html = html.replace("__BOT_USERNAME__", bot_username)
    html = html.replace("__BASE_URL__", base_url)
    return html
