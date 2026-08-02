const chunkSize = 4096;
window.isAudioPlaying = false;
window.currentInstrumentAudio = null;
window.currentExpressionTimers = [];

function stopCurrentAudio() {
    window.currentExpressionTimers.forEach(clearTimeout);
    window.currentExpressionTimers = [];
    if (window.currentInstrumentAudio) {
        window.currentInstrumentAudio.pause();
        window.currentInstrumentAudio.removeAttribute("src");
        window.currentInstrumentAudio = null;
    }
    if (window.model2 && typeof window.model2.stopSpeaking === "function") {
        window.model2.stopSpeaking();
    }
    window.isAudioPlaying = false;
}
window.stopCurrentAudio = stopCurrentAudio;

async function addAudioTask(audio_base64, instrument_base64, volumes, slice_length, text = null, expression_list = null, audio_mime = "audio/wav", instrument_mime = "audio/wav") {
    console.log(`1. Adding audio task ${text} to queue`);
    
    if (window.state === "interrupted") {
        console.log("Skipping audio task due to interrupted state");
        return;
    }
    
    window.audioTaskQueue.addTask(() => {
        return new Promise((resolve, reject) => {
            playAudioLipSync(audio_base64, instrument_base64, volumes, slice_length, text, expression_list, resolve, audio_mime, instrument_mime);
        }).catch(error => {
            console.log("Audio task error:", error);
        });
    });
}
window.addAudioTask = addAudioTask;

async function getAudioLength(audio_base64, audio_mime = "audio/wav") {
    return new Promise((resolve) => {
        const audio = new Audio(`data:${audio_mime};base64,` + audio_base64);
        audio.onloadedmetadata = () => {
            const audioDur = audio.duration * 1000;
            resolve(audioDur);
        };
    });
}

function playAudioLipSync(audio_base64, instrument_base64, volumes, slice_length, text = null, expression_list = null, onComplete, audio_mime = "audio/wav", instrument_mime = "audio/wav") {
    if (window.state === "interrupted") {
        console.error("Audio playback blocked. State:", window.state);
        onComplete();
        return;
    }

    window.fullResponse += text;
    if (text) {
        document.getElementById("message").textContent = text;
    }

    if (instrument_base64 && instrument_base64 !== "None") {
        const instrumentAudio = new Audio(`data:${instrument_mime};base64,` + instrument_base64);
        window.currentInstrumentAudio = instrumentAudio;
        instrumentAudio.play().catch((error) => console.error("Instrument playback error:", error));
        instrumentAudio.onended = () => {
            if (window.currentInstrumentAudio === instrumentAudio) {
                window.currentInstrumentAudio = null;
            }
        };
    }

    const displayExpression = expression_list ? expression_list[0] : null;
    const expressionTimers = [];
    window.currentExpressionTimers = expressionTimers;
    if (Array.isArray(expression_list) && expression_list.length > 1) {
        getAudioLength(audio_base64, audio_mime).then((duration) => {
            expression_list.slice(1).forEach((expression, index) => {
                const delay = duration * (index + 1) / expression_list.length;
                expressionTimers.push(setTimeout(() => {
                    window.setExpression(expression);
                }, delay));
            });
        });
    }
    console.log("Start playing audio: ", text);
    
    try {
        window.model2.speak(`data:${audio_mime};base64,` + audio_base64, {
            expression: displayExpression,
            resetExpression: true,
            onFinish: () => {
                expressionTimers.forEach(clearTimeout);
                if (window.currentExpressionTimers === expressionTimers) {
                    window.currentExpressionTimers = [];
                }
                window.isAudioPlaying = false;
                console.log("Voiceline is over");
                onComplete();
            },
            onError: (error) => {
                expressionTimers.forEach(clearTimeout);
                if (window.currentExpressionTimers === expressionTimers) {
                    window.currentExpressionTimers = [];
                }
                window.isAudioPlaying = false;
                console.error("Audio playback error:", error);
                onComplete();
            }
        });
    } catch (error) {
        console.error("Speak function error:", error);
        onComplete();
    }
}
window.playAudioLipSync = playAudioLipSync;
