"""
Provides functions to send email notifications.
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.utils import COMMASPACE, formatdate
from email.encoders import encode_base64

from .logger import get_logger
from .configuration import Configuration

logger = get_logger()


def send_mail(receiver, subject, text, files):
    """
    Sends an email to given receiver with given
    subject, text and attachements.

    Args:
        receiver (str): The receiver email address.
        subject (str): The email's subject.
        text (str): The email's content.
        files (list): List of files/attachements.
    """
    email_cfg = Configuration().email_notifications
    if not email_cfg or not email_cfg.get("sender") or not email_cfg.get("server"):
        logger.error("Email sender or server not defined in configuration")
        return False

    email_from = email_cfg.get("sender")
    email_server = email_cfg.get("server")

    msg = MIMEMultipart()
    msg["From"] = email_from
    msg["To"] = COMMASPACE.join([receiver])
    msg["Date"] = formatdate(localtime=True)
    msg["Subject"] = subject

    msg.attach(MIMEText(text))

    if files:
        for attachement in files:
            part = MIMEBase("text", "plain")
            part.set_payload(open(attachement, "rb").read())
            encode_base64(part)
            part.add_header(
                "Content-Disposition",
                'attachment; filename="%s"' % os.path.basename(attachement),
            )
            msg.attach(part)

    try:
        smtp = smtplib.SMTP(email_server)
        smtp.sendmail(email_from, receiver, msg.as_string())
        smtp.close()
        logger.debug("email sent to '%s'", receiver)
    except smtplib.SMTPException as exc:
        logger.error("could not send email: '%s'", str(exc))
