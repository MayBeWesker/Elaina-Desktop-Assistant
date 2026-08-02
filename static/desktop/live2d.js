var app, model2;
var modelInfo, emoMap;
var spriteMode = false;
var idleFloatBaseY = 0;
var faceCameraTicker = null;
var spriteExpressionFiles = {};
var currentSpriteExpression = null;
var defaultSpriteExpressionFiles = {};

window.live2dModule = (function () {
    const live2d = PIXI.live2d || null;  // null in sprite mode

    async function init() {
        var canvas = document.getElementById("canvas");
        try {
            app = new PIXI.Application({
                view: canvas,
                autoStart: true,
                resizeTo: window,
                backgroundAlpha: 0,
            });
            console.log("PIXI Application initialized with WebGL");
        } catch (e) {
            console.warn("Default init failed, trying WebGL1:", e.message);
            try {
                app = new PIXI.Application({
                    view: canvas,
                    autoStart: true,
                    resizeTo: window,
                    backgroundAlpha: 0,
                    antialias: false,
                    resolution: 1,
                    preferWebGLVersion: 1,
                });
                console.log("PIXI Application initialized with WebGL1 fallback");
            } catch (e2) {
                console.error("PIXI init failed:", e2.message);
                var loading = document.getElementById("loading");
                if (loading) loading.textContent = "Error: Renderer init failed - " + e2.message;
                throw e2;
            }
        }
    }

    async function loadModel(info = {}) {
        modelInfo = info;
        emoMap = info["emotionMap"] || {};

        // Remove old model
        if (model2) {
            if (faceCameraTicker) {
                app.ticker.remove(faceCameraTicker);
                faceCameraTicker = null;
            }
            app.stage.removeChild(model2);
            model2.destroy({ children: true, texture: true, baseTexture: true });
            model2 = null;
        }

        // SPRITE MODE: use PNG image instead of Live2D
        if (info.type === "sprite" && info.url) {
            spriteMode = true;
            spriteExpressionFiles = info.expressionFiles || {};
            defaultSpriteExpressionFiles = Object.assign({}, spriteExpressionFiles);
            currentSpriteExpression = null;

            // Load texture using compatible API
            var texture;
            try {
                if (PIXI.Assets && typeof PIXI.Assets.load === 'function') {
                    texture = await PIXI.Assets.load(info.url);
                } else if (typeof PIXI.Texture.fromURL === 'function') {
                    texture = await PIXI.Texture.fromURL(info.url);
                } else {
                    // Fallback: manual Image loading
                    texture = await new Promise(function(resolve, reject) {
                        var img = new Image();
                        img.onload = function() {
                            resolve(PIXI.Texture.from(img));
                        };
                        img.onerror = function() { reject(new Error("Image load failed")); };
                        img.src = info.url;
                    });
                }
                if (!texture) throw new Error("Texture is null");
                model2 = new PIXI.Sprite(texture);
            } catch (e) {
                console.error("Failed to load sprite texture:", e);
                var loadingEl = document.getElementById("loading");
                if (loadingEl) loadingEl.textContent = "Error loading character: " + e.message;
                return;
            }

            // Position at bottom center of the window
            const maxWidth = app.view.width * 0.9;
            const maxHeight = app.view.height * (info.heightRatio || 0.92);
            const scale = Math.min(maxWidth / texture.width, maxHeight / texture.height);
            model2.scale.set(scale);
            model2.anchor.set(0.5, 1.0);  // anchor at bottom center

            model2.x = app.view.width / 2 + (info.initialXshift || 0);
            model2.y = app.view.height + (info.initialYshift || 0);
            idleFloatBaseY = model2.y;

            // Add speak method for compatibility with audio.js
            model2.speak = function(audioSrc, options) {
                model2.stopSpeaking();
                if (options && options.expression != null) {
                    window.setExpression(options.expression);
                }
                const audio = new Audio(audioSrc);
                let completed = false;
                const complete = function(isError, error) {
                    if (completed) return;
                    completed = true;
                    model2.currentAudio = null;
                    window.isAudioPlaying = false;
                    if (options && options.resetExpression) window.setExpression(0);
                    if (isError && options && options.onError) options.onError(error);
                    else if (options && options.onFinish) options.onFinish();
                };
                model2.currentAudio = audio;
                window.isAudioPlaying = true;
                audio.play().catch(function(e) {
                    console.error("Audio play error:", e);
                    complete(true, e);
                });
                audio.onended = function() {
                    complete(false);
                };
                audio.onerror = function(e) {
                    console.error("Audio error:", e);
                    complete(true, e);
                };
                model2._completeSpeech = complete;
            };
            model2.stopSpeaking = function() {
                const audio = model2.currentAudio;
                if (!audio) return;
                audio.pause();
                audio.removeAttribute("src");
                audio.load();
                if (model2._completeSpeech) model2._completeSpeech(false);
            };

            makeDraggable(model2);
            setupMouseEvents(model2);
            app.stage.addChild(model2);

            // Hide loading text
            var loadingEl = document.getElementById("loading");
            if (loadingEl) loadingEl.style.display = "none";

            startIdleAnimation();
            console.log("Sprite character loaded: " + info.url);
            return;
        }

        // LIVE2D MODE: original behavior
        spriteMode = false;
        const options = { autoInteract: false, autoUpdate: true };

        const models = await Promise.all([
            live2d.Live2DModel.from(info.url, options),
        ]);

        models.forEach((model) => {
            app.stage.addChild(model);

            const scaleX = (innerWidth * info.kScale);
            const scaleY = (innerHeight * info.kScale);
            model.scale.set(Math.min(scaleX, scaleY));
            model.y = innerHeight * 0.01;

            makeDraggable(model);
            setupMouseEvents(model);
        });

        model2 = models[0];

        if (!info.initialXshift) info.initialXshift = 0;
        if (!info.initialYshift) info.initialYshift = 0;

        model2.x = app.view.width / 2 - model2.width / 2 + info["initialXshift"];
        model2.y = app.view.height / 2 - model2.height / 2 + info["initialYshift"];

        model2.internalModel.eyeBlink = null;
        keepFaceTowardCamera(model2);
        console.log("Live2D model loaded: " + info.url);
    }

    function keepFaceTowardCamera(model) {
        const coreModel = model.internalModel && model.internalModel.coreModel;
        if (!coreModel) return;

        const centeredParameters = [
            "ParamAngleX",
            "ParamAngleY",
            "ParamAngleZ",
            "ParamEyeBallX",
            "ParamEyeBallY",
        ];
        const setParameter = typeof coreModel.setParameterValueById === "function"
            ? (id) => coreModel.setParameterValueById(id, 0)
            : (id) => coreModel.setParamFloat(id, 0);

        faceCameraTicker = () => centeredParameters.forEach(setParameter);
        app.ticker.add(faceCameraTicker);
    }

    async function setSpriteExpression(expressionIndex) {
        const index = String(parseInt(expressionIndex) || 0);
        const url = spriteExpressionFiles[index];
        if (!spriteMode || !model2 || !url || currentSpriteExpression === index) return;

        const texture = PIXI.Assets && typeof PIXI.Assets.load === "function"
            ? await PIXI.Assets.load(url)
            : await PIXI.Texture.fromURL(url);
        model2.texture = texture;
        currentSpriteExpression = index;
    }

    async function setCharacterMode(mode) {
        if (!spriteMode || !model2 || !mode || !mode.url) return;

        const texture = PIXI.Assets && typeof PIXI.Assets.load === "function"
            ? await PIXI.Assets.load(mode.url)
            : await PIXI.Texture.fromURL(mode.url);

        model2.texture = texture;
        const maxWidth = app.view.width * 0.9;
        const maxHeight = app.view.height * ((modelInfo && modelInfo.heightRatio) || 0.92);
        const scale = Math.min(maxWidth / texture.width, maxHeight / texture.height);
        model2.scale.set(scale);

        // Outfit photos intentionally stay fixed while the assistant speaks.
        // Returning to assistant mode restores the generated expression set.
        spriteExpressionFiles = mode.expressionFiles
            ? Object.assign({}, mode.expressionFiles)
            : { "0": mode.url };
        if (mode.id === "assistant" && !mode.expressionFiles) {
            spriteExpressionFiles = Object.assign({}, defaultSpriteExpressionFiles);
        }
        currentSpriteExpression = "0";
        currentExpression = 0;
        console.log(`Character mode changed to ${mode.name}: ${mode.url}`);
    }

    // Idle float animation for sprite mode
    var floatTime = 0;
    function startIdleAnimation() {
        app.ticker.add((delta) => {
            if (!spriteMode || !model2) return;
            floatTime += delta * 0.02;
            var floatOffset = Math.sin(floatTime) * 10;
            model2.y = idleFloatBaseY + floatOffset;
        });
    }

    function makeDraggable(model) {
        model.interactive = true;
        model.buttonMode = true;

        model.on("pointerdown", (e) => {
            if (e.data.button !== 0) return;
            model.dragging = true;
            model._pointerX = e.data.global.x - model.x;
            model._pointerY = e.data.global.y - model.y;
        });

        model.on("pointermove", (e) => {
            if (model.dragging) {
                model.position.x = e.data.global.x - model._pointerX;
                model.position.y = e.data.global.y - model._pointerY;
                if (spriteMode) idleFloatBaseY = model.position.y;
            }
        });

        model.on("pointerupoutside", () => (model.dragging = false));
        model.on("pointerup", () => (model.dragging = false));
    }

    function setupMouseEvents(model) {
        model.on("pointerover", () => {
            window.electronAPI.setIgnoreMouseEvents(false);
        });
        model.on("pointerout", () => {
            window.electronAPI.setIgnoreMouseEvents(true);
        });
        window.addEventListener('mousedown', (e) => {
            if (e.button === 2) {
                window.electronAPI.showContextMenu(e.screenX, e.screenY);
            }
        });
    }

    return { init, loadModel, setSpriteExpression, setCharacterMode };
})();

// === Expression & Mouth (compatible with both modes) ===

var currentExpression = 0;
function setExpression(expressionIndex) {
    if (spriteMode && model2) {
        currentExpression = parseInt(expressionIndex) || 0;
        window.live2dModule.setSpriteExpression(currentExpression).catch((error) => {
            console.error("Failed to switch sprite expression:", error);
        });
        return;
    }
    // Live2D mode
    expressionIndex = parseInt(expressionIndex);
    if (model2 && model2.internalModel.motionManager.expressionManager) {
        model2.internalModel.motionManager.expressionManager.setExpression(expressionIndex);
    }
}

function setMouth(mouthY) {
    if (spriteMode && model2) {
        // Static photo sprites have no mouth-deformation mesh.
        return;
    }
    // Live2D mode
    if (model2 && model2.internalModel.coreModel) {
        if (typeof model2.internalModel.coreModel.setParameterValueById === 'function') {
            model2.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', mouthY);
        } else {
            model2.internalModel.coreModel.setParamFloat('PARAM_MOUTH_OPEN_Y', mouthY);
        }
    }
}

window.setExpression = setExpression;
window.setMouth = setMouth;
