// --- audio_handler.js ---
// This module handles all interactions with the Web Media APIs
// for capturing and processing audio via an AudioWorklet.

import { devLog, devError } from './config.js';
import muteManager from './mute-manager.js';

// Must match sample_rate in the Deepgram LiveOptions in services/stt_service.py.
const TARGET_SAMPLE_RATE = 48000;

let audioContext = null;
let micStream = null;
let systemStream = null;
let micGainNode = null;

// When the backend can read the mic and WASAPI loopback itself, the browser
// is never asked for media access: no getUserMedia prompt, no getDisplayMedia
// picker, no "sharing your screen" badge.
let nativeMode = false;
let nativeDevices = [];

export function isNativeAudioMode() {
    return nativeMode;
}

/**
 * Probes the backend for prompt-free native capture and, when available,
 * fills the mic dropdown from the backend device list instead of calling
 * getUserMedia (which is what triggers the permission prompt).
 * @returns {Promise<boolean>} True if audio setup can proceed without prompts.
 */
export async function setupMicrophone() {
    const micSelect = document.getElementById('mic-select');
    try {
        const probe = await fetch('/api/native-audio').then(r => r.json());
        if (probe && probe.available) {
            const list = await fetch('/api/native-audio/devices').then(r => r.json());
            if (list && Array.isArray(list.devices) && list.devices.length > 0) {
                nativeMode = true;
                nativeDevices = list.devices;
                micSelect.innerHTML = '';
                list.devices.forEach(device => {
                    const option = document.createElement('option');
                    option.value = String(device.index);
                    option.textContent = device.name;
                    if (device.index === list.defaultIndex) option.selected = true;
                    micSelect.appendChild(option);
                });
                micSelect.disabled = false;
                devLog('🎙️ Native audio mode: microphone list supplied by backend (no prompt).');
                return true;
            }
        }
    } catch (err) {
        devLog('Native audio probe failed, falling back to browser capture:', err);
    }

    nativeMode = false;
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        stream.getTracks().forEach(track => track.stop());

        const devices = await navigator.mediaDevices.enumerateDevices();
        const audioDevices = devices.filter(device => device.kind === 'audioinput');

        if (audioDevices.length === 0) return false;

        micSelect.innerHTML = '';
        audioDevices.forEach(device => {
            const option = document.createElement('option');
            option.value = device.deviceId;
            option.textContent = device.label || `Microphone ${micSelect.options.length + 1}`;
            micSelect.appendChild(option);
        });
        
        micSelect.disabled = false;
        return true;
    } catch (err) {
        devError("Error setting up microphone:", err);
        return false;
    }
}

/**
 * Starts audio processing by setting up the AudioContext, loading the worklet,
 * and connecting the audio streams.
 * @param {string} micId - The deviceId of the selected microphone.
 * @param {function} onAudioData - Callback function to handle the processed PCM audio data.
 * @returns {Promise<boolean>} True if processing started successfully.
 */
/**
 * Forces the browser capture path (used when the backend reports native
 * capture is unavailable after the frontend already skipped media setup).
 */
export function enableBrowserFallback() {
    if (!nativeMode) return;
    nativeMode = false;
    devLog('🔁 Switching to browser audio capture (native unavailable).');
}

/**
 * Starts audio processing by setting up the AudioContext, loading the worklet,
 * and connecting the audio streams.
 * @param {string} micId - The deviceId of the selected microphone.
 * @param {function} onAudioData - Callback function to handle the processed PCM audio data.
 * @returns {Promise<boolean>} True if processing started successfully.
 */
export async function startAudioProcessing(micId, onAudioData) {
    if (nativeMode) {
        // Backend owns the mic + loopback capture; nothing is requested from
        // the browser, so there is no permission prompt and no share badge.
        devLog("🎧 Native audio active - browser capture skipped (zero prompts).");
        return true;
    }
    if (micStream && systemStream && audioContext && audioContext.state === 'running') {
        devLog("🎧 Browser audio already running - reusing existing streams.");
        return true;
    }
    try {
        // 1. Get Audio Streams
        micStream = await navigator.mediaDevices.getUserMedia({ audio: { deviceId: { exact: micId } } });
        systemStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });

        if (!micStream || !systemStream) {
            console.error("Could not get both audio streams.");
            stopAudioProcessing();
            return false;
        }

        // 2. Setup AudioContext and Worklet
        // Pin the rate so it matches what Deepgram is told to expect. Left to
        // itself the context adopts the hardware rate, and a 44.1kHz device
        // then streams audio that Deepgram decodes as 48kHz (~9% fast), which
        // degrades transcription in a way that looks like a Deepgram fault
        // rather than a configuration mismatch.
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        try {
            audioContext = new AudioCtx({ sampleRate: TARGET_SAMPLE_RATE });
        } catch (rateErr) {
            // The spec requires 8000-96000 to be supported, so this is close to
            // unreachable; fall back rather than failing the whole session.
            console.warn('⚠️ Could not pin AudioContext sample rate:', rateErr);
            audioContext = new AudioCtx();
        }
        console.log(`🎵 AudioContext: ${audioContext.sampleRate}Hz`); // Keep this as it's important for debugging
        if (audioContext.sampleRate !== TARGET_SAMPLE_RATE) {
            console.warn(`⚠️ AudioContext is ${audioContext.sampleRate}Hz but Deepgram expects ${TARGET_SAMPLE_RATE}Hz - transcription accuracy may suffer`);
        }
        await audioContext.audioWorklet.addModule('/static/js/audio_processor.js');
        
        // 3. Create a single mixed processor for better diarization
        const mixedProcessor = new AudioWorkletNode(audioContext, 'mixed-processor');

        // Handle mixed audio with mute-aware speaker detection
        let audioProcessingCounter = 0; // For throttled logging
        
        mixedProcessor.port.onmessage = (event) => {
            // If universally muted, drop all audio data immediately.
            if (muteManager.isAudioPaused()) {
                if (audioProcessingCounter % 200 === 0) { // Log occasionally to show it's paused
                    devLog(`⏸️ Audio processing paused due to universal mute.`);
                }
                audioProcessingCounter++;
                return;
            }

            const { audioData, micLevel, systemLevel } = event.data;
            let speakerHint;

            if (muteManager.isMicrophoneMuted()) {
                // When microphone is muted, all audio is from the interviewer.
                speakerHint = 'system';
                // Logging removed to reduce console noise.
            } else {
                // When unmuted, distinguish based on volume.
                speakerHint = systemLevel > micLevel * 2 ? 'system' : 'microphone';
            }

            audioProcessingCounter++;
            onAudioData(audioData, speakerHint);
        };

        // 4. Connect both sources to the mixed processor with mute control
        const micSource = audioContext.createMediaStreamSource(micStream);
        const systemSource = audioContext.createMediaStreamSource(systemStream);
        
        // Stop the video track(s) so the browser's "sharing your screen" indicator
        // is dismissed; the audio track keeps capturing system audio.
        try {
            systemStream.getVideoTracks().forEach(t => { try { t.stop(); } catch (e) {} });
        } catch (e) {}
        
        // Create gain node for microphone muting
        micGainNode = audioContext.createGain();
        updateMicGainNode(); // Set initial gain based on mute manager state
        
        // Listen for future changes
        muteManager.on('microphoneMuteChange', updateMicGainNode);
        
        // Connect mic through gain node for mute control
        micSource.connect(micGainNode);
        micGainNode.connect(mixedProcessor);
        
        // System audio connects directly (we don't want to mute interviewer)
        systemSource.connect(mixedProcessor);

        devLog("✅ Audio processing started successfully");
        return true;

    } catch (err) {
        console.error("❌ Error starting audio processing:", err);
        stopAudioProcessing();
        return false;
    }
}

/**
 * Updates the microphone gain node based on the central mute manager state.
 */
function updateMicGainNode() {
    if (!micGainNode || !audioContext) return;
    
    const isMuted = muteManager.isMicrophoneMuted();
    const targetGain = isMuted ? 0 : 1;
    
    // Smooth transition to avoid audio pops
    micGainNode.gain.setTargetAtTime(targetGain, audioContext.currentTime, 0.05);
    devLog(`🎤 Microphone gain set to ${targetGain} based on mute manager.`);
}

// --- Legacy Functions (now wrappers for MuteManager) ---
// These are kept for backward compatibility with other modules that might call them.

/**
 * @deprecated Use muteManager.setMicrophoneMute(mute) instead.
 */
export function setMicrophoneMute(mute) {
    muteManager.setMicrophoneMute(mute);
    return muteManager.isMicrophoneMuted();
}

/**
 * @deprecated Use muteManager.isMicrophoneMuted() instead.
 */
export function isMicrophoneMuted() {
    return muteManager.isMicrophoneMuted();
}

/**
 * @deprecated Use muteManager.toggleMicrophoneMute() instead.
 */
export function toggleMicrophoneMute() {
    return muteManager.toggleMicrophoneMute();
}

/**
 * @deprecated Use muteManager.getMuteStatus() instead.
 */
export function getAudioProcessingMode() {
    return muteManager.getMuteStatus();
}

/**
 * Stops all audio streams and closes the AudioContext.
 */
export function stopAudioProcessing() {
    console.log("Stopping audio processing.");
    if (micStream) {
        micStream.getTracks().forEach(track => track.stop());
        micStream = null;
    }
    if (systemStream) {
        systemStream.getTracks().forEach(track => track.stop());
        systemStream = null;
    }
    if (audioContext && audioContext.state !== 'closed') {
        audioContext.close();
        audioContext = null;
    }
    
    // Reset mute state in the central manager
    muteManager.setMicrophoneMute(true);
    muteManager.setUniversalMute(false);
    micGainNode = null;
}