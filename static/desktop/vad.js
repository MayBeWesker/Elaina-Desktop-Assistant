window.myvad = null;
window.previousTriggeredProbability = 0;
window.wakeWordDetectionOn = false;
window.speechProbThreshold = 0.8;

porcupine = null;
isWaitingForWakeWord = false;
noSpeechTimeout = null;

async function init_vad() {
    window.myvad = await vad.MicVAD.new({
        preSpeechPadFrames: 10,
        positiveSpeechThreshold: window.speechProbThreshold,
        onSpeechStart: () => {
            console.log("Speech start detected: " + window.previousTriggeredProbability);
            showSubtitle("🔊 Hearing you...");
            const audioIsActive = window.isAudioPlaying ||
                (window.audioTaskQueue && window.audioTaskQueue.running);
            if (window.state === "thinking-speaking" || audioIsActive) {
                window.interrupt();
            } else {
                console.log("Not interrupted. Just normal conversation");
            }
            resetNoSpeechTimeout();
        },
        onFrameProcessed: (probs) => {
            if (probs["isSpeech"] > window.previousTriggeredProbability) {
                window.previousTriggeredProbability = probs["isSpeech"];
                resetNoSpeechTimeout();
            }
        },
        onVADMisfire: () => {
            console.log("VAD Misfire. The LLM can't hear you.");
            if (window.state === "interrupted") {
                window.setState("idle");
            }
            showSubtitle("⚠️ No speech detected - try again");
        },
        onSpeechEnd: (audio) => {
            showSubtitle("📝 Transcribing...");
            window.audioTaskQueue.clearQueue();
            if (!window.voiceInterruptionOn) {
                window.stop_mic();
            }
            if (window.ws && window.ws.readyState === WebSocket.OPEN) {
                window.sendAudioPartition(audio);
            }
            resetNoSpeechTimeout();
        }
    });
}

async function start_mic() {
    if (isWaitingForWakeWord) {
        await stop_wake_word_detection();
    }

    try {
        console.log("Mic start");
        showSubtitle("🎤 Mic starting...");

        if (window.myvad == null) {
            await init_vad();
        }
        await window.myvad.start();
        window.electronAPI.updateMenuChecked("Microphone", true);
        window.micToggleState = true;
        showSubtitle("🎤 Listening...");
        resetNoSpeechTimeout();
    } catch (error) {
        console.error("Failed to start microphone:", error);
        showSubtitle("❌ Mic error: check Windows mic permissions");
        window.micToggleState = false;
        window.electronAPI.updateMenuChecked("Microphone", false);
    }
}

window.start_mic = start_mic;

async function stop_mic() {
    console.log("Mic stop");
    
    if (window.myvad) {
        window.myvad.pause();
    }
    window.electronAPI.updateMenuChecked("Microphone", false);
    clearNoSpeechTimeout();
    window.micToggleState = false;
    if (window.wakeWordDetectionOn)
        await start_wake_word_detection();
}

window.stop_mic = stop_mic;

function interrupt() {
    console.log("Interrupting conversation chain");
    console.log("Sending: " + JSON.stringify({ type: "interrupt-signal", text: window.fullResponse }));
    if (window.ws && window.ws.readyState === WebSocket.OPEN) {
        window.ws.send(JSON.stringify({ type: "interrupt-signal", text: window.fullResponse }));
    }
    setState("interrupted");
    if (typeof window.stopCurrentAudio === "function") {
        window.stopCurrentAudio();
    }
    if (window.audioTaskQueue && typeof window.audioTaskQueue.clearQueue === 'function') {
        window.audioTaskQueue.clearQueue();
    }
    resetNoSpeechTimeout();
    console.log("Interrupted!!!!");
}

window.interrupt = interrupt;

async function start_wake_word_detection() {
    if (isWaitingForWakeWord) {
        console.log("Already waiting for wake word.");
        return;
    }

    if (window.WebVoiceProcessor.WebVoiceProcessor.isRecording) {
        await window.WebVoiceProcessor.WebVoiceProcessor.unsubscribe(porcupine);
        await porcupine.terminate();
    }

    console.log("Starting wake word detection...");
    isWaitingForWakeWord = true;
    
    accessKey = "/7gDUCElrddYzUegKQSEoe/ZQjH+sKU1KjcEnANpHdYQeLhc1WXrHQ=="
    try {
        porcupine = await PorcupineWeb.PorcupineWorker.create(
            accessKey,
            {
                label:"伊蕾娜",
                publicPath: "desktop/伊蕾娜_zh_wasm_v3_0_0.ppn"
            },
            keywordDetectionCallback,
            {
                publicPath: "desktop/porcupine_params_zh.pv",
                forceWrite: true,
            }
        );
        await window.WebVoiceProcessor.WebVoiceProcessor.subscribe(porcupine);
    } catch (err) {
        console.log("Error starting wake word detection: " + err);
    }

    console.log("Wake word detection started.");
}

async function stop_wake_word_detection() {
    if (!isWaitingForWakeWord) return;
    console.log("Stopping wake word detection...");
    if (porcupine) {
        await window.WebVoiceProcessor.WebVoiceProcessor.unsubscribe(porcupine);
        await porcupine.terminate();
        porcupine = null;
    }
    isWaitingForWakeWord = false;
    console.log("Wake word detection stopped.");
}

function keywordDetectionCallback(detection) {
    console.log(`Porcupine detected keyword: ${detection.label}`);
    if (detection.label === "伊蕾娜") {
        window.start_mic();
    }
}

function resetNoSpeechTimeout() {
    if (window.wakeWordDetectionOn === false) return;
    clearNoSpeechTimeout();
    noSpeechTimeout = setTimeout(() => {
        console.log("No speech detected for 15 seconds, stopping mic.");
        window.stop_mic();
    }, 15000);
}

window.resetNoSpeechTimeout = resetNoSpeechTimeout;

function clearNoSpeechTimeout() {
    if (noSpeechTimeout) {
        clearTimeout(noSpeechTimeout);
        noSpeechTimeout = null;
    }
}

window.addEventListener("beforeunload", async () => {
    if (window.myvad) {
        window.myvad.release();
        window.myvad = null;
    }
    if (porcupine) {
        await stop_wake_word_detection();
    }
});

window.updateSensitivity = async function(value) {
    value = Math.max(1, Math.min(100, value));
    window.speechProbThreshold = value / 100;
    
    if (window.myvad) {
        const micWasActive = window.WebVoiceProcessor.WebVoiceProcessor.isRecording;
        if (micWasActive) {
            await window.myvad.pause();
        }
        await init_vad();
        if (micWasActive) {
            await window.myvad.start();
        }
    }
    
    const sensitivityInput = document.getElementById('speechProbThreshold');
    if (sensitivityInput && sensitivityInput.value !== value.toString()) {
        sensitivityInput.value = value;
    }
    window.electronAPI.updateSensitivity(value / 100);
};

window.electronAPI.setSensitivity((event, value) => {
    const sensitivityInput = document.getElementById('speechProbThreshold');
    if (sensitivityInput) {
        sensitivityInput.value = Math.round(value * 100);
        window.updateSensitivity(sensitivityInput.value);
    }
});

var speechProbEl = document.getElementById('speechProbThreshold');
if (speechProbEl) {
    speechProbEl.addEventListener('change', function() {
        window.updateSensitivity(this.value);
    });
}

// Shared subtitle display function
function showSubtitle(text) {
    const msg = document.getElementById("message");
    if (msg) {
        msg.textContent = text;
        msg.classList.remove("hidden");
    }
}

// Expose for use from other scripts
window.showSubtitle = showSubtitle;
