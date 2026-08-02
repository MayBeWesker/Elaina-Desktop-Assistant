# pip install pyautogui pyautogui pillow pyobjc pywin32
import sys
import os
import base64
import subprocess
import json
import pyautogui

if sys.platform == "darwin":
    from computer.loop import sampling_loop, APIProvider
    from computer.tools import ToolResult
    from anthropic.types.beta import BetaMessage, BetaMessageParam
    from anthropic import APIResponse
    async def control_computer(api_key: str, instruction: str, api_response_callback=None):
        messages: list[BetaMessageParam] = [
            {
                "role": "user",
                "content": instruction,
            }
        ]
        
        provider = APIProvider.ANTHROPIC
    
        # Define callbacks (you can customize these)
        def output_callback(content_block):
            if isinstance(content_block, dict) and content_block.get("type") == "text":
                print("Assistant:", content_block.get("text"))
    
        def tool_output_callback(result: ToolResult, tool_use_id: str):
            if result.output:
                print(f"> Tool Output [{tool_use_id}]:", result.output)
            if result.error:
                print(f"!!! Tool Error [{tool_use_id}]:", result.error)
            if result.base64_image:
                # Save the image to a file if needed
                os.makedirs("cache", exist_ok=True)
                image_data = result.base64_image
                with open(f"cache/screenshot_{tool_use_id}.png", "wb") as f:
                    f.write(base64.b64decode(image_data))
                print(f"Took screenshot screenshot_{tool_use_id}.png")
    
        # If no api_response_callback is provided, use a default one
        if api_response_callback is None:
            def api_response_callback(response: APIResponse[BetaMessage]):
                print(
                    "\n---------------\nAPI Response:\n",
                    json.dumps(json.loads(response.text)["content"], indent=4),  # type: ignore
                    "\n",
                )
    
        # Run the sampling loop
        messages = await sampling_loop(
            model="claude-3-5-sonnet-20241022",
            provider=provider,
            system_prompt_suffix="",
            messages=messages,
            output_callback=output_callback,
            tool_output_callback=tool_output_callback,
            api_response_callback=api_response_callback,
            api_key=api_key,
            only_n_most_recent_images=10,
            max_tokens=4096,
        )


def get_clipboard_content():
    content = {}

    if sys.platform.startswith('win'):  # Windows
        import win32clipboard
        import win32con
        from PIL import Image
        import io

        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                text_data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                content['text'] = text_data
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB):
                dib = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
                image = Image.open(io.BytesIO(dib))
                buffered = io.BytesIO()
                image.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
                content['image'] = img_str
        except Exception as e:
            print(f"Error accessing clipboard: {e}")
        finally:
            win32clipboard.CloseClipboard()
    elif sys.platform == 'darwin': # MacOS
        from AppKit import NSPasteboard, NSPasteboardTypePNG, NSPasteboardTypeString
        from Foundation import NSData

        pasteboard = NSPasteboard.generalPasteboard()
        types = pasteboard.types()

        if NSPasteboardTypeString in types:
            text = pasteboard.stringForType_(NSPasteboardTypeString)
            content['text'] = text

        if NSPasteboardTypePNG in types:
            data = pasteboard.dataForType_(NSPasteboardTypePNG)
            if data:
                img_str = base64.b64encode(data.bytes()).decode('utf-8')
                content['image'] = img_str
    else:
        print("Unsupported platform for clipboard operations.")
    return content


def capture_active_window_base64(max_size: int = 1280) -> str | None:
    """Capture the foreground window only, returning a compact PNG as base64."""
    if not sys.platform.startswith("win"):
        return None

    from io import BytesIO
    from PIL import ImageGrab
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    def get_window_title(candidate: int) -> str:
        length = user32.GetWindowTextLengthW(candidate)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(candidate, buffer, length + 1)
        return buffer.value.strip()

    def get_window_rect(candidate: int) -> tuple[int, int, int, int]:
        rect = wintypes.RECT()
        if not user32.GetWindowRect(candidate, ctypes.byref(rect)):
            return 0, 0, 0, 0
        return rect.left, rect.top, rect.right, rect.bottom

    def is_assistant_window(candidate: int) -> bool:
        if not candidate or not user32.IsWindowVisible(candidate):
            return True
        title = get_window_title(candidate)
        if not title:
            return True
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(candidate, ctypes.byref(process_id))
        if process_id.value == os.getpid():
            return True
        title_lower = title.lower()
        assistant_titles = (
            "elaina desktop pet",
            "live2d assistant",
            "桌面助手 - 后端",
            "启动桌面助手",
        )
        if any(marker in title_lower for marker in assistant_titles):
            return True
        if user32.IsIconic(candidate):
            return True
        left, top, right, bottom = get_window_rect(candidate)
        return right - left < 200 or bottom - top < 150

    hwnd = user32.GetForegroundWindow()
    original_hwnd = hwnd
    if is_assistant_window(hwnd):
        candidates = []
        enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(
            lambda candidate, _: candidates.append(candidate) or True
        )
        user32.EnumWindows(enum_callback, 0)
        hwnd = next(
            (candidate for candidate in candidates if not is_assistant_window(candidate)),
            0,
        )
        if hwnd:
            original_title = get_window_title(original_hwnd) if original_hwnd else ""
            print(
                f"[Vision] Assistant window was foreground "
                f"({original_title or '(untitled)'!r}); using the window behind it."
            )

    window_title = get_window_title(hwnd) if hwnd else ""
    if hwnd:
        left, top, right, bottom = get_window_rect(hwnd)
    else:
        left = top = right = bottom = 0

    if right > left and bottom > top:
        image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    else:
        # Headless test runners may have no foreground HWND. On a real desktop,
        # fall back to the visible desktop instead of silently losing vision.
        image = ImageGrab.grab(all_screens=True)
    image.thumbnail((max_size, max_size))
    print(
        f"[Vision] Captured active window: "
        f"title={window_title or '(untitled)'!r}, "
        f"source={right - left}x{bottom - top}, image={image.width}x{image.height}"
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    image_bytes = output.getvalue()
    print(f"[Vision] Screenshot encoded successfully: {len(image_bytes)} bytes")
    return base64.b64encode(image_bytes).decode("ascii")

def copy_selected_content():
    if sys.platform.startswith('win'):
        pyautogui.hotkey('ctrl', 'c')
    elif sys.platform == 'darwin':
        subprocess.run(['osascript', '-e', 'tell application "System Events" to keystroke "c" using {command down}'])
    else:
        print("Unsupported platform for copy operation.")

def screenshot_and_copy():
    if sys.platform.startswith('win'):
        from PIL import ImageGrab
        import win32clipboard
        from io import BytesIO

        img = ImageGrab.grab()
        output = BytesIO()
        img.save(output, 'BMP')
        data = output.getvalue()[14:]
        output.close()

        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
        win32clipboard.CloseClipboard()
    elif sys.platform == 'darwin':
        subprocess.run(['screencapture', '-c'])
    else:
        raise NotImplementedError("Unsupported OS")


def input_text(text):
    if sys.platform.startswith('win'):
        # Windows implementation
        import win32clipboard
        import win32con
        import win32gui
        import win32api

        def set_clipboard_text(text):
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            win32clipboard.CloseClipboard()

        def paste_to_active_window():
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                win32api.PostMessage(hwnd, win32con.WM_PASTE, 0, 0)

        set_clipboard_text(text)
        paste_to_active_window()

    elif sys.platform == 'darwin':
        def set_clipboard_text_mac(text):
            p = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
            p.communicate(input=text.encode('utf-8'))

        def paste_in_active_app():
            script = '''
            tell application "System Events"
                keystroke "v" using command down
            end tell
            '''
            subprocess.call(['osascript', '-e', script])

        set_clipboard_text_mac(text)
        paste_in_active_app()
    else:
        raise NotImplementedError("Unsupported OS")

if __name__ == "__main__":
    # copy_selected_content()
    
    # clipboard_content = get_clipboard_content()
    # print(clipboard_content)
    
    screenshot_and_copy()

    # time.sleep(2)
    # input_text("Hello, this is a test. 你好，这是一个测试。")
