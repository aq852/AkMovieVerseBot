"""Flixify / AkMovieVerse 3D — Futuristic 3D Search & File Delivery Telegram Mini App (WebApp).
Interactive 3D WebGL space universe where movie and web series cards float in an orbit around
a glowing cosmic nebula core with real-time search, touch inertia, gyroscopic tilt, and direct Telegram bot file delivery.
"""

import json
from html import escape as html_escape

GALAXY_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>MovieVerse 3D — Futuristic Search & File Delivery</title>
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
            background: #050811;
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

        /* Ambient Glow & Vignette */
        .vignette-overlay {
            position: fixed;
            inset: 0;
            pointer-events: none;
            background: radial-gradient(circle at center, transparent 35%, rgba(5, 8, 17, 0.75) 85%, #050811 100%);
            z-index: 2;
        }

        /* Top HUD Bar */
        .hud-header {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 10;
            padding: 12px 14px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            background: linear-gradient(180deg, rgba(5, 8, 17, 0.95) 0%, rgba(5, 8, 17, 0) 100%);
        }

        .brand-logo {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 15px;
            font-weight: 900;
            color: #f43f5e;
            letter-spacing: 0.5px;
            text-shadow: 0 0 16px rgba(244, 63, 94, 0.6);
            white-space: nowrap;
            flex-shrink: 0;
        }

        /* Live Search Bar */
        .search-bar-wrap {
            position: relative;
            flex: 1;
            max-width: 320px;
        }

        .search-input {
            width: 100%;
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(244, 63, 94, 0.35);
            border-radius: 20px;
            padding: 7px 30px 7px 32px;
            color: #ffffff;
            font-size: 12px;
            font-weight: 600;
            outline: none;
            transition: all 0.2s ease;
            user-select: auto;
            -webkit-user-select: auto;
        }

        .search-input:focus {
            border-color: #f43f5e;
            box-shadow: 0 0 15px rgba(244, 63, 94, 0.4);
            background: rgba(15, 23, 42, 0.95);
        }

        .search-icon-left {
            position: absolute;
            left: 10px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 12px;
            pointer-events: none;
            opacity: 0.7;
        }

        .search-clear-btn {
            position: absolute;
            right: 8px;
            top: 50%;
            transform: translateY(-50%);
            background: rgba(255, 255, 255, 0.15);
            border: none;
            color: #cbd5e1;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            display: none;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            cursor: pointer;
        }

        .search-spinner {
            position: absolute;
            right: 30px;
            top: 50%;
            transform: translateY(-50%);
            width: 12px;
            height: 12px;
            border: 2px solid rgba(244, 63, 94, 0.3);
            border-top-color: #f43f5e;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            display: none;
        }

        @keyframes spin {
            to { transform: translateY(-50%) rotate(360deg); }
        }

        /* Filter Pills Row */
        .hud-pills {
            position: fixed;
            top: 54px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 10;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .filter-btn {
            background: rgba(15, 23, 42, 0.75);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #94a3b8;
            font-size: 11px;
            font-weight: 700;
            padding: 5px 12px;
            border-radius: 18px;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .filter-btn.active, .filter-btn:hover {
            background: linear-gradient(135deg, #f43f5e, #e11d48);
            color: #ffffff;
            border-color: rgba(244, 63, 94, 0.5);
            box-shadow: 0 0 14px rgba(244, 63, 94, 0.4);
        }

        /* Center Search / Results Banner Notice */
        .search-banner {
            position: fixed;
            top: 90px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 10;
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(56, 189, 248, 0.3);
            border-radius: 20px;
            padding: 5px 14px;
            font-size: 11px;
            font-weight: 600;
            color: #38bdf8;
            pointer-events: none;
            display: none;
            text-align: center;
            max-width: 90%;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        /* Swipe Hint */
        .swipe-hint {
            position: fixed;
            bottom: 64px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 10;
            background: rgba(15, 23, 42, 0.6);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 20px;
            padding: 4px 12px;
            font-size: 11px;
            font-weight: 600;
            color: #94a3b8;
            pointer-events: none;
            display: flex;
            align-items: center;
            gap: 6px;
            animation: fadeInOut 4s infinite alternate;
        }

        @keyframes fadeInOut {
            0% { opacity: 0.4; transform: translateX(-50%) translateY(0); }
            100% { opacity: 0.9; transform: translateX(-50%) translateY(-2px); }
        }

        /* Active Movie Title Indicator */
        .focused-title-bar {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 10;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 4px;
            pointer-events: none;
            transition: opacity 0.3s ease;
        }

        .focused-title {
            font-size: 16px;
            font-weight: 800;
            color: #ffffff;
            text-shadow: 0 2px 10px rgba(0, 0, 0, 0.9);
            text-align: center;
            max-width: 280px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .focused-sub {
            font-size: 12px;
            font-weight: 600;
            color: #38bdf8;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .tap-prompt-badge {
            background: rgba(244, 63, 94, 0.2);
            border: 1px solid rgba(244, 63, 94, 0.5);
            color: #f43f5e;
            font-size: 11px;
            font-weight: 700;
            padding: 3px 10px;
            border-radius: 12px;
            animation: pulseTap 1.5s infinite;
        }

        @keyframes pulseTap {
            0% { transform: scale(0.96); opacity: 0.8; }
            50% { transform: scale(1.04); opacity: 1; }
            100% { transform: scale(0.96); opacity: 0.8; }
        }

        /* Slide-up Movie Action Sheet */
        .movie-sheet-overlay {
            position: fixed;
            inset: 0;
            z-index: 100;
            background: rgba(5, 8, 17, 0.82);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            display: flex;
            align-items: flex-end;
            justify-content: center;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease;
        }

        .movie-sheet-overlay.active {
            opacity: 1;
            pointer-events: auto;
        }

        .movie-sheet-card {
            width: 100%;
            max-width: 440px;
            max-height: 85vh;
            overflow-y: auto;
            background: linear-gradient(180deg, #131b2e 0%, #0a0f1d 100%);
            border: 1px solid rgba(244, 63, 94, 0.3);
            box-shadow: 0 -10px 40px rgba(0, 0, 0, 0.85), 0 0 30px rgba(244, 63, 94, 0.2);
            border-radius: 28px 28px 0 0;
            padding: 22px 18px 26px 18px;
            transform: translateY(100%);
            transition: transform 0.35s cubic-bezier(0.175, 0.885, 0.32, 1.2);
            position: relative;
        }

        .movie-sheet-overlay.active .movie-sheet-card {
            transform: translateY(0);
        }

        .sheet-close-btn {
            position: absolute;
            top: 16px;
            right: 18px;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.1);
            color: #94a3b8;
            border: none;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 15px;
            font-weight: 700;
        }

        .sheet-content {
            display: flex;
            gap: 14px;
            margin-bottom: 16px;
        }

        .sheet-poster {
            width: 95px;
            height: 140px;
            border-radius: 12px;
            object-fit: cover;
            border: 1px solid rgba(255, 255, 255, 0.15);
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.6);
            flex-shrink: 0;
            background: #0f172a;
        }

        .sheet-meta {
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 5px;
            min-width: 0;
        }

        .sheet-title {
            font-size: 17px;
            font-weight: 800;
            color: #ffffff;
            line-height: 1.25;
        }

        .sheet-badges {
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            margin: 4px 0;
        }

        .meta-pill {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.12);
            padding: 3px 8px;
            border-radius: 8px;
            font-size: 11px;
            font-weight: 700;
            color: #cbd5e1;
        }

        .meta-pill-rating {
            background: rgba(245, 158, 11, 0.2);
            border-color: rgba(245, 158, 11, 0.4);
            color: #fbbf24;
        }

        .meta-pill-type {
            background: rgba(168, 85, 247, 0.2);
            border-color: rgba(168, 85, 247, 0.4);
            color: #c084fc;
        }

        .meta-pill-size {
            background: rgba(56, 189, 248, 0.15);
            border-color: rgba(56, 189, 248, 0.35);
            color: #38bdf8;
        }

        .meta-pill-audio {
            background: rgba(16, 185, 129, 0.15);
            border-color: rgba(16, 185, 129, 0.35);
            color: #34d399;
        }

        /* Quality Download Buttons Section */
        .quality-section-title {
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: #94a3b8;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .quality-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(125px, 1fr));
            gap: 8px;
            margin-bottom: 14px;
        }

        .btn-qual-download {
            background: linear-gradient(135deg, rgba(30, 41, 59, 0.85) 0%, rgba(15, 23, 42, 0.95) 100%);
            border: 1px solid rgba(56, 189, 248, 0.3);
            border-radius: 12px;
            padding: 10px 12px;
            color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 13px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .btn-qual-download:hover, .btn-qual-download:active {
            background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
            border-color: #38bdf8;
            transform: translateY(-1px);
            box-shadow: 0 4px 15px rgba(2, 132, 199, 0.4);
        }

        .btn-qual-download .q-name {
            color: #38bdf8;
            font-weight: 800;
        }

        .btn-qual-download:active .q-name {
            color: #ffffff;
        }

        .btn-qual-download .q-size {
            font-size: 10px;
            color: #94a3b8;
            font-weight: 600;
            background: rgba(0, 0, 0, 0.3);
            padding: 2px 6px;
            border-radius: 6px;
        }

        /* Action Buttons */
        .sheet-actions {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .btn-bot-primary {
            width: 100%;
            padding: 13px;
            border-radius: 16px;
            border: none;
            background: linear-gradient(135deg, #f43f5e 0%, #e11d48 50%, #be123c 100%);
            color: #ffffff;
            font-size: 14px;
            font-weight: 800;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            cursor: pointer;
            box-shadow: 0 6px 20px rgba(225, 29, 72, 0.35), 0 0 25px rgba(244, 63, 94, 0.2);
            text-decoration: none;
            transition: transform 0.15s ease;
        }

        .btn-bot-primary:active {
            transform: scale(0.97);
        }

        .delivery-note {
            text-align: center;
            font-size: 11px;
            color: #64748b;
            margin-top: 4px;
        }
    </style>
</head>
<body>

    <!-- 3D WebGL Canvas Layer -->
    <canvas id="webglCanvas"></canvas>
    <div class="vignette-overlay"></div>

    <!-- Top HUD Controls with Real-time Search -->
    <div class="hud-header">
        <div class="brand-logo">
            <span>🪐</span>
            <span>MovieVerse 3D</span>
        </div>
        <div class="search-bar-wrap">
            <span class="search-icon-left">🔍</span>
            <input type="text" id="galaxySearchInput" class="search-input" placeholder="Search 3D Orbit..." value="__INITIAL_QUERY__" />
            <div class="search-spinner" id="searchSpinner"></div>
            <button class="search-clear-btn" id="clearSearchBtn" onclick="clearSearch()">✕</button>
        </div>
    </div>

    <!-- Category Filter Pills -->
    <div class="hud-pills">
        <button class="filter-btn active" onclick="applyCategoryFilter('all')">🪐 All</button>
        <button class="filter-btn" onclick="applyCategoryFilter('movies')">🎬 Movies</button>
        <button class="filter-btn" onclick="applyCategoryFilter('series')">📺 Series</button>
    </div>

    <!-- Center Search Results Banner -->
    <div class="search-banner" id="searchBanner"></div>

    <!-- Swipe Guide -->
    <div class="swipe-hint" id="swipeHint">
        <span>👈</span> <span>Swipe to Rotate 3D Orbit</span> <span>👉</span>
    </div>

    <!-- Bottom Focused Title Badge -->
    <div class="focused-title-bar" id="focusedTitleBar">
        <div class="focused-title" id="focusedTitleText">Loading Universe...</div>
        <div class="focused-sub" id="focusedSubText">
            <span class="tap-prompt-badge">👆 Tap Card to Get Files in Bot</span>
        </div>
    </div>

    <!-- Slide-up Movie Action Sheet -->
    <div class="movie-sheet-overlay" id="movieSheet">
        <div class="movie-sheet-card">
            <button class="sheet-close-btn" onclick="closeMovieSheet()">✕</button>
            <div class="sheet-content">
                <img id="sheetPosterImg" class="sheet-poster" src="" alt="Poster" />
                <div class="sheet-meta">
                    <div class="sheet-title" id="sheetTitleText">Movie Title</div>
                    <div class="sheet-badges" id="sheetBadgesContainer">
                        <span class="meta-pill meta-pill-rating">⭐ 8.2 IMDb</span>
                        <span class="meta-pill meta-pill-type">🎬 Movie</span>
                    </div>
                </div>
            </div>

            <!-- Quality Download Options -->
            <div class="quality-section-title">
                <span>⚡ Available File Qualities:</span>
            </div>
            <div class="quality-grid" id="sheetQualityGrid">
                <!-- Dynamically generated quality buttons -->
            </div>

            <div class="sheet-actions">
                <button id="sheetBotBtn" class="btn-bot-primary">
                    <span>🤖</span> <span>Get All Qualities / Episodes in Bot ↗️</span>
                </button>
                <div class="delivery-note">
                    🔒 Files deliver directly into your Telegram bot chat
                </div>
            </div>
        </div>
    </div>

    <script>
        // Telegram Mini App Initialization
        if (window.Telegram && window.Telegram.WebApp) {
            window.Telegram.WebApp.ready();
            window.Telegram.WebApp.expand();
            try {
                window.Telegram.WebApp.setHeaderColor('#050811');
                window.Telegram.WebApp.setBackgroundColor('#050811');
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
                osc.frequency.setValueAtTime(440, actx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(150, actx.currentTime + 0.05);
                gain.gain.setValueAtTime(0.12, actx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, actx.currentTime + 0.05);
                osc.connect(gain);
                gain.connect(actx.destination);
                osc.start();
                osc.stop(actx.currentTime + 0.05);
            } catch (e) {}
        }

        function playChime() {
            try {
                const actx = getAudioContext();
                [587.33, 880].forEach((freq, idx) => {
                    const osc = actx.createOscillator();
                    const gain = actx.createGain();
                    osc.type = "triangle";
                    osc.frequency.value = freq;
                    gain.gain.setValueAtTime(0.18, actx.currentTime + idx * 0.08);
                    gain.gain.exponentialRampToValueAtTime(0.001, actx.currentTime + idx * 0.08 + 0.25);
                    osc.connect(gain);
                    gain.connect(actx.destination);
                    osc.start(actx.currentTime + idx * 0.08);
                    osc.stop(actx.currentTime + idx * 0.08 + 0.25);
                });
            } catch (e) {}
        }

        function triggerHaptic(type = "light") {
            try {
                if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.HapticFeedback) {
                    window.Telegram.WebApp.HapticFeedback.impactOccurred(type);
                }
            } catch (e) {}
        }

        // Dynamic Raw Media Data from Backend Catalog
        let RAW_CATALOG = __CATALOG_JSON__;

        // Three.js 3D Engine Setup
        const canvas = document.getElementById("webglCanvas");
        const scene = new THREE.Scene();
        scene.fog = new THREE.FogExp2(0x050811, 0.022);

        const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 1000);
        camera.position.set(0, 1.8, 24);

        const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

        // Ambient and Point Lights
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.85);
        scene.add(ambientLight);

        const coreLight = new THREE.PointLight(0xf43f5e, 2.5, 45);
        coreLight.position.set(0, 0, 0);
        scene.add(coreLight);

        // 1. Particle Starfield
        const starGeo = new THREE.BufferGeometry();
        const starCount = 2000;
        const starPos = new Float32Array(starCount * 3);
        for (let i = 0; i < starCount * 3; i += 3) {
            starPos[i] = (Math.random() - 0.5) * 160;
            starPos[i + 1] = (Math.random() - 0.5) * 160;
            starPos[i + 2] = (Math.random() - 0.5) * 160;
        }
        starGeo.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
        const starMat = new THREE.PointsMaterial({ color: 0x94a3b8, size: 0.65, transparent: true, opacity: 0.8 });
        const starField = new THREE.Points(starGeo, starMat);
        scene.add(starField);

        // 2. Cosmic Nebula Center Core (MovieVerse Sun)
        const coreGeo = new THREE.SphereGeometry(1.8, 32, 32);
        const coreMat = new THREE.MeshBasicMaterial({ color: 0xf43f5e, wireframe: true, transparent: true, opacity: 0.65 });
        const cosmicCore = new THREE.Mesh(coreGeo, coreMat);
        scene.add(cosmicCore);

        // Orbit Group holding all 3D Movie Cards
        const orbitGroup = new THREE.Group();
        scene.add(orbitGroup);

        const textureLoader = new THREE.TextureLoader();
        let cardMeshes = [];
        let activeFilter = 'all';

        // Helper to generate sleek canvas fallback texture
        function createPosterCanvas(titleText) {
            const c = document.createElement("canvas");
            c.width = 400;
            c.height = 600;
            const cx = c.getContext("2d");
            const grad = cx.createLinearGradient(0, 0, 400, 600);
            grad.addColorStop(0, "#1e293b");
            grad.addColorStop(1, "#0f172a");
            cx.fillStyle = grad;
            cx.fillRect(0, 0, 400, 600);
            cx.fillStyle = "#f43f5e";
            cx.font = "bold 32px sans-serif";
            cx.textAlign = "center";
            cx.fillText("🪐 MovieVerse", 200, 260);
            cx.fillStyle = "#ffffff";
            cx.font = "bold 22px sans-serif";
            cx.fillText(titleText || "Movie", 200, 320);
            return new THREE.CanvasTexture(c);
        }

        // Build 3D Orbit Cards
        function buildOrbit(filter = 'all') {
            // Clear existing
            while (orbitGroup.children.length > 0) {
                orbitGroup.remove(orbitGroup.children[0]);
            }
            cardMeshes = [];

            const filtered = RAW_CATALOG.filter(item => {
                if (filter === 'movies') return !item.is_series;
                if (filter === 'series') return item.is_series;
                return true;
            });

            if (filtered.length === 0) {
                document.getElementById("focusedTitleText").innerText = "No Files in Orbit";
                return;
            }

            const total = Math.min(filtered.length, 28);
            const radius = 13.5;
            const cardW = 3.2;
            const cardH = 4.8;

            for (let i = 0; i < total; i++) {
                const item = filtered[i];
                const angle = (i / total) * Math.PI * 2;

                const cardBox = new THREE.BoxGeometry(cardW, cardH, 0.12);

                // Front Texture
                let frontMat;
                if (item.poster_url) {
                    const tex = textureLoader.load(item.poster_url);
                    frontMat = new THREE.MeshBasicMaterial({ map: tex });
                } else {
                    frontMat = new THREE.MeshBasicMaterial({ map: createPosterCanvas(item.clean_name) });
                }

                const edgeMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.3, metalness: 0.8 });
                const backMat = new THREE.MeshStandardMaterial({ color: 0x0a0f1d, roughness: 0.4, metalness: 0.9 });

                const materials = [
                    edgeMat, // Right
                    edgeMat, // Left
                    edgeMat, // Top
                    edgeMat, // Bottom
                    frontMat, // Front Face (Poster)
                    backMat  // Back Face
                ];

                const mesh = new THREE.Mesh(cardBox, materials);
                mesh.position.x = radius * Math.sin(angle);
                mesh.position.z = radius * Math.cos(angle);
                mesh.position.y = 0;
                mesh.rotation.y = angle; // Facing outward

                mesh.userData = {
                    item: item,
                    angle: angle,
                    baseScale: 1.0
                };

                orbitGroup.add(mesh);
                cardMeshes.push(mesh);
            }
        }

        buildOrbit(activeFilter);

        // Interaction Variables
        let isDragging = false;
        let previousMouseX = 0;
        let rotationVelocity = 0;
        let lastTickIndex = -1;

        // Touch & Mouse Event Handlers
        window.addEventListener("mousedown", (e) => {
            if (e.target.closest(".hud-header") || e.target.closest(".hud-pills") || e.target.closest(".movie-sheet-card")) return;
            isDragging = true;
            previousMouseX = e.clientX;
            getAudioContext();
        });

        window.addEventListener("mousemove", (e) => {
            if (!isDragging) return;
            const deltaX = e.clientX - previousMouseX;
            previousMouseX = e.clientX;
            rotationVelocity = deltaX * 0.004;
            orbitGroup.rotation.y += rotationVelocity;
        });

        window.addEventListener("mouseup", () => {
            isDragging = false;
        });

        // Touch Listeners for Mobile
        window.addEventListener("touchstart", (e) => {
            if (e.target.closest(".hud-header") || e.target.closest(".hud-pills") || e.target.closest(".movie-sheet-card")) return;
            if (e.touches.length === 1) {
                isDragging = true;
                previousMouseX = e.touches[0].clientX;
                getAudioContext();
            }
        }, { passive: true });

        window.addEventListener("touchmove", (e) => {
            if (!isDragging || e.touches.length !== 1) return;
            const deltaX = e.touches[0].clientX - previousMouseX;
            previousMouseX = e.touches[0].clientX;
            rotationVelocity = deltaX * 0.0055;
            orbitGroup.rotation.y += rotationVelocity;
        }, { passive: true });

        window.addEventListener("touchend", () => {
            isDragging = false;
        });

        // Raycasting for Card Click Selection
        const raycaster = new THREE.Raycaster();
        const mouseVec = new THREE.Vector2();

        function handleCardSelection(clientX, clientY) {
            mouseVec.x = (clientX / window.innerWidth) * 2 - 1;
            mouseVec.y = -(clientY / window.innerHeight) * 2 + 1;
            raycaster.setFromCamera(mouseVec, camera);

            const intersects = raycaster.intersectObjects(cardMeshes);
            if (intersects.length > 0) {
                const clickedMesh = intersects[0].object;
                const item = clickedMesh.userData.item;
                if (item) {
                    playChime();
                    triggerHaptic("medium");
                    openMovieSheet(item);
                }
            }
        }

        window.addEventListener("click", (e) => {
            if (Math.abs(rotationVelocity) > 0.002) return;
            // Ignore clicks if on header, pills or sheet
            if (e.target.closest(".hud-header") || e.target.closest(".hud-pills") || e.target.closest(".movie-sheet-card")) return;
            handleCardSelection(e.clientX, e.clientY);
        });

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

        // Open Bottom Action Sheet
        function openMovieSheet(item) {
            document.getElementById("sheetTitleText").innerText = item.title || item.clean_name;
            const posterImg = document.getElementById("sheetPosterImg");
            posterImg.src = item.poster_url || "";
            posterImg.onerror = () => { posterImg.src = "https://api.aniwallpaper.workers.dev/random"; };

            // Render badges
            const badgesBox = document.getElementById("sheetBadgesContainer");
            badgesBox.innerHTML = "";
            
            const ratingPill = document.createElement("span");
            ratingPill.className = "meta-pill meta-pill-rating";
            ratingPill.innerText = `⭐ ${item.rating || '8.2'} IMDb`;
            badgesBox.appendChild(ratingPill);

            const typePill = document.createElement("span");
            typePill.className = "meta-pill meta-pill-type";
            typePill.innerText = item.is_series ? "📺 Web Series" : "🎬 Movie";
            badgesBox.appendChild(typePill);

            if (item.total_size) {
                const sizePill = document.createElement("span");
                sizePill.className = "meta-pill meta-pill-size";
                sizePill.innerText = `📦 ${item.total_size}`;
                badgesBox.appendChild(sizePill);
            }

            if (item.languages && item.languages.length > 0) {
                const audPill = document.createElement("span");
                audPill.className = "meta-pill meta-pill-audio";
                audPill.innerText = item.languages.includes("Multi Audio") ? "🌐 Multi Audio" : `🌐 ${item.languages.slice(0, 2).join(" • ")}`;
                badgesBox.appendChild(audPill);
            }

            // Populate Quality Grid
            const qualGrid = document.getElementById("sheetQualityGrid");
            qualGrid.innerHTML = "";

            const qualityFiles = item.quality_files || [];
            if (qualityFiles.length > 0) {
                qualityFiles.forEach(qf => {
                    const btn = document.createElement("button");
                    btn.className = "btn-qual-download";
                    const qName = qf.quality || "HD";
                    const is4k = qName.toLowerCase().includes("2160") || qName.toLowerCase().includes("4k");
                    const icon = is4k ? "💎" : "📥";
                    btn.innerHTML = `
                        <span class="q-icon">${icon}</span>
                        <span class="q-name">${qName}</span>
                        <span class="q-size">${qf.size || ''}</span>
                    `;
                    btn.onclick = () => downloadQualityFile(qf.bot_url);
                    qualGrid.appendChild(btn);
                });
            } else {
                const notice = document.createElement("div");
                notice.style.fontSize = "12px";
                notice.style.color = "#94a3b8";
                notice.style.padding = "6px 0";
                notice.innerText = "All qualities available via bot command:";
                qualGrid.appendChild(notice);
            }

            // Main Bot Deep Link Button
            const botBtn = document.getElementById("sheetBotBtn");
            botBtn.onclick = () => downloadQualityFile(item.bot_url);

            document.getElementById("movieSheet").classList.add("active");
            document.getElementById("focusedTitleBar").style.opacity = "0";
        }

        function closeMovieSheet() {
            document.getElementById("movieSheet").classList.remove("active");
            document.getElementById("focusedTitleBar").style.opacity = "1";
            triggerHaptic("light");
        }

        // Live Real-Time Search Handler
        let searchTimeout = null;
        const searchInput = document.getElementById("galaxySearchInput");
        const clearBtn = document.getElementById("clearSearchBtn");
        const searchSpinner = document.getElementById("searchSpinner");
        const searchBanner = document.getElementById("searchBanner");

        if (searchInput.value.trim()) {
            clearBtn.style.display = "flex";
            searchBanner.innerText = `✨ Exploring matches for "${searchInput.value.trim()}"`;
            searchBanner.style.display = "block";
        }

        searchInput.addEventListener("input", (e) => {
            const query = e.target.value.trim();
            clearBtn.style.display = query ? "flex" : "none";
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                performLiveSearch(query);
            }, 320);
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
                    buildOrbit(activeFilter);
                    playChime();
                    triggerHaptic("medium");

                    if (query && data.results.length === 0) {
                        searchBanner.innerText = `🌌 No cosmic files found for "${query}"`;
                        searchBanner.style.display = "block";
                    } else if (query) {
                        searchBanner.innerText = `✨ Found ${data.results.length} files in 3D Orbit for "${query}"`;
                        searchBanner.style.display = "block";
                    } else {
                        searchBanner.style.display = "none";
                    }
                }
            } catch (err) {
                console.error("Galaxy search error:", err);
            } finally {
                searchSpinner.style.display = "none";
            }
        }

        // Category Filter Switcher
        function applyCategoryFilter(cat) {
            activeFilter = cat;
            document.querySelectorAll(".filter-btn").forEach(btn => btn.classList.remove("active"));
            event.target.classList.add("active");
            triggerHaptic("light");
            buildOrbit(cat);
        }

        // Window Resize
        window.addEventListener("resize", () => {
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight);
        });

        // Main Animation Loop
        function animate() {
            requestAnimationFrame(animate);

            // Rotate starfield slowly
            starField.rotation.y += 0.0003;
            cosmicCore.rotation.y += 0.005;
            cosmicCore.rotation.x += 0.003;

            // Apply inertia decay when not dragging
            if (!isDragging) {
                rotationVelocity *= 0.94;
                orbitGroup.rotation.y += rotationVelocity;
            }

            // Determine front-most focused card
            let minDistanceToCamera = Infinity;
            let frontMesh = null;
            let frontIndex = 0;

            cardMeshes.forEach((mesh, idx) => {
                const worldPos = new THREE.Vector3();
                mesh.getWorldPosition(worldPos);
                const dist = worldPos.distanceTo(camera.position);

                if (dist < minDistanceToCamera) {
                    minDistanceToCamera = dist;
                    frontMesh = mesh;
                    frontIndex = idx;
                }

                // Smooth scale-up for cards close to front camera
                if (dist < 14) {
                    const scaleFactor = 1.0 + (14 - dist) * 0.035;
                    mesh.scale.set(scaleFactor, scaleFactor, scaleFactor);
                } else {
                    mesh.scale.set(1, 1, 1);
                }
            });

            // Update focused title in bottom HUD
            if (frontMesh && frontMesh.userData.item) {
                const item = frontMesh.userData.item;
                document.getElementById("focusedTitleText").innerText = item.title || item.clean_name;
                
                // Play subtle tick on switching front card
                if (frontIndex !== lastTickIndex && Math.abs(rotationVelocity) > 0.001) {
                    lastTickIndex = frontIndex;
                    playOrbTick();
                    triggerHaptic("light");
                }
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
    return html
