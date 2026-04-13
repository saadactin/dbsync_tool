import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def test_smtp(port=587, use_ssl=False):
    host = 'smtp.sendgrid.net'
    user = 'apikey'
    password = 'SG.4r9HO5M4TOWmzlrttzcJg.N1qohZTCiGsIwrIzB98RYwjdV7BxBVk8AgOPRhk1sx0'
    sender = 'No-reply@actin.co.in'
    receiver = 'saad.sayyed@actin.co.in'

    print(f"\n--- Testing {host}:{port} (SSL: {use_ssl}) ---")
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.set_debuglevel(1)
            server.starttls()
        
        print("Logging in...")
        server.login(user, password)
        
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = receiver
        msg['Subject'] = f"SMTP Test - Port {port}"
        msg.attach(MIMEText("Hello, this is a test email.", 'plain'))
        
        print("Sending mail...")
        server.send_message(msg)
        server.quit()
        print("Success!")
    except Exception as e:
        print(f"Failed on port {port}: {e}")

if __name__ == "__main__":
    test_smtp(587, False)
    test_smtp(465, True)
    test_smtp(2525, False)
