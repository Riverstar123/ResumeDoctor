"""Runtime-only, synthetic PDF/DOCX bytes. No real resumes or binary fixtures."""

import io
import zipfile

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"


def pdf_bytes(
    *texts: str, encrypted: bool = False, compressed: bool = False, image_only: bool = False
) -> bytes:
    writer = PdfWriter()
    chars = sorted(set("".join(texts)))
    cmap = DecodedStreamObject()
    mappings = "\n".join(f"<{ord(char):04X}> <{ord(char):04X}>" for char in chars)
    cmap.set_data(
        (
            "/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
            "/CMapName /Synthetic def /CMapType 2 def\n"
            "1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
            f"{len(chars)} beginbfchar\n{mappings}\nendbfchar\n"
            "endcmap CMapName currentdict /CMap defineresource pop end end"
        ).encode("ascii")
    )
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/BaseFont"): NameObject("/STSong-Light"),
            NameObject("/Encoding"): NameObject("/Identity-H"),
            NameObject("/ToUnicode"): writer._add_object(cmap),
            NameObject("/DescendantFonts"): ArrayObject(
                [
                    DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/CIDFontType0"),
                            NameObject("/BaseFont"): NameObject("/STSong-Light"),
                        }
                    )
                ]
            ),
        }
    )
    font_ref = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if image_only:
            image = DecodedStreamObject()
            image.set_data(b"\xff\xff\xff")
            image.update(
                {
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Image"),
                    NameObject("/Width"): NumberObject(1),
                    NameObject("/Height"): NumberObject(1),
                    NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                    NameObject("/BitsPerComponent"): NumberObject(8),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {
                    NameObject("/XObject"): DictionaryObject(
                        {NameObject("/Im1"): writer._add_object(image)}
                    )
                }
            )
            contents = DecodedStreamObject()
            contents.set_data(b"q 100 0 0 100 40 600 cm /Im1 Do Q")
            page[NameObject("/Contents")] = writer._add_object(contents)
        if text:
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
            )
            contents = DecodedStreamObject()
            contents.set_data(
                f"BT /F1 12 Tf 40 750 Td <{text.encode('utf-16-be').hex()}> Tj ET".encode()
            )
            page[NameObject("/Contents")] = writer._add_object(
                contents.flate_encode() if compressed else contents
            )
    if encrypted:
        writer.encrypt("synthetic-only-password")
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def docx_bytes(body: str, *, extra: dict[str, bytes] | None = None) -> bytes:
    parts = {
        "[Content_Types].xml": (
            f'<Types xmlns="{CT}"><Override PartName="/word/document.xml" '
            f'ContentType="{DOCX_TYPE}"/></Types>'
        ).encode(),
        "_rels/.rels": (
            f'<Relationships xmlns="{REL}"><Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>'
        ).encode(),
        "word/document.xml": (
            f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
        ).encode(),
    }
    parts.update(extra or {})
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            entry = zipfile.ZipInfo()
            # Preserve hostile spellings in negative fixtures; Windows ZipInfo
            # would otherwise normalize the very backslash being tested.
            entry.filename = name
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, value)
    return stream.getvalue()
