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
    def __init__(self):
        # Configuration - use environment variables for security
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.email_from = os.getenv('EMAIL_FROM')
        self.email_password = os.getenv('EMAIL_PASSWORD')
        self.email_to = os.getenv('EMAIL_TO')
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        
        # Products to monitor - customize these URLs and selectors
        self.products = [
            Product(
                name="Amul Butter 500g",
                url="https://www.amul.com/products/butter-500g",
                selector="add-to-cart",  # Common selector for buy buttons
                price_selector=".price"
            ),
            Product(
                name="Amul Milk Powder",
                url="https://www.amul.com/products/milk-powder",
                selector="add-to-cart",
                price_selector=".price"
            )
            # Add more products here
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

    def check_product_availability(self, product: Product) -> Dict:
        """Check if a specific product is available"""
        try:
            response = self.session.get(product.url, timeout=30)
            response.raise_for_status()
            
            content = response.text.lower()
            
            # Check for availability indicators
            available = False
            price = None
            
            # Common availability indicators
            availability_indicators = [
                'add to cart',
                'buy now',
                'in stock',
                'available',
                product.selector.lower()
            ]
            
            unavailability_indicators = [
                'out of stock',
                'sold out',
                'unavailable',
                'notify when available',
                'coming soon'
            ]
            
            # Check availability
            for indicator in availability_indicators:
                if indicator in content:
                    available = True
                    break
            
            # Override if unavailable indicators found
            for indicator in unavailability_indicators:
                if indicator in content:
                    available = False
                    break
            
            # Try to extract price if available
            if product.price_selector and available:
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(response.text, 'html.parser')
                    price_element = soup.select_one(product.price_selector)
                    if price_element:
                        price = price_element.get_text(strip=True)
                except ImportError:
                    # BeautifulSoup not available, skip price extraction
                    pass
                except Exception as e:
                    logging.warning(f"Error extracting price for {product.name}: {e}")
            
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

    def send_telegram_message(self, message: str) -> bool:
        """Send message via Telegram bot"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logging.warning("Telegram credentials not configured")
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            data = {
                'chat_id': self.telegram_chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=data, timeout=10)
            response.raise_for_status()
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
            server.send_message(msg)
            server.quit()
            return True
        except Exception as e:
            logging.error(f"Error sending email: {e}")
            return False

    def format_notification_message(self, product: Product, status: Dict, status_change: str) -> str:
        """Format notification message"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"🛍️ <b>Amul Stock Alert</b>\n\n"
        message += f"📦 <b>Product:</b> {product.name}\n"
        message += f"🔗 <b>URL:</b> {product.url}\n"
        message += f"📊 <b>Status:</b> {status_change}\n"
        
        if status.get('price'):
            message += f"💰 <b>Price:</b> {status['price']}\n"
        
        message += f"🕒 <b>Checked at:</b> {timestamp}\n"
        
        if status['available']:
            message += "\n✅ <b>Product is now available! Hurry up!</b>"
        else:
            message += "\n❌ <b>Product is out of stock</b>"
        
        return message

    def monitor_products(self):
        """Main monitoring function"""
        logging.info("Starting product monitoring...")
        current_state = {}
        notifications_sent = []
        
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
        
        # Save current state
        self.save_state(current_state)
        self.previous_state = current_state
        
        # Log summary
        if notifications_sent:
            logging.info(f"Sent {len(notifications_sent)} notifications")
            for notification in notifications_sent:
                logging.info(f"  {notification}")
        else:
            logging.info("No status changes detected")

def main():
    """Main function to run the monitor"""
    try:
        monitor = StockMonitor()
        monitor.monitor_products()
    except KeyboardInterrupt:
        logging.info("Monitoring stopped by user")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()