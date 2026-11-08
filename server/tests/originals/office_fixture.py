"""Synthetic DOCX and photo originals built from stdlib bytes (no customer material)."""

import io
import zipfile

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def docx_bytes(body=None, *, main_type=_MAIN, extra=None, document=True):
    body = (
        body
        if body is not None
        else (
            "<w:p><w:r><w:t>合成规格（非真实客户资料）</w:t></w:r></w:p>"
            "<w:p/>"
            "<w:p><w:r><w:t>额定压力：</w:t></w:r><w:r><w:tab/><w:t>150 PSI</w:t></w:r>"
            "<w:del><w:r><w:delText>120 PSI</w:delText></w:r></w:del></w:p>"
            "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>项目</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>目标</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>噪声</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>≤ 70 dB</w:t><w:br/><w:t>1 米处</w:t></w:r></w:p></w:tc>"
            "</w:tr></w:tbl>"
        )
    )
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/word/document.xml" ContentType="{main_type}"/></Types>'
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="word/document.xml"/></Relationships>'
        ),
    }
    if document:
        parts["word/document.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8"?><w:document {_NS}><w:body>{body}</w:body>'
            "</w:document>"
        )
    parts.update(extra or {})
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    return stream.getvalue()


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 17 + b"synthetic photo"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF\x00" + b"synthetic photo bytes" + b"\xff\xd9"
