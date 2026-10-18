// Auto-capture: watches the screen for a new question and answers it hands-free.
//
// Cheap loop: poll /api/screen-signature (24x14 grayscale grid from the backend,
// no browser permission prompt). When enough cells change and the frame settles,
// grab one screenshot and run it through the normal vision pipeline so the
// backend turns it into an answer.
import screenshotService from './screenshot-service.js';

const POLL_MS = 1200;
const SETTLE_MS = 1400;
const COOLDOWN_MS = 8000;
const DIFF_THRESHOLD = 0.06;
const MAX_SKIPS = 6;

class AutoCapture {
    constructor() {
        this.stateManager = null;
        this.getEnabled = () => false;
        this.onStatus = () => {};
        this.timer = null;
        this.running = false;
        this.lastSignature = null;
        this.changedAt = 0;
        this.lastCaptureTime = 0;
        this.busy = false;
        this.skipped = 0;
    }

    configure({ stateManager, getEnabled, onStatus } = {}) {
        if (stateManager) this.stateManager = stateManager;
        if (typeof getEnabled === 'function') this.getEnabled = getEnabled;
        if (typeof onStatus === 'function') this.onStatus = onStatus;
    }

    start() {
        if (this.running) return;
        this.running = true;
        this.lastSignature = null;
        this.changedAt = 0;
        console.log('🎯 Auto-capture started');
        this._schedule(POLL_MS);
    }

    stop() {
        this.running = false;
        if (this.timer) {
            clearTimeout(this.timer);
            this.timer = null;
        }
        console.log('🎯 Auto-capture stopped');
    }

    _schedule(ms) {
        if (!this.running) return;
        this.timer = setTimeout(() => this._tick(), ms);
    }

    async _tick() {
        if (!this.running) return;
        try {
            if (!this.getEnabled()) {
                this.lastSignature = null;
                this.changedAt = 0;
                return;
            }
            await this._check();
        } catch (err) {
            console.warn('🎯 Auto-capture tick failed:', err);
        } finally {
            this._schedule(POLL_MS);
        }
    }

    async _check() {
        const sig = await this._signature();
        if (!sig) return;

        if (!this.lastSignature) {
            this.lastSignature = sig;
            return;
        }

        const changed = this._diff(this.lastSignature, sig);
        this.lastSignature = sig;

        if (changed) {
            this.changedAt = Date.now();
            return;
        }

        // Screen settled after a change → maybe a new question appeared.
        if (!this.changedAt) return;
        if (Date.now() - this.changedAt < SETTLE_MS) return;
        this.changedAt = 0;

        if (Date.now() - this.lastCaptureTime < COOLDOWN_MS) return;

        await this._capture();
    }

    async _signature() {
        try {
            const resp = await fetch('/api/screen-signature');
            if (!resp.ok) return null;
            const data = await resp.json();
            return Array.isArray(data.grid) ? data.grid : null;
        } catch (err) {
            return null;
        }
    }

    _diff(a, b) {
        if (!a || !b || a.length !== b.length || !a.length) return false;
        let hits = 0;
        for (let i = 0; i < a.length; i++) {
            if (Math.abs(a[i] - b[i]) > 24) hits++;
        }
        return (hits / a.length) >= DIFF_THRESHOLD;
    }

    _visionProvider() {
        const appState = this.stateManager?.getState?.() || {};
        const primary = appState.selectedVisionProvider || {};
        const secondary = appState.selectedSecondaryVisionProvider || {};
        if (primary.name && primary.model) return primary;
        if (secondary.name && secondary.model) return secondary;
        return null;
    }

    async _capture() {
        const provider = this._visionProvider();
        if (!provider) {
            this.onStatus?.('Auto-capture needs a vision model configured');
            return;
        }
        if (this.stateManager && !this.stateManager.isLiveInterviewActive()) return;

        this.lastCaptureTime = Date.now();
        const appState = this.stateManager?.getState?.() || {};
        try {
            screenshotService.setVisionConfig(provider.name, provider.model, 1);
            screenshotService.setProgrammingLanguages(appState.selectedLanguages || []);
            const captured = await screenshotService.captureScreenshot();
            if (!captured) {
                this.onStatus?.('Auto-capture: capture failed');
                return;
            }
            await screenshotService.processQueue();
            this.onStatus?.('Auto-captured a new question');
            console.log('🎯 Auto-capture triggered a vision answer');
        } catch (err) {
            console.warn('🎯 Auto-capture capture failed:', err);
            this.onStatus?.('Auto-capture failed');
        }
    }
}

const autoCapture = new AutoCapture();
export default autoCapture;
