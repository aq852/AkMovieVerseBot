"""Flixify 3D Lucky Wheel Telegram Mini App (WebApp).
Provides rich, interactive HTML5 Canvas Lucky Wheel with Web Audio mechanical sound effects,
Telegram haptic feedback, real-time physics, confetti celebrations, and secure backend validation.
"""

from html import escape as html_escape
from config import Config

SPIN_WEBAPP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Flixify Lucky Wheel</title>
    <!-- Telegram Mini App SDK -->
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <!-- Canvas Confetti Celebration FX -->
    <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.3/dist/confetti.browser.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            user-select: none;
            -webkit-user-select: none;
        }

        body {
            background: #090d16;
            background: radial-gradient(circle at 50% 20%, #172138 0%, #090d16 80%);
            color: #ffffff;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: space-between;
            padding: 16px;
            overflow-x: hidden;
        }

        /* Top Bar & Profile Header */
        .top-container {
            width: 100%;
            max-width: 420px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .header-card {
            background: rgba(23, 33, 56, 0.65);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 12px 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
        }

        .user-info {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        .user-name {
            font-size: 15px;
            font-weight: 700;
            color: #f8fafc;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .user-rank {
            font-size: 11px;
            color: #94a3b8;
            font-weight: 500;
        }

        .stats-pill-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .stat-pill {
            background: rgba(15, 23, 42, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            padding: 6px 10px;
            display: flex;
            align-items: center;
            gap: 5px;
            font-size: 12px;
            font-weight: 700;
        }

        .coin-pill {
            color: #fbbf24;
            border-color: rgba(251, 191, 36, 0.25);
            box-shadow: 0 0 12px rgba(251, 191, 36, 0.15);
        }

        .streak-pill {
            color: #f87171;
            border-color: rgba(248, 113, 113, 0.25);
        }

        /* Wheel Stage Container */
        .wheel-container {
            position: relative;
            width: 330px;
            height: 330px;
            margin: auto;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        /* Ambient glowing aura behind wheel */
        .wheel-glow-aura {
            position: absolute;
            width: 300px;
            height: 300px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(99, 102, 241, 0.25) 0%, rgba(245, 158, 11, 0.15) 50%, transparent 70%);
            filter: blur(24px);
            z-index: 1;
            animation: pulseGlow 3s ease-in-out infinite alternate;
        }

        @keyframes pulseGlow {
            0% { transform: scale(0.95); opacity: 0.6; }
            100% { transform: scale(1.05); opacity: 1; }
        }

        #wheelCanvas {
            position: relative;
            z-index: 2;
            width: 320px;
            height: 320px;
            filter: drop-shadow(0 12px 24px rgba(0, 0, 0, 0.6));
        }

        /* Top Needle Pointer */
        .pointer-needle {
            position: absolute;
            top: -2px;
            left: 50%;
            transform: translateX(-50%);
            width: 32px;
            height: 38px;
            z-index: 10;
            filter: drop-shadow(0 4px 10px rgba(0, 0, 0, 0.8));
            pointer-events: none;
            transition: transform 0.05s ease-out;
        }

        .pointer-needle svg {
            width: 100%;
            height: 100%;
        }

        /* Center Hub Knob Button */
        .center-hub {
            position: absolute;
            width: 68px;
            height: 68px;
            border-radius: 50%;
            background: radial-gradient(circle at 35% 35%, #ffd700, #b8860b 70%, #5c4300 100%);
            border: 3px solid #fff3a8;
            box-shadow: 0 0 20px rgba(255, 215, 0, 0.6), inset 0 2px 4px rgba(255, 255, 255, 0.8);
            z-index: 5;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            font-weight: 900;
            color: #3d2600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            cursor: pointer;
            transition: transform 0.15s ease;
        }

        .center-hub:active {
            transform: scale(0.92);
        }

        /* Action & Footer Section */
        .action-container {
            width: 100%;
            max-width: 420px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin-top: 16px;
        }

        .btn-spin {
            width: 100%;
            padding: 16px;
            border-radius: 16px;
            border: none;
            outline: none;
            background: linear-gradient(135deg, #f59e0b 0%, #ea580c 50%, #dc2626 100%);
            color: #ffffff;
            font-size: 17px;
            font-weight: 800;
            letter-spacing: 0.5px;
            cursor: pointer;
            box-shadow: 0 6px 20px rgba(234, 88, 12, 0.4), 0 0 24px rgba(245, 158, 11, 0.3);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: all 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }

        .btn-spin:active:not(:disabled) {
            transform: scale(0.97);
        }

        .btn-spin:disabled {
            background: #1e293b;
            color: #64748b;
            box-shadow: none;
            cursor: not-allowed;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .helper-text {
            text-align: center;
            font-size: 12px;
            color: #94a3b8;
            line-height: 1.5;
        }

        .helper-text b {
            color: #fbbf24;
        }

        /* Result Celebration Modal */
        .modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(7, 11, 20, 0.85);
            backdrop-filter: blur(12px);
            z-index: 100;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 20px;
            opacity: 0;
            transition: opacity 0.3s ease;
        }

        .modal-overlay.active {
            display: flex;
            opacity: 1;
        }

        .modal-card {
            background: linear-gradient(165deg, rgba(30, 41, 59, 0.95), rgba(15, 23, 42, 0.95));
            border: 1px solid rgba(251, 191, 36, 0.3);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8), 0 0 30px rgba(245, 158, 11, 0.2);
            border-radius: 24px;
            width: 100%;
            max-width: 360px;
            padding: 28px 24px;
            text-align: center;
            transform: scale(0.85);
            transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }

        .modal-overlay.active .modal-card {
            transform: scale(1);
        }

        .modal-icon {
            font-size: 52px;
            margin-bottom: 8px;
            animation: bounceIcon 0.8s ease infinite alternate;
        }

        @keyframes bounceIcon {
            0% { transform: translateY(0); }
            100% { transform: translateY(-8px); }
        }

        .modal-title {
            font-size: 22px;
            font-weight: 800;
            color: #f8fafc;
            margin-bottom: 6px;
        }

        .modal-prize-tag {
            display: inline-block;
            background: rgba(251, 191, 36, 0.15);
            border: 1px solid rgba(251, 191, 36, 0.35);
            color: #fbbf24;
            font-size: 18px;
            font-weight: 800;
            padding: 8px 18px;
            border-radius: 14px;
            margin: 12px 0 16px 0;
        }

        .modal-desc {
            font-size: 13px;
            color: #94a3b8;
            margin-bottom: 22px;
            line-height: 1.5;
        }

        .btn-claim {
            width: 100%;
            padding: 14px;
            border-radius: 14px;
            border: none;
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: #ffffff;
            font-size: 16px;
            font-weight: 700;
            cursor: pointer;
            box-shadow: 0 4px 16px rgba(16, 185, 129, 0.35);
        }
    </style>
</head>
<body>

    <!-- Header Section -->
    <div class="top-container">
        <div class="header-card">
            <div class="user-info">
                <div class="user-name">
                    <span>👤</span>
                    <span>__USER_NAME__</span>
                </div>
                <div class="user-rank">__RANK__</div>
            </div>
            <div class="stats-pill-group">
                <div class="stat-pill coin-pill">
                    <span>🪙</span>
                    <span id="coin-val">__COINS__</span>
                </div>
                <div class="stat-pill streak-pill">
                    <span>🔥</span>
                    <span id="streak-val">__STREAK__</span>d
                </div>
            </div>
        </div>
    </div>

    <!-- 3D Lucky Wheel Center Stage -->
    <div class="wheel-container">
        <div class="wheel-glow-aura"></div>
        
        <!-- Top Precision Pointer Needle -->
        <div class="pointer-needle" id="pointerNeedle">
            <svg viewBox="0 0 32 38" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M16 38L2 10C-1 5 1 0 7 0H25C31 0 33 5 30 10L16 38Z" fill="url(#needleGrad)"/>
                <path d="M16 34L4 10C2 6 3 2 7 2H25C29 2 30 6 28 10L16 34Z" stroke="#FFE082" stroke-width="2"/>
                <defs>
                    <linearGradient id="needleGrad" x1="16" y1="0" x2="16" y2="38" gradientUnits="userSpaceOnUse">
                        <stop stop-color="#EF4444"/>
                        <stop offset="0.6" stop-color="#DC2626"/>
                        <stop offset="1" stop-color="#991B1B"/>
                    </linearGradient>
                </defs>
            </svg>
        </div>

        <!-- HTML5 Wheel Canvas -->
        <canvas id="wheelCanvas" width="640" height="640"></canvas>

        <!-- Center Interactive Hub -->
        <div class="center-hub" id="centerHub" onclick="handleSpinClick()">
            SPIN
        </div>
    </div>

    <!-- Action Section -->
    <div class="action-container">
        <button id="spinBtn" class="btn-spin" onclick="handleSpinClick()">
            <span>🎡</span>
            <span id="spinBtnLabel">TAP TO SPIN</span>
            <span>🎰</span>
        </button>
        <div class="helper-text" id="statusNote">
            🔥 <b>Maintain Daily Streak</b> for higher jackpot & VIP chances!
        </div>
    </div>

    <!-- Winner Celebration Modal -->
    <div class="modal-overlay" id="winnerModal">
        <div class="modal-card">
            <div class="modal-icon" id="modalIcon">🎉</div>
            <div class="modal-title" id="modalTitle">MUBARAK HO!</div>
            <div class="modal-prize-tag" id="modalPrizeTitle">+5 Coins</div>
            <div class="modal-desc" id="modalDesc">
                Aapke Flixify Wallet me reward successfully credit ho chuka hai!
            </div>
            <button class="btn-claim" onclick="closeRewardModal()">
                🚀 Claim Reward & Close
            </button>
        </div>
    </div>

    <script>
        // Initialize Telegram WebApp SDK
        if (window.Telegram && window.Telegram.WebApp) {
            window.Telegram.WebApp.ready();
            window.Telegram.WebApp.expand();
            try {
                window.Telegram.WebApp.setHeaderColor('#172138');
                window.Telegram.WebApp.setBackgroundColor('#090d16');
            } catch (e) {}
        }

        const USER_ID = __USER_ID__;
        const TOKEN = "__TOKEN__";
        let CAN_SPIN = __CAN_SPIN__;
        let isSpinning = false;
        let currentAngle = 0; // Current angle in degrees

        // Wheel Slices (8 Segments)
        // 0: 5c, 1: 1D VIP, 2: 10c, 3: PASS, 4: 20c, 5: 5c, 6: 3D VIP, 7: 10c
        const SEGMENTS = [
            { label: "5 Coins", icon: "🪙", color: "#059669", textCol: "#ffffff" },
            { label: "1D VIP", icon: "👑", color: "#d97706", textCol: "#ffffff", jackpot: true },
            { label: "10 Coins", icon: "🪙", color: "#2563eb", textCol: "#ffffff" },
            { label: "Direct Pass", icon: "⚡", color: "#7c3aed", textCol: "#ffffff" },
            { label: "20 Coins", icon: "🪙", color: "#4f46e5", textCol: "#ffffff" },
            { label: "5 Coins", icon: "🪙", color: "#0d9488", textCol: "#ffffff" },
            { label: "3D VIP", icon: "💎", color: "#db2777", textCol: "#ffffff", mega: true },
            { label: "10 Coins", icon: "🪙", color: "#ea580c", textCol: "#ffffff" }
        ];

        const canvas = document.getElementById("wheelCanvas");
        const ctx = canvas.getContext("2d");
        const spinBtn = document.getElementById("spinBtn");
        const spinBtnLabel = document.getElementById("spinBtnLabel");
        const needle = document.getElementById("pointerNeedle");

        // Web Audio Synthesizer for Authentic Mechanical Casino Ticks & Fanfare
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

        function playTickSound() {
            try {
                const actx = getAudioContext();
                const osc = actx.createOscillator();
                const gain = actx.createGain();
                osc.type = "triangle";
                osc.frequency.setValueAtTime(850, actx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(140, actx.currentTime + 0.035);
                gain.gain.setValueAtTime(0.28, actx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.01, actx.currentTime + 0.035);
                osc.connect(gain);
                gain.connect(actx.destination);
                osc.start();
                osc.stop(actx.currentTime + 0.035);
            } catch (e) {}
        }

        function playVictoryFanfare() {
            try {
                const actx = getAudioContext();
                const notes = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6
                notes.forEach((freq, idx) => {
                    const osc = actx.createOscillator();
                    const gain = actx.createGain();
                    osc.type = "sine";
                    osc.frequency.value = freq;
                    const startTime = actx.currentTime + (idx * 0.11);
                    gain.gain.setValueAtTime(0.35, startTime);
                    gain.gain.exponentialRampToValueAtTime(0.01, startTime + 0.35);
                    osc.connect(gain);
                    gain.connect(actx.destination);
                    osc.start(startTime);
                    osc.stop(startTime + 0.35);
                });
            } catch (e) {}
        }

        function triggerHaptic(type = "light") {
            try {
                if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.HapticFeedback) {
                    if (type === "success") {
                        window.Telegram.WebApp.HapticFeedback.notificationOccurred("success");
                    } else {
                        window.Telegram.WebApp.HapticFeedback.impactOccurred(type);
                    }
                }
            } catch (e) {}
        }

        // Draw the 3D Lucky Wheel on Canvas
        function drawWheel(angleDeg) {
            const width = canvas.width;
            const height = canvas.height;
            const cx = width / 2;
            const cy = height / 2;
            const radius = width / 2 - 28;
            const numSlices = SEGMENTS.length;
            const sliceAngle = (2 * Math.PI) / numSlices;

            ctx.clearRect(0, 0, width, height);

            ctx.save();
            ctx.translate(cx, cy);
            ctx.rotate((angleDeg * Math.PI) / 180);

            // 1. Draw outer gold bezel with 3D bevel
            ctx.beginPath();
            ctx.arc(0, 0, radius + 22, 0, 2 * Math.PI);
            ctx.fillStyle = "#1e293b";
            ctx.fill();

            ctx.beginPath();
            ctx.arc(0, 0, radius + 18, 0, 2 * Math.PI);
            const rimGrad = ctx.createLinearGradient(-radius, -radius, radius, radius);
            rimGrad.addColorStop(0, "#ffd700");
            rimGrad.addColorStop(0.5, "#b8860b");
            rimGrad.addColorStop(1, "#fff3a8");
            ctx.fillStyle = rimGrad;
            ctx.fill();

            // 2. Draw 16 flashing LED lights around the rim
            const numBulbs = 16;
            for (let b = 0; b < numBulbs; b++) {
                const bAngle = (b * 2 * Math.PI) / numBulbs;
                const bx = (radius + 9) * Math.cos(bAngle);
                const by = (radius + 9) * Math.sin(bAngle);
                ctx.beginPath();
                ctx.arc(bx, by, 4.5, 0, 2 * Math.PI);
                ctx.fillStyle = (b % 2 === 0) ? "#ffffff" : "#fbbf24";
                ctx.shadowColor = (b % 2 === 0) ? "#ffffff" : "#fbbf24";
                ctx.shadowBlur = 8;
                ctx.fill();
                ctx.shadowBlur = 0;
            }

            // 3. Draw Slices
            for (let i = 0; i < numSlices; i++) {
                const seg = SEGMENTS[i];
                const startAngle = i * sliceAngle;
                const endAngle = startAngle + sliceAngle;

                ctx.beginPath();
                ctx.moveTo(0, 0);
                ctx.arc(0, 0, radius, startAngle, endAngle);
                ctx.closePath();

                // Slice gradient fill
                const sliceGrad = ctx.createRadialGradient(0, 0, 30, 0, 0, radius);
                sliceGrad.addColorStop(0, "#1e293b");
                sliceGrad.addColorStop(0.2, seg.color);
                sliceGrad.addColorStop(1, seg.color);
                ctx.fillStyle = sliceGrad;
                ctx.fill();

                // Gold separator line between slices
                ctx.lineWidth = 2.5;
                ctx.strokeStyle = "rgba(255, 255, 255, 0.25)";
                ctx.stroke();

                // Draw Text and Icon along slice radius
                ctx.save();
                ctx.rotate(startAngle + sliceAngle / 2);
                ctx.textAlign = "right";
                ctx.fillStyle = seg.textCol;
                
                // Icon
                ctx.font = "bold 26px sans-serif";
                ctx.shadowColor = "rgba(0,0,0,0.8)";
                ctx.shadowBlur = 6;
                ctx.fillText(seg.icon, radius - 20, 9);

                // Label Text
                ctx.font = "bold 20px -apple-system, sans-serif";
                ctx.fillText(seg.label, radius - 62, 7);
                ctx.shadowBlur = 0;
                ctx.restore();
            }

            ctx.restore();
        }

        // Initialize state
        if (!CAN_SPIN) {
            spinBtn.disabled = true;
            spinBtnLabel.innerText = "NEXT SPIN: __TIMER_STR__";
            document.getElementById("statusNote").innerHTML = "⏰ <b>Daily Free Spin Used!</b> Share bot with friends to get <b>+1 Instant Spin</b>!";
        }

        // Draw initial wheel frame
        drawWheel(currentAngle);

        // Core Spin Handler
        async function handleSpinClick() {
            if (isSpinning || !CAN_SPIN) return;
            getAudioContext(); // Activate user gesture audio
            isSpinning = true;
            spinBtn.disabled = true;
            spinBtnLabel.innerText = "SPINNING...";
            triggerHaptic("medium");

            try {
                // Call backend API to determine prize under server probability gate
                const resp = await fetch("/api/spin/roll", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ uid: USER_ID, tok: TOKEN })
                });

                const data = await resp.json();
                if (!data.success) {
                    alert(data.error || "Spin error. Please retry.");
                    isSpinning = false;
                    spinBtn.disabled = false;
                    spinBtnLabel.innerText = "TAP TO SPIN";
                    return;
                }

                // Animate wheel to stop exactly on winning segment!
                const targetSeg = data.target_segment; // 0 to 7
                const duration = 4600; // ms
                const startAngle = currentAngle;
                
                // Target angle formula: Needle is pinned at TOP (270 deg / -90 deg).
                // Center of segment k is (k * 45 + 22.5) degrees.
                const R_mod = ((270 - (targetSeg * 45 + 22.5) - (startAngle % 360)) % 360 + 360) % 360;
                const totalRevolutions = 360 * 6; // 6 full turns for visual excitement
                const targetAngle = startAngle + totalRevolutions + R_mod;
                
                let lastTickSeg = -1;
                const startTime = performance.now();

                function animate(now) {
                    const elapsed = now - startTime;
                    const progress = Math.min(1, elapsed / duration);
                    // Ease-Out Cubic curve: 1 - (1 - progress)^3
                    const ease = 1 - Math.pow(1 - progress, 3);
                    currentAngle = startAngle + (targetAngle - startAngle) * ease;

                    // Calculate current segment under needle for click sound
                    const needleRelative = ((270 - currentAngle) % 360 + 360) % 360;
                    const curSeg = Math.floor(needleRelative / 45);
                    if (curSeg !== lastTickSeg) {
                        lastTickSeg = curSeg;
                        playTickSound();
                        triggerHaptic("light");
                        // Needle bounce animation
                        needle.style.transform = "translateX(-50%) rotate(-12deg)";
                        setTimeout(() => { needle.style.transform = "translateX(-50%) rotate(0deg)"; }, 40);
                    }

                    drawWheel(currentAngle);

                    if (progress < 1) {
                        requestAnimationFrame(animate);
                    } else {
                        currentAngle = targetAngle;
                        drawWheel(currentAngle);
                        onSpinFinished(data);
                    }
                }

                requestAnimationFrame(animate);

            } catch (err) {
                console.error("Spin roll failed:", err);
                isSpinning = false;
                spinBtn.disabled = false;
                spinBtnLabel.innerText = "TAP TO SPIN";
            }
        }

        // Celebration and UI update on completion
        function onSpinFinished(data) {
            isSpinning = false;
            CAN_SPIN = false;
            spinBtn.disabled = true;
            spinBtnLabel.innerText = "SPIN COMPLETED";

            // Update live user balance on header
            document.getElementById("coin-val").innerText = data.new_balance;
            if (data.streak) {
                document.getElementById("streak-val").innerText = data.streak;
            }

            // Play Victory Fanfare & Haptic
            playVictoryFanfare();
            triggerHaptic("success");

            // Confetti Explosion
            if (typeof confetti === "function") {
                confetti({
                    particleCount: 120,
                    spread: 80,
                    origin: { y: 0.6 }
                });
                setTimeout(() => {
                    confetti({
                        particleCount: 60,
                        angle: 60,
                        spread: 55,
                        origin: { x: 0 }
                    });
                    confetti({
                        particleCount: 60,
                        angle: 120,
                        spread: 55,
                        origin: { x: 1 }
                    });
                }, 300);
            }

            // Display Celebration Modal
            const modal = document.getElementById("winnerModal");
            const icon = document.getElementById("modalIcon");
            const prizeTag = document.getElementById("modalPrizeTitle");
            const modalTitle = document.getElementById("modalTitle");

            if (data.prize_type === "vip_1d" || data.prize_type === "vip_3d") {
                icon.innerText = data.prize_type === "vip_3d" ? "💎" : "👑";
                modalTitle.innerText = "JACKPOT WINNER!";
                prizeTag.innerText = data.item_title;
            } else {
                icon.innerText = "🪙";
                modalTitle.innerText = "MUBARAK HO!";
                prizeTag.innerText = data.item_title;
            }

            modal.classList.add("active");
        }

        function closeRewardModal() {
            document.getElementById("winnerModal").classList.remove("active");
            if (window.Telegram && window.Telegram.WebApp) {
                window.Telegram.WebApp.close();
            }
        }
    </script>
</body>
</html>
"""


def render_spin_webapp(
    user_id: int,
    token: str,
    user_name: str,
    profile: dict,
    allowed: bool,
    cooldown_secs: int
) -> str:
    """Format and render the Lucky Wheel Mini App HTML page for a specific user session."""
    hours = cooldown_secs // 3600
    minutes = (cooldown_secs % 3600) // 60
    timer_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

    coins = profile.get("coins", 0)
    streak = profile.get("current_streak", 1)
    rank = profile.get("lifetime_rank", "🌟 Newbie")
    bot_uname = getattr(Config, "BOT_USERNAME", "") or "AkMovieVerseBot"

    html = SPIN_WEBAPP_HTML
    html = html.replace("__USER_ID__", str(user_id))
    html = html.replace("__TOKEN__", token)
    html = html.replace("__USER_NAME__", html_escape(user_name or "Player"))
    html = html.replace("__COINS__", str(coins))
    html = html.replace("__STREAK__", str(streak))
    html = html.replace("__RANK__", html_escape(rank))
    html = html.replace("__CAN_SPIN__", "true" if allowed else "false")
    html = html.replace("__TIMER_STR__", timer_str)
    html = html.replace("__BOT_USERNAME__", bot_uname)

    return html
