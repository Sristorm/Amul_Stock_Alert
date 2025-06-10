import requests
import json
import smtplib
import time
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Dict, Optional
import os
from dataclasses import dataclass
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('stock_monitor.log'),
        logging.StreamHandler()
    ]
)

@dataclass
class Product:
    name: str
    url: str
    selector: str  # CSS selector or keyword to check availability
    price_selector: Optional[str] = None

class StockMonitor:
    def __init__(self, debug_mode=False, force_notify=False):
        Configuration - use environment variables for security
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.email_from = os.getenv('EMAIL_FROM')
        self.email_password = os.getenv('EMAIL_PASSWORD')
        self.email_to = os.getenv('EMAIL_TO')
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        
        # Debug and testing options
        self.debug_mode = debug_mode
        self.force_notify = force_notify
        
        # Products to monitor - customize these URLs and selectors
        self.products = [
            Product(
                name="Amul High Protein Milk, 250 mL | Pack of 32",
                url="https://shop.amul.com/en/product/amul-high-protein-milk-250-ml-or-pack-of-32",
                selector="add-to-cart",  # Common selector for buy buttons
                price_selector=".price"
            ),
            Product(
                name="Amul Chocolate Whey Protein, 34 g | Pack of 60 sachets",
                url="https://shop.amul.com/en/product/amul-chocolate-whey-protein-34-g-or-pack-of-60-sachets",
                selector="add-to-cart",
                price_selector=".price"
            ),
            Product(
                name="Amul High Protein Paneer, 400 g | Pack of 24",
                url="https://shop.amul.com/en/product/amul-high-protein-paneer-400-g-or-pack-of-24",
                selector="add-to-cart",
                price_selector=".price"
            ),
            Product(
                name="Amul High Protein Blueberry Shake, 200 mL | Pack of 30",
                url="https://shop.amul.com/en/product/amul-high-protein-blueberry-shake-200-ml-or-pack-of-30",
                selector="add-to-cart",
                price_selector=".price"
            )
        ]
        
        # File to store previous state
        self.state_file = 'stock_state.json'
        self.previous_state = self.load_state()
        
        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def load_state(self) -> Dict:
        """Load previous stock state from file"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Error loading state: {e}")
        return {}

    def save_state(self, state: Dict):
        """Save current stock state to file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving state: {e}")

    def ensure_files_exist(self):
        """Ensure state and log files exist, create them if they don't"""
        try:
            # Ensure log file exists
            if not os.path.exists('stock_monitor.log'):
                with open('stock_monitor.log', 'w') as f:
                    f.write(f"{datetime.now().isoformat()} - Stock monitor log initialized\n")
            
            # Ensure state file exists
            if not os.path.exists(self.state_file):
                initial_state = {
                    'initialized': datetime.now().isoformat(),
                    'last_run': None
                }
                self.save_state(initial_state)
            
            print(f"Files ensured to exist: {os.path.exists('stock_monitor.log')}, {os.path.exists(self.state_file)}")
            
        except Exception as e:
            print(f"Error ensuring files exist: {e}")

    def check_product_availability(self, product: Product) -> Dict:
        """Check if a specific product is available"""
        try:
            response = self.session.get(product.url, timeout=30)
            response.raise_for_status()
            
            content = response.text
            available = self.is_product_available(content, product)
            price = self.extract_price(content, product) if available else None
            
            return {
                'available': available,
                'price': price,
                'last_checked': datetime.now().isoformat(),
                'status_code': response.status_code
            }
            
        except requests.RequestException as e:
            logging.error(f"Error checking {product.name}: {e}")
            return {
                'available': False,
                'price': None,
                'last_checked': datetime.now().isoformat(),
                'error': str(e)
            }

    def is_product_available(self, content: str, product: Product) -> bool:
        """Enhanced availability detection logic"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            
            # Method 1: Check for enabled "Add to Cart" buttons
            add_to_cart_buttons = soup.find_all('a', class_='add-to-cart')
            for button in add_to_cart_buttons:
                button_text = button.get_text(strip=True).lower()
                
                # Only check buttons that actually say "Add to Cart"
                if 'add to cart' in button_text:
                    disabled = button.get('disabled')
                    
                    # For Amul website: disabled="0" means ENABLED, disabled="1" or missing means DISABLED
                    # Also check for other disabled indicators
                    if disabled is None:
                        # No disabled attribute - could be enabled
                        # Check if button has proper onclick or href
                        if button.get('href') or button.get('onclick') or not button.get('disabled'):
                            return True
                    elif str(disabled) == "0":
                        # disabled="0" means the button is actually ENABLED
                        return True
                    elif str(disabled) == "1" or str(disabled).lower() == "true":
                        # disabled="1" or disabled="true" means actually disabled
                        continue
                    
                    # Additional check: look for CSS classes that might indicate disabled state
                    button_classes = button.get('class', [])
                    if any(cls in ['disabled', 'btn-disabled', 'out-of-stock'] for cls in button_classes):
                        continue
                    
                    # If we reach here and have an "Add to Cart" button without clear disabled indicators
                    return True
            
            # Method 2: Check for quantity input field (indicates available product)
            quantity_inputs = soup.find_all('input', {'type': 'text'})
            for input_field in quantity_inputs:
                if input_field.get('placeholder') == 'Quantity' and not input_field.get('disabled'):
                    # If quantity selector is present and not disabled, product is likely available
                    return True
            
            # Method 3: Check for price information (strong indicator of availability)
            price_elements = soup.find_all(class_=lambda x: x and ('price' in x.lower() or 'mrp' in x.lower()))
            if price_elements:
                # If price is shown, product is likely available
                for price_elem in price_elements:
                    price_text = price_elem.get_text(strip=True)
                    if '₹' in price_text or 'rs' in price_text.lower():
                        return True
            
            # Method 4: Text-based checks (fallback)
            content_lower = content.lower()
            
            # Strong indicators of unavailability (these override availability)
            unavailable_patterns = [
                'out of stock',
                'sold out',
                'currently unavailable',
                'notify when available',
                'coming soon',
                'temporarily out of stock',
                'not available',
                'stock not available',
                'currently out of stock'
            ]
            
            for pattern in unavailable_patterns:
                if pattern in content_lower:
                    return False
            
            # Check for availability indicators
            available_patterns = [
                'in stock',
                'available now',
                'buy now',
                'available for purchase',
                'add to cart'
            ]
            
            for pattern in available_patterns:
                if pattern in content_lower:
                    # Double-check it's in a positive context
                    if 'not ' + pattern not in content_lower and 'no ' + pattern not in content_lower:
                        return True
            
            return False
            
        except ImportError:
            # Fallback to text-based detection if BeautifulSoup is not available
            logging.warning("BeautifulSoup not available, using text-based detection")
            return self.text_based_availability_check(content)
        except Exception as e:
            logging.warning(f"Error in availability detection for {product.name}: {e}")
            return self.text_based_availability_check(content)

    def text_based_availability_check(self, content: str) -> bool:
        """Fallback text-based availability check"""
        content_lower = content.lower()
        
        # Check for out of stock indicators
        out_of_stock_patterns = [
            'out of stock', 'sold out', 'currently unavailable',
            'notify when available', 'coming soon', 'not available'
        ]
        
        for pattern in out_of_stock_patterns:
            if pattern in content_lower:
                return False
        
        # Check for in stock indicators
        in_stock_patterns = [
            'add to cart', 'buy now', 'in stock', 'available'
        ]
        
        for pattern in in_stock_patterns:
            if pattern in content_lower:
                return True
        
        # Default to False if we can't determine
        return False

    def extract_price(self, content: str, product: Product) -> Optional[str]:
        """Extract price from product page"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            
            # Try multiple price selectors
            price_selectors = [
                '.price', '.product-price', '.selling-price', '.mrp',
                '[class*="price"]', '[class*="cost"]'
            ]
            
            for selector in price_selectors:
                price_elem = soup.select_one(selector)
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    # Clean up price text
                    price_match = re.search(r'₹[\d,]+(?:\.\d{2})?', price_text)
                    if price_match:
                        return price_match.group()
            
            # Fallback regex search
            price_match = re.search(r'₹[\d,]+(?:\.\d{2})?', content)
            if price_match:
                return price_match.group()
                
        except ImportError:
            # Fallback without BeautifulSoup
            price_match = re.search(r'₹[\d,]+(?:\.\d{2})?', content)
            if price_match:
                return price_match.group()
        except Exception as e:
            logging.warning(f"Error extracting price for {product.name}: {e}")
        
        return None

    def format_notification_message(self, product: Product, status: Dict, status_change: str) -> str:
        """Format notification message"""
        message = f"🏪 <b>Amul Stock Alert</b>\n\n"
        message += f"📦 <b>Product:</b> {product.name}\n"
        message += f"📊 <b>Status:</b> {status_change}\n"
        
        if status.get('price'):
            message += f"💰 <b>Price:</b> {status['price']}\n"
        
        message += f"🔗 <b>Link:</b> {product.url}\n"
        message += f"⏰ <b>Checked:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return message

    def send_telegram_message(self, message: str) -> bool:
        """Send message via Telegram"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logging.warning("Telegram credentials not configured")
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                'chat_id': self.telegram_chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            logging.info("Telegram message sent successfully")
            return True
            
        except Exception as e:
            logging.error(f"Error sending Telegram message: {e}")
            return False

    def send_email(self, subject: str, body: str) -> bool:
        """Send email notification"""
        if not all([self.email_from, self.email_password, self.email_to]):
            logging.warning("Email credentials not configured")
            return False
        
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_from
            msg['To'] = self.email_to
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'html'))
            
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email_from, self.email_password)
            
            text = msg.as_string()
            server.sendmail(self.email_from, self.email_to, text)
            server.quit()
            
            logging.info("Email sent successfully")
            return True
            
        except Exception as e:
            logging.error(f"Error sending email: {e}")
            return False
        
    def monitor_products(self):
        """Main monitoring function - UPDATED VERSION"""
        logging.info("Starting product monitoring...")
        
        # NEW: Ensure files exist at the start
        self.ensure_files_exist()
        
        current_state = {
            'last_run': datetime.now().isoformat(),
            'run_count': self.previous_state.get('run_count', 0) + 1
        }
        notifications_sent = []
        
        try:
            for product in self.products:
                logging.info(f"Checking {product.name}...")
                
                status = self.check_product_availability(product)
                current_state[product.name] = status
                
                # Check if status changed
                previous_status = self.previous_state.get(product.name, {})
                previous_available = previous_status.get('available', False)
                current_available = status['available']
                
                if previous_available != current_available:
                    status_change = "Available ✅" if current_available else "Out of Stock ❌"
                    message = self.format_notification_message(product, status, status_change)
                    
                    # Send notifications
                    telegram_sent = self.send_telegram_message(message)
                    email_sent = self.send_email(
                        f"Amul Stock Alert: {product.name} - {status_change}",
                        message.replace('<b>', '').replace('</b>', '').replace('\n', '<br>')
                    )
                    
                    notifications_sent.append({
                        'product': product.name,
                        'status': status_change,
                        'telegram_sent': telegram_sent,
                        'email_sent': email_sent
                    })
                    
                    logging.info(f"Status changed for {product.name}: {status_change}")
                
                # Rate limiting
                time.sleep(2)
        
        except Exception as e:
            logging.error(f"Error during monitoring: {e}")
            current_state['error'] = str(e)
        
        finally:
            # Always save state and ensure files exist, even if there were errors
            try:
                current_state['notifications_sent'] = len(notifications_sent)
                self.save_state(current_state)
                self.previous_state = current_state
                
                # Log a final message to ensure log file has content
                logging.info(f"Monitoring cycle completed. Checked {len(self.products)} products.")
                
                # Verify files were created
                print(f"Final file check - State file exists: {os.path.exists(self.state_file)}")
                print(f"Final file check - Log file exists: {os.path.exists('stock_monitor.log')}")
                
            except Exception as e:
                print(f"Error in finally block: {e}")
        
        # Log summary
        if notifications_sent:
            logging.info(f"Sent {len(notifications_sent)} notifications")
            for notification in notifications_sent:
                logging.info(f"  {notification}")
        else:
            logging.info("No status changes detected")

def main():
    """Main function to run the monitor"""
    print("=== Starting Amul Stock Monitor ===")
    try:
        monitor = StockMonitor()
        monitor.monitor_products()
        print("=== Stock Monitor Completed Successfully ===")
    except KeyboardInterrupt:
        logging.info("Monitoring stopped by user")
        print("=== Monitoring Stopped by User ===")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        print(f"=== Unexpected Error: {e} ===")
        
        # Even if there's an error, try to create minimal files
        try:
            with open('stock_state.json', 'w') as f:
                json.dump({
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                }, f, indent=2)
        except:
            pass

if __name__ == "__main__":
    main()
