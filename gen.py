"""
ABCK Token Generator - Headless Railway Edition with Flask
FIXED for Railway deployment
"""

import os, sys, time, random, subprocess, threading, shutil, re, gc, platform, io, warnings, logging
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

_generation_thread = None
_generation_running = False
_generation_stats = {"generated": 0, "total": 0, "status": "idle"}
_tokens_store = []

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['WDM_LOG_LEVEL'] = '0'
os.environ['WDM_PRINT_FIRST_LINE'] = 'False'

warnings.filterwarnings('ignore')
logging.getLogger('selenium').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)

class _FilteredStderr(io.TextIOBase):
    DROP_PATTERNS = (
        "DevTools listening on",
        "GetGpuDriverOverlayInfo",
        "registration_request.cc",
        "TensorFlow Lite XNNPACK delegate",
    )

    def __init__(self, wrapped):
        self._wrapped = wrapped
        self._buf = ""

    def write(self, s):
        try:
            self._buf += s
            while '\n' in self._buf:
                line, self._buf = self._buf.split('\n', 1)
                if any(p in line for p in self.DROP_PATTERNS):
                    continue
                self._wrapped.write(line + '\n')
            return len(s)
        except Exception:
            return 0

    def flush(self):
        try:
            if self._buf:
                line = self._buf
                self._buf = ""
                if not any(p in line for p in self.DROP_PATTERNS):
                    self._wrapped.write(line)
            self._wrapped.flush()
        except Exception:
            pass

if not isinstance(sys.stderr, _FilteredStderr):
    sys.stderr = _FilteredStderr(sys.stderr)

def install_dependencies():
    dependencies = [
        "selenium",
        "requests",
        "webdriver-manager",
        "flask-cors",
    ]
    missing = []
    for dep in dependencies:
        try:
            __import__(dep.replace('-', '_'))
        except ImportError:
            missing.append(dep)

    if missing:
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.common.exceptions import (
        TimeoutException, NoSuchElementException,
        WebDriverException, StaleElementReferenceException
    )
    from webdriver_manager.chrome import ChromeDriverManager
    import requests
except ImportError:
    install_dependencies()
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

IS_LINUX = platform.system() == 'Linux'
IS_WINDOWS = platform.system() == 'Windows'

TARGET_URL             = "https://mtacc.mobilelegends.com"
ABCK_FILE              = os.path.join(os.path.dirname(os.path.abspath(__file__)), "abck.txt")
MAX_THREADS            = 2  # Reduced for Railway memory limits
NUM_BROWSERS           = 2  # Reduced for Railway memory limits
MAX_TOKENS_PER_BROWSER = 10
MAX_CONSECUTIVE_FAILS  = 5
SOLVE_TIMEOUT          = 45
CHECK_INTERVAL         = 0.12
DELAY_BETWEEN_TOKENS   = (0.5, 1.0)
DELAY_BROWSER_RELAUNCH = (1.0, 2.0)
DEFAULT_TOKEN_COUNT    = 30
MAX_TOKENS_IN_MEMORY   = 500
CLEANUP_INTERVAL       = 50
SAVE_TO_FILE           = True
WIN_W, WIN_H           = 1280, 720

_print_lock = threading.Lock()
_file_lock  = threading.Lock()

def cprint(msg):
    with _print_lock:
        print(msg)

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log_info(idx, msg):
    cprint(f"[{ts()}] [B{idx+1}] › {msg}")

def log_status(idx, attempt, gen, fcount, remaining, slot):
    cprint(f"[{ts()}] [B{idx+1}] #{attempt} ↑{gen} ◉{fcount} ◎{remaining} [{slot}/{MAX_TOKENS_PER_BROWSER}]")

def log_solving(idx, elapsed):
    cprint(f"[{ts()}] [B{idx+1}] Bypass Akamai... {elapsed}s")

def log_success(idx, num, tokens, extra=""):
    tok_preview = tokens[:40]
    cprint(f"[{ts()}] [B{idx+1}] ✔ #{num} {tok_preview}... {extra}")

def log_fail(idx, fail, maxf):
    cprint(f"[{ts()}] [B{idx+1}] ✗ FAIL [{fail}/{maxf}]")

def log_warn(idx, msg):
    cprint(f"[{ts()}] [B{idx+1}] ⚠ {msg}")

def log_relaunch(idx, reason):
    cprint(f"[{ts()}] [B{idx+1}] ↻ RELAUNCH {reason}")

def get_chrome_path():
    """Find Chrome executable path - FIXED for Railway"""
    possible_paths = [
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable', 
        '/usr/bin/chromium-browser',
        '/usr/bin/chromium',
        '/opt/google/chrome/chrome',
        '/snap/bin/chromium'
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    # Try to find via which command
    try:
        result = subprocess.run(['which', 'google-chrome'], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except:
        pass
    
    return None

def get_chromedriver_path():
    """Get chromedriver path - FIXED to use webdriver-manager"""
    try:
        # Let webdriver-manager handle it
        driver_path = ChromeDriverManager().install()
        return driver_path
    except Exception as e:
        log_warn(0, f"WebDriver Manager error: {e}")
        
        # Fallback paths
        fallback_paths = [
            '/usr/bin/chromedriver',
            '/usr/local/bin/chromedriver',
            '/snap/bin/chromedriver'
        ]
        
        for path in fallback_paths:
            if os.path.exists(path):
                return path
    return None

def load_existing_tokens():
    if not SAVE_TO_FILE or not os.path.exists(ABCK_FILE):
        return set()
    try:
        with open(ABCK_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        recent = lines[-MAX_TOKENS_IN_MEMORY:] if len(lines) > MAX_TOKENS_IN_MEMORY else lines
        return {line.strip() for line in recent if line.strip()}
    except Exception:
        return set()

def save_tokens(tokens):
    if not SAVE_TO_FILE:
        return
    with _file_lock:
        with open(ABCK_FILE, 'a', encoding='utf-8') as f:
            f.write(tokens + '\n')

def send_tokens_to_server(tokens, use_server=False):
    if not use_server:
        return None
    # Store locally instead of external server
    global _tokens_store
    _tokens_store.append({
        "token": tokens,
        "timestamp": datetime.now().isoformat()
    })
    return "local_storage"

_ram_tokens_count = 0
_ram_tokens_count_lock = threading.Lock()

def count_tokens():
    with _ram_tokens_count_lock:
        return _ram_tokens_count

def increment_tokens_count():
    global _ram_tokens_count
    with _ram_tokens_count_lock:
        _ram_tokens_count += 1
        return _ram_tokens_count

_chrome_version_cache = None

def get_chrome_version():
    global _chrome_version_cache
    if _chrome_version_cache is not None:
        return _chrome_version_cache

    chrome_path = get_chrome_path()
    if chrome_path:
        try:
            result = subprocess.run([chrome_path, '--version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                match = re.search(r'(\d+)\.', result.stdout)
                if match:
                    _chrome_version_cache = int(match.group(1))
                    return _chrome_version_cache
        except Exception:
            pass
    return 120  # Default fallback version

def cleanup_chrome_garbage():
    base = _get_temp_base()
    cleaned = 0
    prefixes = ('scoped_dir', '.com.google', 'chrome_', 'Crashpad',
                'uc_', '.org.chromium', 'tmp', 'gpu-process')
    try:
        for name in os.listdir(base):
            if any(name.startswith(p) for p in prefixes):
                path = os.path.join(base, name)
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        os.remove(path)
                    cleaned += 1
                except Exception:
                    pass
    except Exception:
        pass
    gc.collect()
    return cleaned

def kill_chrome():
    if IS_LINUX:
        for proc in ['chrome', 'chromedriver', 'google-chrome', 'chromium']:
            try:
                subprocess.run(['pkill', '-f', proc], capture_output=True, timeout=5)
            except Exception:
                pass
    else:
        for proc in ['chrome.exe', 'chromedriver.exe']:
            try:
                subprocess.run(['taskkill', '/F', '/IM', proc], capture_output=True, timeout=5)
            except Exception:
                pass

def _get_temp_base():
    return os.environ.get('TEMP', os.environ.get('TMP', '/tmp'))

def _cleanup_old_temp_dirs():
    base = _get_temp_base()
    try:
        for name in os.listdir(base):
            if name.startswith('uc_b'):
                path = os.path.join(base, name)
                try:
                    shutil.rmtree(path, ignore_errors=True)
                except Exception:
                    pass
    except Exception:
        pass

def create_driver(chrome_ver=None, browser_index=0):
    for attempt in range(3):
        try:
            options = Options()
            
            # Essential headless options for Railway
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-popup-blocking")
            options.add_argument("--disable-infobars")
            options.add_argument("--disable-default-apps")
            options.add_argument("--single-process")
            options.add_argument("--disable-logging")
            options.add_argument("--disable-crash-reporter")
            options.add_argument("--disable-component-update")
            options.add_argument("--disable-sync")
            options.add_argument("--disable-translate")
            options.add_argument("--log-level=3")
            options.add_argument("--disable-domain-reliability")
            options.add_argument("--disable-client-side-phishing-detection")
            options.add_argument("--safebrowsing-disable-auto-update")
            options.add_argument(f"--window-size={WIN_W},{WIN_H}")
            
            # Memory optimization for Railway
            options.add_argument("--memory-pressure-off")
            options.add_argument("--max_old_space_size=256")
            
            # Set user agent
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            options.add_argument(f"--user-agent={user_agent}")
            
            # Remove automation flags
            options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
            options.add_experimental_option("useAutomationExtension", False)
            
            # Set binary location
            chrome_path = get_chrome_path()
            if chrome_path:
                options.binary_location = chrome_path
                log_info(browser_index, f"Using Chrome: {chrome_path}")
            
            # Get chromedriver
            chromedriver_path = get_chromedriver_path()
            if not chromedriver_path:
                log_warn(browser_index, "ChromeDriver not found!")
                return None
            
            # Create driver
            service = webdriver.chrome.service.Service(chromedriver_path)
            driver = webdriver.Chrome(service=service, options=options)
            
            driver.set_page_load_timeout(30)
            driver.set_script_timeout(30)
            
            # Remove webdriver property
            try:
                driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})")
                driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['en-US']})")
            except Exception:
                pass
            
            return driver
            
        except Exception as e:
            err_msg = str(e)
            log_warn(browser_index, f"Launch failed ({attempt+1}/3): {err_msg[:150]}")
            time.sleep(1)
    
    return None

def generate_mobile_fingerprint() -> dict:
    return {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "platform": "Windows",
        "hardware_concurrency": 4,
        "device_memory": 4,
        "webgl_vendor": "Google Inc.",
        "webgl_renderer": "ANGLE (Intel, Intel UHD Graphics)",
    }

def inject_fingerprint(driver, fingerprint_data):
    try:
        script = f"""
        Object.defineProperty(navigator, 'platform', {{ get: () => '{fingerprint_data.get("platform", "Windows")}' }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {fingerprint_data.get("hardware_concurrency", 4)} }});
        Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {fingerprint_data.get("device_memory", 4)} }});
        """
        driver.execute_script(script)
    except Exception:
        pass

def safe_quit(driver, browser_index=None):
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
        cleanup_chrome_garbage()

def get_solved_abck(cookies):
    for c in cookies:
        if c.get('name') == '_abck' and '~0~' in c.get('value', ''):
            return c['value']
    return None

def wait_for_solve(driver, timeout=SOLVE_TIMEOUT, browser_index=0):
    start = time.time()
    last_log = -10

    try:
        driver.get(TARGET_URL)
        time.sleep(3)
    except Exception as e:
        log_warn(browser_index, f"Page load error: {e}")
        return None

    while time.time() - start < timeout:
        try:
            cookies = driver.get_cookies()
            solved = get_solved_abck(cookies)
            if solved:
                return solved
        except Exception:
            pass

        elapsed = int(time.time() - start)
        if elapsed - last_log >= 8:
            log_solving(browser_index, elapsed)
            last_log = elapsed
        
        time.sleep(CHECK_INTERVAL)
    
    return None

class SharedState:
    def __init__(self, target_count, loop_forever):
        self.target_count = target_count
        self.loop_forever = loop_forever
        self.generated    = 0
        self.existing     = load_existing_tokens()
        self.lock         = threading.Lock()
        self.stop_event   = threading.Event()

    def should_continue(self):
        if self.stop_event.is_set():
            return False
        if self.loop_forever:
            return True
        with self.lock:
            return self.generated < self.target_count

    def add_tokens(self, tokens):
        with self.lock:
            if tokens in self.existing:
                return False
            self.existing.add(tokens)
            if len(self.existing) > MAX_TOKENS_IN_MEMORY:
                excess = len(self.existing) - MAX_TOKENS_IN_MEMORY
                for _ in range(excess):
                    self.existing.pop()
            self.generated += 1
            if self.generated % CLEANUP_INTERVAL == 0:
                cleanup_chrome_garbage()
            return True

def browser_worker(idx, shared, use_server, chrome_ver):
    driver = None
    consec_fails = 0
    tok_this_br  = 0
    attempt      = 0

    try:
        while shared.should_continue():
            attempt += 1
            
            driver_alive = False
            if driver is not None:
                try:
                    driver.current_url
                    driver_alive = True
                except Exception:
                    driver_alive = False
            
            need_new = (
                driver is None or
                not driver_alive or
                consec_fails >= MAX_CONSECUTIVE_FAILS or
                tok_this_br  >= MAX_TOKENS_PER_BROWSER
            )

            if need_new:
                if driver is not None:
                    reason = (f"{consec_fails}×" if consec_fails >= MAX_CONSECUTIVE_FAILS else f"{tok_this_br} tokens")
                    log_relaunch(idx, reason)
                    safe_quit(driver, idx)
                    driver = None
                    time.sleep(random.uniform(*DELAY_BROWSER_RELAUNCH))

                log_info(idx, "Opening browser…")
                driver = create_driver(chrome_ver=chrome_ver, browser_index=idx)
                if not driver:
                    log_warn(idx, "Browser failed! Retry in 3s…")
                    time.sleep(3)
                    continue

                consec_fails = 0
                tok_this_br  = 0

            with shared.lock:
                gen_now = shared.generated
            remaining = "∞" if shared.loop_forever else str(shared.target_count - gen_now)
            file_count = count_tokens()
            log_status(idx, attempt, gen_now, file_count, remaining, tok_this_br)

            token = wait_for_solve(driver, timeout=SOLVE_TIMEOUT, browser_index=idx)

            if token:
                if shared.add_tokens(token):
                    save_tokens(token)
                    increment_tokens_count()
                    server_id = send_tokens_to_server(token, use_server)
                    tok_this_br += 1
                    consec_fails = 0
                    with shared.lock:
                        g = shared.generated
                    extra = f"  [srv:{server_id}]" if use_server and server_id else ""
                    log_success(idx, g, token, extra)
                    time.sleep(random.uniform(*DELAY_BETWEEN_TOKENS))
                else:
                    log_warn(idx, "Duplicate token, skip")
                    try: 
                        driver.delete_all_cookies()
                    except Exception: 
                        pass
            else:
                consec_fails += 1
                log_fail(idx, consec_fails, MAX_CONSECUTIVE_FAILS)
                try:
                    driver.delete_all_cookies()
                except Exception:
                    safe_quit(driver, idx)
                    driver = None

            if shared.should_continue():
                time.sleep(random.uniform(*DELAY_BETWEEN_TOKENS))

    except Exception as e:
        log_warn(idx, f"Error: {e}")
    finally:
        safe_quit(driver, idx)
        log_info(idx, "Worker finished.")

def generate(target_count, loop_forever=False, use_server=False):
    shared = SharedState(target_count, loop_forever)
    threads = []

    chrome_ver = get_chrome_version()
    for i in range(NUM_BROWSERS):
        t = threading.Thread(
            target=browser_worker,
            args=(i, shared, use_server, chrome_ver),
            daemon=True, name=f"B{i+1}"
        )
        threads.append(t)
        t.start()
        if i < NUM_BROWSERS - 1:
            time.sleep(2)

    try:
        while any(t.is_alive() for t in threads):
            if not loop_forever and not shared.should_continue():
                shared.stop_event.set()
            time.sleep(1)
    except KeyboardInterrupt:
        cprint("\n⚠  Stopped by user (Ctrl+C)")
        shared.stop_event.set()

    for t in threads:
        try:
            t.join(timeout=10)
        except KeyboardInterrupt:
            pass

    return shared.generated

def _generation_worker(threads, loop_forever, use_server):
    global _generation_running, _generation_stats
    try:
        _generation_stats["status"] = "running"
        start = time.time()
        generated = generate(DEFAULT_TOKEN_COUNT, loop_forever, use_server)
        elapsed = time.time() - start
        total = count_tokens()
        
        _generation_stats["generated"] = generated
        _generation_stats["total"] = total
        _generation_stats["status"] = "completed"
        _generation_stats["elapsed"] = int(elapsed)
        
        cprint(f"[{ts()}] [INFO] Generation complete: {generated} tokens in {int(elapsed)}s")
    except Exception as e:
        _generation_stats["status"] = "error"
        _generation_stats["error"] = str(e)
        cprint(f"[{ts()}] [ERROR] {e}")
    finally:
        _generation_running = False
        kill_chrome()
        cleanup_chrome_garbage()

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "service": "ABCK Token Generator",
        "status": _generation_stats["status"],
        "generated": _generation_stats["generated"],
        "total": _generation_stats["total"],
        "endpoints": ["/status", "/start", "/stop", "/health", "/tokens"]
    })

@app.route('/status', methods=['GET'])
def status():
    return jsonify({
        "status": _generation_stats["status"],
        "generated": _generation_stats["generated"],
        "total": _generation_stats["total"],
        "elapsed": _generation_stats.get("elapsed", 0),
        "error": _generation_stats.get("error"),
        "is_running": _generation_running
    })

@app.route('/start', methods=['POST'])
def start_generation():
    global _generation_thread, _generation_running, NUM_BROWSERS
    
    if _generation_running:
        return jsonify({"error": "Generation already running"}), 400
    
    data = request.json or {}
    threads = min(data.get("threads", 1), MAX_THREADS)
    use_server = data.get("use_server", False)  # Default to False for Railway
    
    NUM_BROWSERS = threads
    _generation_stats["status"] = "starting"
    _generation_stats["generated"] = 0
    _generation_stats["total"] = count_tokens()
    _generation_running = True
    
    _cleanup_old_temp_dirs()
    
    _generation_thread = threading.Thread(
        target=_generation_worker,
        args=(threads, True, use_server),
        daemon=False
    )
    _generation_thread.start()
    
    return jsonify({
        "message": "Generation started",
        "threads": threads,
        "use_server": use_server
    })

@app.route('/stop', methods=['POST'])
def stop_generation():
    global _generation_running
    _generation_running = False
    kill_chrome()
    return jsonify({"message": "Stop signal sent"})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "ok": True,
        "chrome_available": get_chrome_path() is not None,
        "chromedriver_available": get_chromedriver_path() is not None
    })

@app.route('/tokens', methods=['GET'])
def get_tokens():
    limit = request.args.get('limit', 50, type=int)
    try:
        with open(ABCK_FILE, 'r') as f:
            all_tokens = f.readlines()
        recent_tokens = all_tokens[-limit:]
        return jsonify({
            "total": len(all_tokens),
            "tokens": [t.strip() for t in recent_tokens]
        })
    except:
        return jsonify({"total": 0, "tokens": []})

def main():
    port = int(os.environ.get('PORT', 5000))
    cprint(f"[{ts()}] Starting ABCK Token Generator on port {port}")
    cprint(f"[{ts()}] Chrome available: {get_chrome_path() is not None}")
    cprint(f"[{ts()}] ChromeDriver available: {get_chromedriver_path() is not None}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)

if __name__ == "__main__":
    main()