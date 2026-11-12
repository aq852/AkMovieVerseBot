"""Flixify / AkMovieVerse 3D — Futuristic 3D Cinema Showcase & File Delivery Mini App.
Features:
1. Hero 3D Card Mode for single searched titles with interactive 3D parallax tilt & cosmic aura.
2. Smooth 3D Carousel for multiple titles.
3. Top Brand Header with centered full-width search bar below it (zero filter clutter).
4. Vertical optical centering of cards.
5. Rich Full-Screen Cinema Post Modal on tap with complete episodes, season packs, and quality prints.
6. 1-tap direct Telegram Bot file delivery with 100% shortener / VIP monetization.
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

        /* Ambient Cosmic Vignette */
        .vignette-overlay {
            position: fixed;
            inset: 0;
            pointer-events: none;
            background: radial-gradient(circle at center, transparent 30%, rgba(5, 8, 17, 0.7) 75%, #050811 100%);
            z-index: 2;
        }

        /* Top HUD Navigation Bar */
        .top-nav {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 20;
            padding: 14px 16px 10px 16px;
            display: flex;
            flex-direction: column;
            align-items: center;
            background: linear-gradient(180deg, rgba(5, 8, 17, 0.95) 0%, rgba(5, 8, 17, 0.6) 80%, rgba(5, 8, 17, 0) 100%);
        }

        .brand-title {
            font-size: 17px;
            font-weight: 900;
            color: #f43f5e;
            letter-spacing: 0.8px;
            text-shadow: 0 0 18px rgba(244, 63, 94, 0.6);
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
            background: rgba(18, 24, 38, 0.85);
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
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
            user-select: auto;
            -webkit-user-select: auto;
        }

        .search-input:focus {
            border-color: #f43f5e;
            box-shadow: 0 0 20px rgba(244, 63, 94, 0.45);
            background: rgba(22, 30, 48, 0.95);
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
            opacity: 0.7;
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
            bottom: 24px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 20;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 6px;
            pointer-events: none;
        }

        .tap-prompt-badge {
            background: linear-gradient(135deg, rgba(244, 63, 94, 0.25) 0%, rgba(225, 29, 72, 0.35) 100%);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(244, 63, 94, 0.5);
            color: #ffffff;
            font-size: 12px;
            font-weight: 700;
            padding: 6px 16px;
            border-radius: 20px;
            box-shadow: 0 4px 18px rgba(244, 63, 94, 0.3);
            display: flex;
            align-items: center;
            gap: 6px;
            animation: pulseTap 1.8s infinite;
        }

        @keyframes pulseTap {
            0% { transform: scale(0.97); opacity: 0.85; }
            50% { transform: scale(1.03); opacity: 1; }
            100% { transform: scale(0.97); opacity: 0.85; }
        }

        .movie-title-preview {
            font-size: 15px;
            font-weight: 800;
            color: #ffffff;
            text-shadow: 0 2px 10px rgba(0, 0, 0, 0.9);
            max-width: 290px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            text-align: center;
        }

        /* ------------------------------------------------------------- */
        /* FULL-SCREEN CINEMA POST MODAL (Styled like Website Post Page) */
        /* ------------------------------------------------------------- */
        .cinema-post-modal {
            position: fixed;
            inset: 0;
            z-index: 100;
            background: #07090e;
            color: #f1f5f9;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
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

        .modal-top-bar {
            position: sticky;
            top: 0;
            z-index: 50;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 14px 18px;
            background: rgba(7, 9, 14, 0.85);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }

        .modal-brand {
            font-size: 14px;
            font-weight: 800;
            color: #f43f5e;
            display: flex;
            align-items: center;
            gap: 6px;
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
            background: rgba(244, 63, 94, 0.3);
        }

        /* Hero Backdrop & Poster Banner */
        .modal-hero {
            position: relative;
            padding: 20px 16px 24px 16px;
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
            filter: blur(32px) brightness(0.28) saturate(1.4);
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
            width: 175px;
            aspect-ratio: 2/3;
            border-radius: 16px;
            overflow: hidden;
            border: 1px solid rgba(255, 255, 255, 0.2);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8), 0 0 30px rgba(244, 63, 94, 0.25);
            background: #0f172a;
            margin-bottom: 14px;
        }

        .modal-poster-img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }

        .modal-title {
            font-size: 20px;
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
            background: rgba(15, 23, 42, 0.6);
            border-left: 3px solid #f43f5e;
            padding: 8px 12px;
            border-radius: 0 10px 10px 0;
            margin-top: 4px;
            text-align: left;
            width: 100%;
        }

        /* Content Section: Prints or Episodes */
        .modal-body {
            padding: 16px 18px 90px 18px;
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
            font-size: 14px;
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
            background: rgba(22, 30, 48, 0.75);
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
            background: rgba(30, 42, 68, 0.95);
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

        /* Sticky Bottom Action Bar */
        .modal-bottom-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            z-index: 50;
            padding: 12px 18px 16px 18px;
            background: linear-gradient(180deg, rgba(7, 9, 14, 0.8) 0%, #07090e 100%);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border-top: 1px solid rgba(255, 255, 255, 0.08);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 6px;
        }

        .btn-all-in-bot {
            width: 100%;
            max-width: 500px;
            padding: 13px;
            border-radius: 14px;
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
            box-shadow: 0 6px 20px rgba(225, 29, 72, 0.4);
            text-decoration: none;
        }

        .btn-all-in-bot:active {
            transform: scale(0.97);
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
        <div class="tap-prompt-badge">
            <span>👆</span>
            <span>Tap Poster to View Files &amp; Episodes</span>
        </div>
    </div>

    <!-- ------------------------------------------------------------- -->
    <!-- FULL-SCREEN CINEMA POST MODAL (Styled like Website Post Page) -->
    <!-- ------------------------------------------------------------- -->
    <div class="cinema-post-modal" id="cinemaModal">
        <div class="modal-top-bar">
            <div class="modal-brand">
                <span>🍿</span> <span>AkMovieVerse Cinema</span>
            </div>
            <button class="modal-close-btn" onclick="closeCinemaModal()">✕</button>
        </div>

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

        <!-- Sticky Bottom Delivery Button -->
        <div class="modal-bottom-bar">
            <button id="modalBotAllBtn" class="btn-all-in-bot">
                <span>🤖</span> <span>Get All Files / Episodes in Bot ↗️</span>
            </button>
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
                osc.frequency.setValueAtTime(480, actx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(160, actx.currentTime + 0.04);
                gain.gain.setValueAtTime(0.08, actx.currentTime);
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
                    osc.type = "triangle";
                    osc.frequency.value = freq;
                    gain.gain.setValueAtTime(0.16, actx.currentTime + idx * 0.08);
                    gain.gain.exponentialRampToValueAtTime(0.001, actx.currentTime + idx * 0.08 + 0.22);
                    osc.connect(gain);
                    gain.connect(actx.destination);
                    osc.start(actx.currentTime + idx * 0.08);
                    osc.stop(actx.currentTime + idx * 0.08 + 0.22);
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
        scene.fog = new THREE.FogExp2(0x050811, 0.024);

        const camera = new THREE.PerspectiveCamera(48, window.innerWidth / window.innerHeight, 0.1, 1000);
        // Position camera to frame poster right in optical center (y = 0.4)
        camera.position.set(0, 0.4, 14.5);
        camera.lookAt(0, 0.4, 0);

        const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

        // Ambient & Cosmic Lights
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.9);
        scene.add(ambientLight);

        const coreLight = new THREE.PointLight(0xf43f5e, 2.8, 50);
        coreLight.position.set(0, 0.4, 0);
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

        // 2. Cosmic Pulsing Halo Aura for Hero Card
        const haloGeo = new THREE.RingGeometry(3.6, 4.4, 48);
        const haloMat = new THREE.MeshBasicMaterial({ color: 0xf43f5e, side: THREE.DoubleSide, transparent: true, opacity: 0.35, wireframe: true });
        const cosmicHalo = new THREE.Mesh(haloGeo, haloMat);
        cosmicHalo.position.set(0, 0.4, -0.6);
        scene.add(cosmicHalo);

        // Group holding 3D Card(s)
        const cardsGroup = new THREE.Group();
        cardsGroup.position.set(0, 0.4, 0);
        scene.add(cardsGroup);

        const textureLoader = new THREE.TextureLoader();
        let cardMeshes = [];
        let isSingleHeroMode = true;

        // Fallback texture canvas generator
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
            cx.font = "bold 34px sans-serif";
            cx.textAlign = "center";
            cx.fillText("🪐 MovieVerse", 200, 260);
            cx.fillStyle = "#ffffff";
            cx.font = "bold 22px sans-serif";
            cx.fillText(titleText || "Movie", 200, 320);
            return new THREE.CanvasTexture(c);
        }

        // Build 3D Cards Scene (Hero Mode for 1 result vs Smooth Arc Carousel for multiple)
        function build3DScene() {
            while (cardsGroup.children.length > 0) {
                cardsGroup.remove(cardsGroup.children[0]);
            }
            cardMeshes = [];

            if (!RAW_CATALOG || RAW_CATALOG.length === 0) {
                document.getElementById("movieTitlePreview").innerText = "No Matching Files Found";
                cosmicHalo.visible = false;
                return;
            }

            const total = RAW_CATALOG.length;
            isSingleHeroMode = (total === 1);
            cosmicHalo.visible = true;

            const cardW = 3.6;
            const cardH = 5.4;
            const cardD = 0.14;

            if (isSingleHeroMode) {
                // HERO MODE: 1 Single Card perfectly centered with floating oscillation and touch tilt
                const item = RAW_CATALOG[0];
                const cardBox = new THREE.BoxGeometry(cardW, cardH, cardD);

                let frontMat;
                if (item.poster_url) {
                    const tex = textureLoader.load(item.poster_url);
                    frontMat = new THREE.MeshBasicMaterial({ map: tex });
                } else {
                    frontMat = new THREE.MeshBasicMaterial({ map: createPosterCanvas(item.clean_name) });
                }

                const edgeMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.3, metalness: 0.8 });
                const backMat = new THREE.MeshStandardMaterial({ color: 0x0a0f1d, roughness: 0.4, metalness: 0.9 });
                const materials = [edgeMat, edgeMat, edgeMat, edgeMat, frontMat, backMat];

                const mesh = new THREE.Mesh(cardBox, materials);
                mesh.position.set(0, 0, 0);
                mesh.userData = { item: item, baseScale: 1.0 };

                cardsGroup.add(mesh);
                cardMeshes.push(mesh);
                cardsGroup.rotation.set(0, 0, 0);
                document.getElementById("movieTitlePreview").innerText = item.title || item.clean_name;
            } else {
                // CAROUSEL MODE: Multiple cards arranged in a smooth circular arc
                const count = Math.min(total, 24);
                const radius = 10.5;

                for (let i = 0; i < count; i++) {
                    const item = RAW_CATALOG[i];
                    const angle = (i / count) * Math.PI * 2;
                    const cardBox = new THREE.BoxGeometry(cardW, cardH, cardD);

                    let frontMat;
                    if (item.poster_url) {
                        const tex = textureLoader.load(item.poster_url);
                        frontMat = new THREE.MeshBasicMaterial({ map: tex });
                    } else {
                        frontMat = new THREE.MeshBasicMaterial({ map: createPosterCanvas(item.clean_name) });
                    }

                    const edgeMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.3, metalness: 0.8 });
                    const backMat = new THREE.MeshStandardMaterial({ color: 0x0a0f1d, roughness: 0.4, metalness: 0.9 });
                    const materials = [edgeMat, edgeMat, edgeMat, edgeMat, frontMat, backMat];

                    const mesh = new THREE.Mesh(cardBox, materials);
                    mesh.position.x = radius * Math.sin(angle);
                    mesh.position.z = radius * Math.cos(angle);
                    mesh.position.y = 0;
                    mesh.rotation.y = angle;

                    mesh.userData = { item: item, angle: angle, baseScale: 1.0 };
                    cardsGroup.add(mesh);
                    cardMeshes.push(mesh);
                }
            }
        }

        build3DScene();

        // 3D Parallax Tilt & Drag Interaction
        let isDragging = false;
        let startX = 0;
        let startY = 0;
        let previousMouseX = 0;
        let rotationVelocity = 0;
        let heroTiltX = 0;
        let heroTiltY = 0;
        let targetHeroTiltX = 0;
        let targetHeroTiltY = 0;
        let lastTickIndex = -1;

        // Pointer Events
        window.addEventListener("mousedown", (e) => {
            if (e.target.closest(".top-nav") || e.target.closest(".cinema-post-modal")) return;
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            previousMouseX = e.clientX;
            getAudioContext();
        });

        window.addEventListener("mousemove", (e) => {
            if (!isDragging) return;
            const deltaX = e.clientX - previousMouseX;
            previousMouseX = e.clientX;

            if (isSingleHeroMode) {
                // Interactive 3D Card Tilt
                targetHeroTiltY = (e.clientX - window.innerWidth / 2) * 0.0016;
                targetHeroTiltX = -(e.clientY - window.innerHeight / 2) * 0.0016;
            } else {
                // Rotate Carousel Orbit
                rotationVelocity = deltaX * 0.0045;
                cardsGroup.rotation.y += rotationVelocity;
            }
        });

        window.addEventListener("mouseup", () => {
            isDragging = false;
            targetHeroTiltX = 0;
            targetHeroTiltY = 0;
        });

        // Touch Listeners for Mobile
        window.addEventListener("touchstart", (e) => {
            if (e.target.closest(".top-nav") || e.target.closest(".cinema-post-modal")) return;
            if (e.touches.length === 1) {
                isDragging = true;
                startX = e.touches[0].clientX;
                startY = e.touches[0].clientY;
                previousMouseX = e.touches[0].clientX;
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
                rotationVelocity = deltaX * 0.0055;
                cardsGroup.rotation.y += rotationVelocity;
            }
        }, { passive: true });

        window.addEventListener("touchend", () => {
            isDragging = false;
            targetHeroTiltX = 0;
            targetHeroTiltY = 0;
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
                    openCinemaModal(item);
                }
            }
        }

        window.addEventListener("click", (e) => {
            if (Math.abs(rotationVelocity) > 0.002) return;
            if (e.target.closest(".top-nav") || e.target.closest(".cinema-post-modal")) return;
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

        // -------------------------------------------------------------
        // OPEN FULL CINEMA POST MODAL (Styled like Website Post Page)
        // -------------------------------------------------------------
        function openCinemaModal(item) {
            const modal = document.getElementById("cinemaModal");
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
                    // Fallback to quality buttons
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

        // Animation Loop with Smooth Floating Physics & 3D Parallax Tilt
        let clock = 0;
        function animate() {
            requestAnimationFrame(animate);
            clock += 0.016;

            // Rotate starfield slowly
            starField.rotation.y += 0.0003;
            cosmicHalo.rotation.z += 0.005;

            if (isSingleHeroMode && cardMeshes.length > 0) {
                // HERO MODE:
                // 1. Subtle smooth floating levitation
                const heroCard = cardMeshes[0];
                heroCard.position.y = Math.sin(clock * 1.6) * 0.12;

                // 2. Parallax 3D spring tilt on touch/drag
                heroTiltX += (targetHeroTiltX - heroTiltX) * 0.12;
                heroTiltY += (targetHeroTiltY - heroTiltY) * 0.12;
                heroCard.rotation.x = heroTiltX;
                heroCard.rotation.y = heroTiltY;

                // Pulsing Halo behind card
                cosmicHalo.scale.set(1 + Math.sin(clock * 2) * 0.04, 1 + Math.sin(clock * 2) * 0.04, 1);
            } else if (cardMeshes.length > 0) {
                // CAROUSEL MODE: Apply inertia decay when not dragging
                if (!isDragging) {
                    rotationVelocity *= 0.94;
                    cardsGroup.rotation.y += rotationVelocity;
                }

                // Focus front-most card
                let minDistance = Infinity;
                let frontMesh = null;
                let frontIndex = 0;

                cardMeshes.forEach((mesh, idx) => {
                    const worldPos = new THREE.Vector3();
                    mesh.getWorldPosition(worldPos);
                    const dist = worldPos.distanceTo(camera.position);

                    if (dist < minDistance) {
                        minDistance = dist;
                        frontMesh = mesh;
                        frontIndex = idx;
                    }

                    if (dist < 11.5) {
                        const sc = 1.0 + (11.5 - dist) * 0.04;
                        mesh.scale.set(sc, sc, sc);
                    } else {
                        mesh.scale.set(1, 1, 1);
                    }
                });

                if (frontMesh && frontMesh.userData.item) {
                    const item = frontMesh.userData.item;
                    document.getElementById("movieTitlePreview").innerText = item.title || item.clean_name;

                    if (frontIndex !== lastTickIndex && Math.abs(rotationVelocity) > 0.001) {
                        lastTickIndex = frontIndex;
                        playOrbTick();
                        triggerHaptic("light");
                    }
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
