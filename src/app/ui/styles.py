"""
CSS-стили для Gradio интерфейса Multi-Agent Interview Coach.

Содержит константы с CSS-стилями для профессионального оформления
интерфейса приложения.
"""

from __future__ import annotations

from typing import Final

MAIN_CSS: Final[str] = """
/* ===================================================================
   Multi-Agent Interview Coach — Main Stylesheet (v2 clean)
   =================================================================== */

/* --- Root Variables ------------------------------------------------ */
:root {
    --accent-primary: #6366f1;
    --accent-primary-hover: #4f46e5;
    --accent-secondary: #8b5cf6;
    --accent-success: #10b981;
    --accent-warning: #f59e0b;
    --accent-danger: #ef4444;
    --surface-0: #0f1117;
    --surface-1: #1a1b26;
    --surface-2: #24253a;
    --surface-3: #2e3048;
    --text-primary: #e2e8f0;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --border-subtle: rgba(99, 102, 241, 0.15);
    --border-accent: rgba(99, 102, 241, 0.4);
    --shadow-glow: 0 0 20px rgba(99, 102, 241, 0.1);
    --radius-sm: 10px;
    --radius-md: 14px;
    --radius-lg: 18px;
    --radius-xl: 22px;
    --transition-fast: 0.15s ease;
    --transition-normal: 0.25s ease;
}

/* === GLOBAL LAYOUT ================================================ */

.gradio-container {
    max-width: 100% !important;
    width: 100% !important;
    padding: 16px 28px !important;
    margin: 0 auto !important;
    background: var(--surface-0) !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI',
                 Roboto, Oxygen, Ubuntu, sans-serif !important;
}

/* Make the main row stretch fully */
.gradio-container > .main > .wrap > .contain,
.gradio-container > div {
    max-width: 100% !important;
}

/* === GLOBAL BORDER-RADIUS ========================================= */
/* Apply rounded corners to all Gradio block-level elements */

.gradio-container .block,
.gradio-container .gr-group,
.gradio-container .gr-block,
.gradio-container .gr-box,
.gradio-container .gr-panel,
.gradio-container .form,
.gradio-container .wrap,
.gradio-container .contain,
.gradio-container textarea,
.gradio-container input[type="text"],
.gradio-container select,
.gradio-container .file-preview {
    border-radius: var(--radius-sm) !important;
}

/* === BACKGROUND COLOR HARMONY ===================================== */
/* Only override specific elements that get wrong backgrounds.
   Do NOT blanket-override *, .block, .wrap etc. — that breaks layout. */

/* The main body background is set via theme. These handle edge cases. */
.gradio-container > .main,
.gradio-container > .main > .wrap {
    background: var(--surface-0) !important;
}

/* Tab content panels — these often get an unwanted lighter bg */
.gradio-tabitem,
.gradio-tabitem > .gap,
.gradio-tabitem > div,
.tab-content {
    background: transparent !important;
}

/* Gradio group wrappers inside our styled panels — keep transparent */
.settings-panel .gr-group,
.settings-panel .form,
.settings-panel .block:not(.gradio-accordion),
.feedback-panel .gr-group,
.feedback-panel .form,
.feedback-panel .block:not(.gradio-accordion) {
    background: transparent !important;
}

/* Accordion inner body (the expanded content area) */
.gradio-accordion > div:not(.label-wrap) {
    background: transparent !important;
}

/* Row/Column containers should never have visible bg */
.gradio-row,
.gradio-column {
    background: transparent !important;
}

/* === HEADER ======================================================= */

.app-header {
    text-align: center;
    padding: 28px 24px 22px;
    margin-bottom: 12px;
    background: linear-gradient(135deg, var(--surface-1) 0%, var(--surface-2) 100%);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-glow);
    position: relative;
    overflow: hidden;
}

.app-header::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg,
        var(--accent-primary) 0%,
        var(--accent-secondary) 50%,
        var(--accent-primary) 100%);
}

.app-header h1 {
    font-size: 1.75rem !important;
    font-weight: 700 !important;
    background: linear-gradient(135deg, #c7d2fe, #a5b4fc, #818cf8);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0 0 6px !important;
    letter-spacing: -0.02em;
}

.app-header p {
    color: var(--text-secondary) !important;
    font-size: 0.92rem !important;
    margin: 0 !important;
    line-height: 1.5;
}

/* Agent role badges */
.agent-badges {
    display: flex;
    justify-content: center;
    gap: 12px;
    margin-top: 14px;
    flex-wrap: wrap;
}

.agent-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 14px;
    border-radius: 20px;
    font-size: 0.78rem;
    font-weight: 500;
    letter-spacing: 0.01em;
}

.badge-observer {
    background: rgba(16, 185, 129, 0.12) !important;
    color: #6ee7b7;
    border: 1px solid rgba(16, 185, 129, 0.25);
}

.badge-interviewer {
    background: rgba(99, 102, 241, 0.12) !important;
    color: #a5b4fc;
    border: 1px solid rgba(99, 102, 241, 0.25);
}

.badge-evaluator {
    background: rgba(245, 158, 11, 0.12) !important;
    color: #fcd34d;
    border: 1px solid rgba(245, 158, 11, 0.25);
}

/* === SETTINGS PANEL (Left Sidebar) ================================ */

.settings-panel {
    background: var(--surface-1) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: var(--radius-lg) !important;
    padding: 18px !important;
}

.panel-title {
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    color: var(--text-primary) !important;
    margin-bottom: 12px !important;
    display: flex;
    align-items: center;
    gap: 8px;
}

/* === ACCORDION ==================================================== */

.gradio-accordion {
    border: 1px solid var(--border-subtle) !important;
    border-radius: var(--radius-md) !important;
    margin-bottom: 6px !important;
    background: var(--surface-2) !important;
    overflow: hidden;
}

.gradio-accordion > .label-wrap {
    padding: 10px 14px !important;
    background: transparent !important;
    border-radius: var(--radius-md) !important;
}

.gradio-accordion > .label-wrap > span {
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    color: var(--text-primary) !important;
}

/* === BUTTONS ====================================================== */

.btn-start {
    background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary)) !important;
    border: none !important;
    color: white !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    border-radius: var(--radius-sm) !important;
    padding: 10px 20px !important;
    transition: all var(--transition-fast) !important;
    box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3) !important;
    min-height: 42px !important;
}

.btn-start:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 16px rgba(99, 102, 241, 0.45) !important;
}

.btn-stop {
    background: linear-gradient(135deg, var(--accent-danger), #dc2626) !important;
    border: none !important;
    color: white !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    border-radius: var(--radius-sm) !important;
    padding: 10px 20px !important;
    transition: all var(--transition-fast) !important;
    box-shadow: 0 2px 8px rgba(239, 68, 68, 0.25) !important;
    min-height: 42px !important;
}

.btn-stop:hover {
    box-shadow: 0 4px 16px rgba(239, 68, 68, 0.4) !important;
}

.btn-reset {
    background: var(--surface-3) !important;
    border: 1px solid var(--border-subtle) !important;
    color: var(--text-secondary) !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    border-radius: var(--radius-sm) !important;
    padding: 10px 20px !important;
    transition: all var(--transition-fast) !important;
    min-height: 42px !important;
}

.btn-reset:hover {
    background: var(--surface-2) !important;
    border-color: var(--border-accent) !important;
    color: var(--text-primary) !important;
}

.btn-refresh {
    background: var(--surface-3) !important;
    border: 1px solid var(--border-subtle) !important;
    color: var(--text-secondary) !important;
    border-radius: var(--radius-sm) !important;
    transition: all var(--transition-fast) !important;
}

.btn-refresh:hover {
    background: var(--surface-2) !important;
    border-color: var(--border-accent) !important;
    color: var(--text-primary) !important;
}

.btn-send {
    background: var(--accent-primary) !important;
    border: none !important;
    color: white !important;
    font-weight: 600 !important;
    border-radius: var(--radius-sm) !important;
    min-height: 50px !important;
    transition: all var(--transition-fast) !important;
}

.btn-send:hover {
    background: var(--accent-primary-hover) !important;
}

/* === STATUS BAR =================================================== */

.status-bar {
    min-height: 36px !important;
}

.status-bar textarea,
.status-bar input {
    background: var(--surface-2) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--accent-success) !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    padding: 6px 12px !important;
    text-align: center;
}

/* === TABS ========================================================= */

.gradio-tabs {
    background: transparent !important;
    border-radius: var(--radius-lg) !important;
    overflow: visible !important;
}

.gradio-tabs > .tab-nav {
    background: var(--surface-1) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: var(--radius-md) !important;
    padding: 4px !important;
    gap: 6px !important;
    display: flex !important;
    margin-bottom: 12px !important;
}

.gradio-tabs > .tab-nav > button {
    color: var(--text-secondary) !important;
    font-size: 0.88rem !important;
    font-weight: 500 !important;
    border: none !important;
    border-radius: var(--radius-sm) !important;
    padding: 10px 22px !important;
    transition: all var(--transition-fast) !important;
    background: transparent !important;
    margin: 0 !important;
    flex: 1 !important;
}

.gradio-tabs > .tab-nav > button:hover {
    background: var(--surface-2) !important;
    color: var(--text-primary) !important;
}

.gradio-tabs > .tab-nav > button.selected {
    color: white !important;
    background: var(--accent-primary) !important;
    border: none !important;
    box-shadow: 0 2px 8px rgba(99, 102, 241, 0.25) !important;
}

/* === CHAT AREA ==================================================== */

.chat-area {
    border: 1px solid var(--border-subtle) !important;
    border-radius: var(--radius-lg) !important;
    overflow: hidden;
    background: var(--surface-1) !important;
}

/* Chatbot inner wrapper */
.chat-area .chatbot,
.chat-area .wrapper,
.chat-area .wrap {
    background: var(--surface-1) !important;
}

.chat-area .message {
    border-radius: var(--radius-sm) !important;
    padding: 10px 14px !important;
    font-size: 0.9rem !important;
    line-height: 1.55 !important;
}

/* Chatbot placeholder — make it blend with surface-1 */
.chat-area .placeholder,
.chat-area .empty,
.chatbot .placeholder,
.chatbot .empty {
    background: transparent !important;
    background-color: transparent !important;
}

.chat-area .placeholder *,
.chatbot .placeholder * {
    background: transparent !important;
    background-color: transparent !important;
}

/* The data-testid wrapper */
[data-testid="chatbot"],
[data-testid="chatbot"] > div {
    background: var(--surface-1) !important;
    border-radius: var(--radius-lg) !important;
}

/* === INPUT AREA =================================================== */

.input-area textarea {
    background: var(--surface-2) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text-primary) !important;
    font-size: 0.9rem !important;
    transition: border-color var(--transition-fast) !important;
    padding: 10px 14px !important;
}

.input-area textarea:focus {
    border-color: var(--accent-primary) !important;
    box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15) !important;
}

/* === FEEDBACK PANEL =============================================== */

.feedback-panel {
    background: var(--surface-1) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: var(--radius-lg) !important;
    padding: 18px !important;
}

.feedback-panel textarea {
    background: var(--surface-2) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text-primary) !important;
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace !important;
    font-size: 0.82rem !important;
    line-height: 1.6 !important;
    padding: 14px !important;
    max-height: 560px !important;
    overflow-y: auto !important;
}

/* === LABEL STYLING ================================================ */

.gradio-slider .label-wrap > span,
.gradio-number .label-wrap > span,
.gradio-dropdown .label-wrap > span,
.gradio-textbox .label-wrap > span {
    font-size: 0.82rem !important;
    color: var(--text-secondary) !important;
}

/* === MODEL SELECTOR DROPDOWN ====================================== */

.model-selector .wrap {
    background: var(--surface-2) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: var(--radius-sm) !important;
}

.model-selector .wrap:hover {
    border-color: var(--border-accent) !important;
}

/* === JOB DESCRIPTION ============================================== */

.job-desc-input textarea {
    background: var(--surface-2) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text-primary) !important;
    font-size: 0.85rem !important;
    min-height: 100px !important;
}

.job-desc-input textarea:focus {
    border-color: var(--accent-primary) !important;
    box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15) !important;
}

/* === AGENT CONFIG SECTIONS ======================================== */

.agent-config-section {
    padding: 8px 4px !important;
    background: transparent !important;
    border: none !important;
}

.agent-config-section .label-wrap > span {
    font-size: 0.8rem !important;
}

/* === FILE DOWNLOAD ================================================ */

.download-section {
    margin-top: 8px;
}

.download-section .file-preview {
    background: var(--surface-2) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: var(--radius-sm) !important;
}

/* === SCROLLBAR ===================================================== */

::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}

::-webkit-scrollbar-track {
    background: var(--surface-1);
    border-radius: 3px;
}

::-webkit-scrollbar-thumb {
    background: var(--surface-3);
    border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--text-muted);
}

/* === MISC ========================================================= */

.section-divider {
    border: none;
    border-top: 1px solid var(--border-subtle);
    margin: 12px 0;
}

.hint-text {
    font-size: 0.78rem !important;
    color: var(--text-muted) !important;
    margin-top: 4px;
    line-height: 1.4;
}

.gr-padded {
    padding: 12px !important;
}

/* === RESPONSIVE =================================================== */

@media (max-width: 768px) {
    .gradio-container {
        padding: 8px 10px !important;
    }

    .agent-badges {
        flex-direction: column;
        align-items: center;
        gap: 6px;
    }

    .app-header h1 {
        font-size: 1.35rem !important;
    }

    .gradio-tabs > .tab-nav > button {
        padding: 8px 12px !important;
        font-size: 0.82rem !important;
    }
}

/* === HIDE GRADIO FOOTER =========================================== */

footer {
    display: none !important;
}

/* === GLOBAL BORDER-RADIUS for Gradio 5.x generated wrappers ======= */
/* Gradio generates dynamic class names; target by structure */

/* All direct block children of columns get rounded corners */
.gradio-column > div {
    border-radius: var(--radius-md) !important;
}

/* Slider range inputs — accent color */
.gradio-slider input[type="range"] {
    accent-color: var(--accent-primary) !important;
}

/* Block labels (floating above inputs) — transparent bg */
.gradio-container label.float,
.gradio-container .label-wrap {
    background: transparent !important;
}
"""

HEADER_HTML: Final[str] = """
<div class="app-header">
    <h1>Multi-Agent Interview Coach</h1>
    <p>Интеллектуальная система подготовки к техническим интервью с AI-агентами</p>
    <div class="agent-badges">
        <span class="agent-badge badge-observer">👁️ Observer — анализ и факт-чекинг</span>
        <span class="agent-badge badge-interviewer">🎤 Interviewer — адаптивный диалог</span>
        <span class="agent-badge badge-evaluator">📊 Evaluator — финальная оценка</span>
    </div>
</div>
"""