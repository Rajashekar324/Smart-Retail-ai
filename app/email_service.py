import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import settings


def send_password_reset_email(email: str, reset_token: str, user_name: str):
    """Send password reset email to user"""
    try:
        reset_link = f"http://localhost:8000/reset-password?token={reset_token}"
        
        msg = MIMEMultipart()
        msg['From'] = settings.mail_from
        msg['To'] = email
        msg['Subject'] = "Password Reset Request - StyleHub AI Store"
        
        body = f"""
        <html>
        <body>
            <h2>Password Reset Request</h2>
            <p>Hi {user_name},</p>
            <p>We received a request to reset your password for your StyleHub AI Store account.</p>
            <p>Click the link below to reset your password:</p>
            <p><a href="{reset_link}">Reset Password</a></p>
            <p>Or copy and paste this link in your browser:</p>
            <p>{reset_link}</p>
            <p>This link will expire in {settings.password_reset_expire_hours} hour(s).</p>
            <p>If you did not request this password reset, please ignore this email.</p>
            <br>
            <p>Best regards,<br>StyleHub AI Store Team</p>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        if settings.mail_username and settings.mail_password:
            server = smtplib.SMTP(settings.mail_server, settings.mail_port)
            if settings.mail_tls:
                server.starttls()
            server.login(settings.mail_username, settings.mail_password)
            server.sendmail(settings.mail_from, email, msg.as_string())
            server.quit()
        
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False
