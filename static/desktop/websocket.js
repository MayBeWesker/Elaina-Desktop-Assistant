let micStateBeforeConfigSwitch = null;
window.state = "idle"; // idle, thinking-speaking, interrupted
window.voiceInterruptionOn = false;
window.fullResponse = ""; // full response from the server in one conversation chain

function setState(newState) {
    window.state = newState;
    console.log(`State updated to: ${window.state}`);
}
window.setState = setState;

async function sendAudioPartition(audio) {
    try {
        for (let index = 0; index < audio.length; index += chunkSize) {
            const endIndex = Math.min(index + chunkSize, audio.length);
            const chunk = audio.slice(index, endIndex);

            window.ws.send(JSON.stringify({ 
                type: "mic-audio-data", 
                audio: chunk
            }));
        }

        window.ws.send(JSON.stringify({ type: "mic-audio-end" }));
    } catch (error) {
        console.error('Error sending audio partition:', error);
    }
}
window.sendAudioPartition = sendAudioPartition;

window.ws = null;
let hasConnectedOnce = false;
let reconnectTimer = null;
let connectPromise = null;

function scheduleReconnect() {
    if (reconnectTimer) return;

    reconnectTimer = setTimeout(async () => {
        reconnectTimer = null;
        if (window.ws && (window.ws.readyState === WebSocket.OPEN ||
            window.ws.readyState === WebSocket.CONNECTING)) return;

        try {
            await connectWebSocket();
            fetchConfigurations();
        } catch (error) {
            console.error("Reconnect failed; retrying in 2 seconds:", error);
            scheduleReconnect();
        }
    }, 2000);
}

function connectWebSocket() {
    if (window.ws && window.ws.readyState === WebSocket.OPEN) {
        return Promise.resolve();
    }
    if (connectPromise) return connectPromise;

    connectPromise = new Promise((resolve, reject) => {
        showSubtitle("🔌 Connecting to server...");
        window.ws = new WebSocket("ws://127.0.0.1:1017/client-ws");

        window.ws.onopen = function () {
            connectPromise = null;
            hasConnectedOnce = true;
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
            setState("idle");
            console.log("Connected to WebSocket");
            showSubtitle("🟢 Connected — waiting for mic...");
            resolve();
        };

        window.ws.onclose = function () {
            connectPromise = null;
            setState("idle");
            console.log("Disconnected from WebSocket");
            showSubtitle("🔴 Disconnected from server");
            if (window.audioTaskQueue) {
                window.audioTaskQueue.clearQueue();
            }
            scheduleReconnect();
        };

        window.ws.onmessage = function (event) {
            handleMessage(JSON.parse(event.data));
        };

        window.ws.onerror = function (error) {
            connectPromise = null;
            console.error("WebSocket error:", error);
            showSubtitle("❌ Cannot connect to server (port 1017)");
            reject(error);
        };
    });
    return connectPromise;
}

function handleMessage(message) {
    console.log("Received Message: ", message);
    switch (message.type) {
        case "full-text":
            if (message.text === "Thinking...") {
                showSubtitle("🤔 Thinking...");
            } else {
                showSubtitle(message.text);
            }
            console.log("full-text: ", message.text);
            break;
        case "control":
            switch (message.text) {
                case "start-mic":
                    window.start_mic();
                    break;
                case "stop-mic":
                    window.stop_mic();
                    showSubtitle("Mic stopped");
                    break;
                case "conversation-chain-start":
                    if (typeof window.stopCurrentAudio === "function") {
                        window.stopCurrentAudio();
                    }
                    if (window.audioTaskQueue) {
                        window.audioTaskQueue.clearQueue();
                    }
                    setState("thinking-speaking");
                    window.fullResponse = "";
                    window.audioTaskQueue = new TaskQueue(20);
                    showSubtitle("🤔 Thinking...");
                    break;
                case "conversation-chain-end":
                    if (window.state === "interrupted") {
                        console.log("Ignoring end of interrupted conversation chain");
                        break;
                    }
                    setState("idle");
                    setExpression(0);
                    showSubtitle("🎤 Listening...");
                    if (!window.voiceInterruptionOn) {
                        window.start_mic();
                    }
                    break;
            }
            break;
        case "expression":
            setExpression(message.text);
            break;
        case "character-mode":
            window.live2dModule.setCharacterMode(message).then(() => {
                showSubtitle(`已切换到${message.name}模式`);
            }).catch((error) => {
                console.error("Failed to switch character mode:", error);
                showSubtitle("形象切换失败，请查看后端日志");
            });
            break;
        case "mouth":
            setMouth(Number(message.text));
            break;
        case "audio":
            if (window.state == "interrupted") {
                console.log("Audio playback intercepted. Sentence:", message.text);
            } else {
                if (message.text) {
                    showSubtitle("🔊 " + message.text);
                }
                window.addAudioTask(message.audio, message.instrument, message.volumes, message.slice_length, message.text, message.expressions, message.audio_mime, message.instrument_mime);
                window.setExpression(0);
            }
            break;
        case "set-model":
            if (!app) {
                window.pendingModelInfo = message.text;
                break;
            }
            if (window.modelInfo?.name === message.text?.name) {
                break;
            }
            window.live2dModule.loadModel(message.text).then(() => {
                window.modelInfo = message.text;
            }).catch((error) => {
                console.error("Failed to load model from server:", error);
            });
            break;
        case "listExpressions":
            console.log(listSupportedExpressions());
            break;
        case "config-files":
            console.log("Received config files");
            window.electronAPI.sendConfigFiles(message.files);
            break;
        case "config-switched":
            console.log(message.message);
            document.getElementById("message").textContent = "Configuration switched successfully!";
            setState("idle");

            if (micStateBeforeConfigSwitch) {
                start_mic();
            }
            micStateBeforeConfigSwitch = null;  // reset the state
            break;
        case "error":
            console.error(message.message);
            showSubtitle(`❌ ${message.message}`);
            break;
        default:
            console.error("Unknown message type: " + message.type);
            console.log(message);
    }
}

function fetchConfigurations() {
    if (window.ws && window.ws.readyState === WebSocket.OPEN) {
        window.ws.send(JSON.stringify({ type: "fetch-configs" }));
        console.log("Fetching configurations");
    } else {
        console.error("WebSocket is not open. Cannot fetch configurations.");
    }
}

function switchConfig(configFile) {
    setState("switching-config");
    document.getElementById("message").textContent = "Switching configuration...";
    
    micStateBeforeConfigSwitch = micToggleState;
    if (micToggleState) {
        stop_mic();
    }
    window.interrupt();
    window.ws.send(JSON.stringify({ type: "switch-config", file: configFile }));
}

window.handleMessage = handleMessage;
window.switchConfig = switchConfig;
window.fetchConfigurations = fetchConfigurations;

async function initialize() {
    let retries = 0;
    const maxRetries = 20;
    const retryDelay = 2000; // 2 seconds between retries

    while (retries < maxRetries) {
        try {
            await connectWebSocket();
            fetchConfigurations();
            return; // Success, stop retrying
        } catch (error) {
            retries++;
            console.error(`Failed to initialize (attempt ${retries}/${maxRetries}):`, error);
            showSubtitle(`🔌 Retrying connection (${retries}/${maxRetries})...`);
            await new Promise(r => setTimeout(r, retryDelay));
        }
    }
    showSubtitle("🔌 Server not ready — continuing to reconnect...");
    scheduleReconnect();
}

initialize();

window.connectWebSocket = connectWebSocket;
