import datetime

def send_notification(title, message, channels=None):
    """
    Generic notification backend.
    Currently only logs to a file, but can easily be extended to Telegram/WhatsApp.
    """
    if channels is None:
        channels = ['log']
        
    timestamp = datetime.datetime.now().isoformat()
    
    if 'log' in channels:
        with open('notifications.log', 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {title}\n")
            f.write(f"{message}\n")
            f.write("-" * 40 + "\n")
            
    # if 'telegram' in channels:
    #     send_telegram(title, message)
    # if 'whatsapp' in channels:
    #     send_whatsapp(title, message)
