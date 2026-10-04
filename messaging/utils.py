# messaging/utils.py

from __future__ import annotations

from dataclasses import dataclass
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional, Sequence, Tuple, Union

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from django.conf import settings
from django.template import Context, Template
from django.utils import timezone

from .models import EmailTemplate, EmailSendLog, WhatsAppTemplate, WhatsAppSendLog


import requests


class EmailSendError(Exception):
    pass


@dataclass
class SendResult:
    ok: bool
    message_id: str = ""
    error: str = ""
    skipped: bool = False


def email_sending_enabled() -> bool:
    return bool(getattr(settings, "EMAIL_SENDING_ENABLED", True))


def normalize_emails(emails: Union[str, Sequence[str], None]) -> list[str]:
    if not emails:
        return []

    if isinstance(emails, str):
        emails = [emails]

    return [email.strip() for email in emails if email and email.strip()]


def get_ses_client():
    region = getattr(settings, "AWS_REGION", None) or getattr(settings, "AWS_DEFAULT_REGION", None)

    if not region:
        raise EmailSendError("AWS region is not configured. Add AWS_REGION in settings/.env.")

    access_key = getattr(settings, "AWS_ACCESS_KEY_ID", None)
    secret_key = getattr(settings, "AWS_SECRET_ACCESS_KEY", None)

    kwargs = {"region_name": region}

    if access_key and secret_key:
        kwargs.update(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    return boto3.client("ses", **kwargs)


def get_active_template(template_type: str) -> EmailTemplate:
    template = (
        EmailTemplate.objects
        .filter(type=template_type, is_active=True)
        .prefetch_related("attachments")
        .first()
    )

    if not template:
        raise EmailSendError(f"No active email template found for '{template_type}'.")

    return template


def render_template_string(
    template_str: str,
    context: Dict[str, Any],
    autoescape: bool = True,
) -> str:
    """
    Render a stored template. Pass autoescape=False for plain text (email
    subjects, text bodies, WhatsApp messages) so "Ravi & Priya" doesn't
    arrive as "Ravi &amp; Priya".
    """
    if not template_str:
        return ""

    return Template(template_str).render(Context(context, autoescape=autoescape))


def render_email_from_template(
    template: EmailTemplate,
    context: Dict[str, Any],
) -> Tuple[str, str, str]:
    context = dict(context or {})
    context.setdefault("now", timezone.now())
    context.setdefault("today", timezone.localdate())

    subject = render_template_string(template.subject, context, autoescape=False).strip()
    body_html = render_template_string(template.body_html, context)
    body_text = render_template_string(template.body_text, context, autoescape=False)

    if not subject:
        raise EmailSendError(f"Template '{template.slug}' produced an empty subject.")

    if not body_html and not body_text:
        raise EmailSendError(f"Template '{template.slug}' produced an empty body.")

    return subject, body_html, body_text


def send_email_ses(
    *,
    to_emails: Union[str, Sequence[str]],
    subject: str,
    body_html: str = "",
    body_text: str = "",
    from_email: Optional[str] = None,
    reply_to: Optional[Union[str, Sequence[str]]] = None,
    cc: Optional[Union[str, Sequence[str]]] = None,
    bcc: Optional[Union[str, Sequence[str]]] = None,
    charset: str = "UTF-8",
) -> SendResult:
    if not email_sending_enabled():
        return SendResult(
            ok=False,
            skipped=True,
            error="Email sending is disabled in settings.",
        )

    to_list = normalize_emails(to_emails)
    cc_list = normalize_emails(cc)
    bcc_list = normalize_emails(bcc)
    reply_to_list = normalize_emails(reply_to)

    if not to_list:
        return SendResult(ok=False, error="No recipient email provided.")

    sender = (
        from_email
        or getattr(settings, "EMAIL_DEFAULT_FROM", "")
        or getattr(settings, "AWS_SES_SENDER", "")
    ).strip()

    if not sender:
        return SendResult(ok=False, error="Sender email is not configured.")

    destination = {"ToAddresses": to_list}

    if cc_list:
        destination["CcAddresses"] = cc_list

    if bcc_list:
        destination["BccAddresses"] = bcc_list

    message = {
        "Subject": {"Data": subject, "Charset": charset},
        "Body": {},
    }

    if body_text:
        message["Body"]["Text"] = {"Data": body_text, "Charset": charset}

    if body_html:
        message["Body"]["Html"] = {"Data": body_html, "Charset": charset}

    try:
        client = get_ses_client()

        kwargs = {
            "Source": sender,
            "Destination": destination,
            "Message": message,
        }

        if reply_to_list:
            kwargs["ReplyToAddresses"] = reply_to_list

        response = client.send_email(**kwargs)

        return SendResult(
            ok=True,
            message_id=response.get("MessageId", ""),
        )

    except (ClientError, BotoCoreError) as exc:
        return SendResult(ok=False, error=str(exc))


def send_raw_email_ses(
    *,
    to_emails: Union[str, Sequence[str]],
    subject: str,
    body_html: str = "",
    body_text: str = "",
    attachments: Optional[list[dict]] = None,
    from_email: Optional[str] = None,
    reply_to: Optional[Union[str, Sequence[str]]] = None,
) -> SendResult:
    if not email_sending_enabled():
        return SendResult(
            ok=False,
            skipped=True,
            error="Email sending is disabled in settings.",
        )

    to_list = normalize_emails(to_emails)
    reply_to_list = normalize_emails(reply_to)

    if not to_list:
        return SendResult(ok=False, error="No recipient email provided.")

    sender = (
        from_email
        or getattr(settings, "EMAIL_DEFAULT_FROM", "")
        or getattr(settings, "AWS_SES_SENDER", "")
    ).strip()

    if not sender:
        return SendResult(ok=False, error="Sender email is not configured.")

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to_list)

    if reply_to_list:
        msg["Reply-To"] = ", ".join(reply_to_list)

    alternative = MIMEMultipart("alternative")

    if body_text:
        alternative.attach(MIMEText(body_text, "plain", "utf-8"))

    if body_html:
        alternative.attach(MIMEText(body_html, "html", "utf-8"))

    msg.attach(alternative)

    for attachment in attachments or []:
        filename = attachment.get("filename")
        content = attachment.get("content")
        content_type = attachment.get("content_type") or "application/octet-stream"

        if not filename or content is None:
            continue

        part = MIMEApplication(content)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        part.add_header("Content-Type", content_type)
        msg.attach(part)

    try:
        client = get_ses_client()

        response = client.send_raw_email(
            Source=sender,
            Destinations=to_list,
            RawMessage={"Data": msg.as_string()},
        )

        return SendResult(
            ok=True,
            message_id=response.get("MessageId", ""),
        )

    except (ClientError, BotoCoreError) as exc:
        return SendResult(ok=False, error=str(exc))


def build_template_attachments(template: EmailTemplate) -> list[dict]:
    attachments = []

    for item in template.attachments.filter(is_active=True):
        if not item.file:
            continue

        filename = item.display_name or item.file.name.split("/")[-1]

        item.file.open("rb")
        content = item.file.read()
        item.file.close()

        attachments.append({
            "filename": filename,
            "content": content,
            "content_type": "application/octet-stream",
        })

    return attachments


def send_templated_email(
    *,
    template_type: str,
    to_emails: Union[str, Sequence[str]],
    context: Dict[str, Any],
    related_object=None,
    generated_pdf: Optional[dict] = None,
    from_email: Optional[str] = None,
    reply_to: Optional[Union[str, Sequence[str]]] = None,
) -> SendResult:
    """
    Main function for proposal/contract/invoice/payment/anniversary/campaign.

    generated_pdf example:
    {
        "filename": "invoice-1001.pdf",
        "content": pdf_bytes,
        "content_type": "application/pdf",
    }
    """

    log = EmailSendLog(
        template_type=template_type,
        to_email=", ".join(normalize_emails(to_emails)),
        related_model=related_object.__class__.__name__ if related_object else "",
        related_object_id=getattr(related_object, "pk", None),
    )

    try:
        template = get_active_template(template_type)
        log.template = template

        subject, body_html, body_text = render_email_from_template(template, context)
        log.subject = subject
        log.save()

        attachments = build_template_attachments(template)

        if template.attach_generated_pdf and generated_pdf:
            attachments.append(generated_pdf)

        if attachments:
            result = send_raw_email_ses(
                to_emails=to_emails,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
                attachments=attachments,
                from_email=from_email,
                reply_to=reply_to,
            )
        else:
            result = send_email_ses(
                to_emails=to_emails,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
                from_email=from_email,
                reply_to=reply_to,
            )

        if result.ok:
            log.mark_sent(result.message_id)
        else:
            if result.skipped:
                log.status = EmailSendLog.Status.SKIPPED
                log.error_message = result.error
                log.save(update_fields=["status", "error_message"])
            else:
                log.mark_failed(result.error)

        return result

    except Exception as exc:
        log.status = EmailSendLog.Status.FAILED
        log.error_message = str(exc)
        log.save()
        return SendResult(ok=False, error=str(exc))
    




class WhatsAppSendError(Exception):
    pass


@dataclass
class WhatsAppSendResult:
    ok: bool
    message_id: str = ""
    error: str = ""
    skipped: bool = False
    raw_response: dict | None = None


def whatsapp_sending_enabled() -> bool:
    return bool(getattr(settings, "WHATSAPP_SENDING_ENABLED", False))


def normalize_whatsapp_number(number: str | None) -> str:
    """
    WhatsApp Cloud API expects country-code format without +.
    Example:
    +919999999999 -> 919999999999
    9999999999    -> 919999999999, assuming India.
    """

    if not number:
        return ""

    number = str(number).strip()
    number = number.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

    if number.startswith("+"):
        number = number[1:]

    # Simple India fallback
    if len(number) == 10:
        number = "91" + number

    return number


def resolve_context_value(context: Dict[str, Any], path: str) -> str:
    """
    Resolves paths like:
    event.name
    event.date
    venue.name
    client.name
    """

    current: Any = context

    for part in path.split("."):
        if current is None:
            return ""

        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)

        if callable(current):
            current = current()

    if current is None:
        return ""

    return str(current)


def get_active_whatsapp_template(
    template_type: str,
    provider: str | None = None,
    language_code: str | None = None,
) -> WhatsAppTemplate:
    provider = provider or getattr(settings, "WHATSAPP_PROVIDER", "meta")

    qs = WhatsAppTemplate.objects.filter(
        type=template_type,
        provider=provider,
        is_active=True,
        is_default_for_type=True,
    )

    if language_code:
        qs = qs.filter(language_code=language_code)

    template = qs.first()

    if not template:
        raise WhatsAppSendError(
            f"No active WhatsApp template found for type '{template_type}' and provider '{provider}'."
        )

    return template


def build_meta_template_components(
    *,
    template: WhatsAppTemplate,
    context: Dict[str, Any],
) -> list[dict]:
    """
    For simple BODY variables.
    Example Meta format:
    components: [
      {
        "type": "body",
        "parameters": [
          {"type": "text", "text": "Event Name"},
          {"type": "text", "text": "2026-05-07"}
        ]
      }
    ]
    """

    parameters = []

    for variable_path in template.variable_order or []:
        value = resolve_context_value(context, variable_path)
        parameters.append({
            "type": "text",
            "text": value,
        })

    if not parameters:
        return []

    return [
        {
            "type": "body",
            "parameters": parameters,
        }
    ]


def send_meta_whatsapp_template(
    *,
    to_number: str,
    template: WhatsAppTemplate,
    context: Dict[str, Any],
) -> WhatsAppSendResult:
    if not whatsapp_sending_enabled():
        return WhatsAppSendResult(
            ok=False,
            skipped=True,
            error="WhatsApp sending is disabled in settings.",
        )

    access_token = getattr(settings, "META_WHATSAPP_ACCESS_TOKEN", "")
    phone_number_id = getattr(settings, "META_WHATSAPP_PHONE_NUMBER_ID", "")
    api_version = getattr(settings, "META_WHATSAPP_API_VERSION", "v22.0")

    if not access_token:
        return WhatsAppSendResult(ok=False, error="META_WHATSAPP_ACCESS_TOKEN is not configured.")

    if not phone_number_id:
        return WhatsAppSendResult(ok=False, error="META_WHATSAPP_PHONE_NUMBER_ID is not configured.")

    to_number = normalize_whatsapp_number(to_number)

    if not to_number:
        return WhatsAppSendResult(ok=False, error="No WhatsApp number provided.")

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "template",
        "template": {
            "name": template.provider_template_name,
            "language": {
                "code": template.language_code,
            },
        },
    }

    components = build_meta_template_components(
        template=template,
        context=context,
    )

    if components:
        payload["template"]["components"] = components

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=30,
        )

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}

        if response.status_code >= 400:
            return WhatsAppSendResult(
                ok=False,
                error=str(data),
                raw_response=data,
            )

        messages = data.get("messages") or []
        message_id = ""

        if messages:
            message_id = messages[0].get("id", "")

        return WhatsAppSendResult(
            ok=True,
            message_id=message_id,
            raw_response=data,
        )

    except requests.RequestException as exc:
        return WhatsAppSendResult(ok=False, error=str(exc))


def send_msg91_whatsapp_template(
    *,
    to_number: str,
    template: WhatsAppTemplate,
    context: Dict[str, Any],
) -> WhatsAppSendResult:
    """
    Placeholder for MSG91.

    MSG91 setup depends on your MSG91 WhatsApp flow/template configuration.
    Keep this function here so your project can switch provider later.
    """

    return WhatsAppSendResult(
        ok=False,
        skipped=True,
        error="MSG91 WhatsApp provider is not implemented yet. Use Meta provider first.",
    )


def send_templated_whatsapp(
    *,
    template_type: str,
    to_number: str,
    context: Dict[str, Any],
    related_object=None,
    provider: str | None = None,
    language_code: str | None = None,
) -> WhatsAppSendResult:
    provider = provider or getattr(settings, "WHATSAPP_PROVIDER", "meta")

    log = WhatsAppSendLog(
        template_type=template_type,
        provider=provider,
        to_number=normalize_whatsapp_number(to_number),
        related_model=related_object.__class__.__name__ if related_object else "",
        related_object_id=getattr(related_object, "pk", None),
    )

    try:
        template = get_active_whatsapp_template(
            template_type=template_type,
            provider=provider,
            language_code=language_code,
        )

        log.template = template

        preview_context = dict(context or {})
        preview_context.setdefault("now", timezone.now())
        preview_context.setdefault("today", timezone.localdate())

        log.rendered_message = render_template_string(
            template.body_text,
            preview_context,
            autoescape=False,
        )
        log.save()

        if provider == WhatsAppTemplate.Provider.META:
            result = send_meta_whatsapp_template(
                to_number=to_number,
                template=template,
                context=preview_context,
            )
        elif provider == WhatsAppTemplate.Provider.MSG91:
            result = send_msg91_whatsapp_template(
                to_number=to_number,
                template=template,
                context=preview_context,
            )
        else:
            result = WhatsAppSendResult(
                ok=False,
                error=f"Unknown WhatsApp provider: {provider}",
            )

        if result.ok:
            log.mark_sent(
                message_id=result.message_id,
                raw_response=result.raw_response,
            )
        else:
            if result.skipped:
                log.status = WhatsAppSendLog.Status.SKIPPED
                log.error_message = result.error
                log.raw_response = result.raw_response or {}
                log.save(update_fields=["status", "error_message", "raw_response"])
            else:
                log.mark_failed(
                    result.error,
                    raw_response=result.raw_response,
                )

        return result

    except Exception as exc:
        log.status = WhatsAppSendLog.Status.FAILED
        log.error_message = str(exc)
        log.save()
        return WhatsAppSendResult(ok=False, error=str(exc))