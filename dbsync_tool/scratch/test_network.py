import smtplib
from email.mime.text import MIMEText

def test_gmail():
    host = 'smtp.gmail.com'
    port = 587
    user = 'saadpractice4@gmail.com'
    # Use the app password provided by the user previously
    password = 'txludusmznqxoweo'
    sender = 'saadpractice4@gmail.com'
    receiver = 'saad.sayyed@actin.co.in'

    print(f"Connecting to {host}:{port}...")
    try:
        server = smtplib.SMTP(host, port, timeout=10)
        server.set_debuglevel(1)
        server.starttls()
        print("Logging in...")
        server.login(user, password)
        
        msg = MIMEText("Network Test: Gmail SMTP works.")
        msg['Subject'] = "Network Test"
        msg['From'] = sender
        msg['To'] = receiver
        
        print("Sending mail...")
        server.sendmail(sender, [receiver], msg.as_string())
        server.quit()
        print("Success! Network allows SMTP traffic.")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_gmail()
