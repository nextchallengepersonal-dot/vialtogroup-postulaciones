import os
import re
import ssl
import smtplib
import mimetypes
from email.message import EmailMessage
from email.utils import formataddr
from flask import Flask, render_template, request, flash, redirect, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "CAMBIAR-ESTA-CLAVE-ANTES-DE-PUBLICAR")

# Límites: 18 MB por archivo y 18 MB en total para que el correo resultante
# permanezca por debajo del límite habitual de Titan (la codificación MIME aumenta el tamaño).
MAX_FILE_BYTES = 18 * 1024 * 1024
MAX_TOTAL_BYTES = 18 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

RECIPIENT = os.environ.get("RECIPIENT_EMAIL", "personal@vialtogroup.com")
SENDER = os.environ.get("SMTP_USERNAME", "personal@vialtogroup.com")
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}

DOCUMENTS = [
    ("cv", "Currículum Vitae actualizado", True),
    ("cedula", "Cédula de identidad (ambas caras)", True),
    ("antecedentes", "Certificado de Antecedentes para Fines Especiales", True),
    ("afp", "Certificado de afiliación AFP", True),
    ("salud", "Certificado de Fonasa o Isapre", True),
    ("estudios", "Certificado de enseñanza media completa", True),
    ("licencia", "Licencia de conducir Clase D (si corresponde)", False),
]

def valid_file_signature(data, ext):
    if ext == ".pdf":
        return data.startswith(b"%PDF-")
    if ext in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    return False

def send_application(name, rut, phone, email, attachments):
    host = os.environ.get("SMTP_HOST", "smtpout.secureserver.net")
    port = int(os.environ.get("SMTP_PORT", "465"))
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")

    if not username or not password:
        raise RuntimeError("Falta configurar SMTP_USERNAME o SMTP_PASSWORD en el servidor.")

    msg = EmailMessage()
    msg["Subject"] = f"Nueva postulación Peoneta – {name}"
    msg["From"] = formataddr(("VIALTOGROUP - Postulaciones", username))
    msg["To"] = RECIPIENT
    msg["Reply-To"] = email
    msg.set_content(
        "VIALTOGROUP – Nueva postulación para el cargo de Peoneta\n\n"
        f"Nombre: {name}\nRUT: {rut}\nTeléfono: {phone}\nCorreo: {email}\n\n"
        "Los documentos enviados por el postulante se incluyen como archivos adjuntos.\n"
        "Por seguridad, revise los archivos y elimínelos cuando ya no sean necesarios."
    )

    for original_name, data, ext in attachments:
        mime, _ = mimetypes.guess_type("archivo" + ext)
        maintype, subtype = (mime or "application/octet-stream").split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype,
                           filename=secure_filename(original_name) or ("documento" + ext))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
        server.login(username, password)
        server.send_message(msg)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template("index.html", documents=DOCUMENTS)

    # Campo trampa anti-spam: los usuarios reales lo dejan vacío.
    if request.form.get("website", "").strip():
        return redirect(url_for("success"))

    name = request.form.get("name", "").strip()
    rut = request.form.get("rut", "").strip()
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()
    consent = request.form.get("consent")

    if not all([name, rut, phone, email]) or not consent:
        flash("Completa todos los datos obligatorios y acepta el aviso de privacidad.", "error")
        return redirect(url_for("index"))

    if len(name) > 120 or len(rut) > 20 or len(phone) > 40 or len(email) > 254:
        flash("Uno de los datos ingresados supera la longitud permitida.", "error")
        return redirect(url_for("index"))
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        flash("Ingresa un correo electrónico válido.", "error")
        return redirect(url_for("index"))

    attachments = []
    total = 0
    for field, label, required in DOCUMENTS:
        uploaded = request.files.get(field)
        if not uploaded or not uploaded.filename:
            if required:
                flash(f"Falta adjuntar: {label}.", "error")
                return redirect(url_for("index"))
            continue

        filename = secure_filename(uploaded.filename)
        ext = os.path.splitext(filename.lower())[1]
        if ext not in ALLOWED_EXTENSIONS:
            flash(f"Formato no permitido en «{label}». Usa PDF, JPG o PNG.", "error")
            return redirect(url_for("index"))

        data = uploaded.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            flash(f"El archivo «{label}» supera 18 MB.", "error")
            return redirect(url_for("index"))
        if not data or not valid_file_signature(data, ext):
            flash(f"No se pudo validar el archivo «{label}». Comprueba que sea un PDF o imagen válido.", "error")
            return redirect(url_for("index"))

        total += len(data)
        if total > MAX_TOTAL_BYTES:
            flash("El tamaño combinado de todos los documentos no puede superar 18 MB. Reduce o comprime los archivos.", "error")
            return redirect(url_for("index"))
        attachments.append((filename, data, ext))

    try:
        send_application(name, rut, phone, email, attachments)
    except Exception:
        app.logger.exception("No se pudo enviar la postulación")
        flash("No fue posible enviar la postulación en este momento. Inténtalo nuevamente más tarde.", "error")
        return redirect(url_for("index"))

    return redirect(url_for("success"))

@app.route("/enviado")
def success():
    return render_template("success.html")

@app.errorhandler(413)
def too_large(_error):
    flash("La carga supera el límite permitido. El tamaño combinado máximo es 18 MB.", "error")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
