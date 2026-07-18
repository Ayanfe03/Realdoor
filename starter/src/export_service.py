from datetime import datetime, timezone
import html
import io

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None


class ExportService:
    def packet_json(self, packet: dict) -> dict:
        return {
            "export_type": "realdoor_application_readiness_packet",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "packet": packet,
            "disclaimer": "This packet supports human review and does not determine eligibility, approval, denial, ranking, or priority.",
        }

    def packet_html(self, packet: dict) -> str:
        assessment = packet["assessment"]
        confirmations = "".join(
            f"<li>{html.escape(item['field'])}: {html.escape(str(item['value']))}</li>"
            for item in packet.get("confirmations", [])
        )
        reasons = "".join(f"<li>{html.escape(str(reason))}</li>" for reason in assessment.get("review_reasons", []))
        return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>RealDoor Packet</title></head>
<body>
  <h1>RealDoor Application-Readiness Packet</h1>
  <p><strong>Household:</strong> {html.escape(packet['household_id'])}</p>
  <p><strong>Annualized income:</strong> ${assessment['annualized_income']:,.2f}</p>
  <p><strong>Comparison:</strong> {html.escape(assessment['comparison'])}</p>
  <p><strong>Readiness:</strong> {html.escape(assessment['readiness_status'])}</p>
  <h2>Confirmed Fields</h2>
  <ul>{confirmations or '<li>No confirmed fields yet.</li>'}</ul>
  <h2>Review Reasons</h2>
  <ul>{reasons or '<li>No review reasons.</li>'}</ul>
  <p>{html.escape(packet['decision_boundary'])}</p>
</body>
</html>"""

    def packet_pdf(self, packet: dict) -> bytes:
        if fitz is None:
            raise RuntimeError("PyMuPDF/fitz is required for PDF export")
        assessment = packet["assessment"]
        lines = [
            "RealDoor Application-Readiness Packet",
            f"Household: {packet['household_id']}",
            f"Annualized income: ${assessment['annualized_income']:,.2f}",
            f"Comparison: {assessment['comparison']}",
            f"Readiness: {assessment['readiness_status']}",
            f"Review reasons: {', '.join(assessment.get('review_reasons', [])) or 'None'}",
            "",
            packet["decision_boundary"],
        ]
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "\n".join(lines), fontsize=11)
        output = io.BytesIO()
        doc.save(output)
        return output.getvalue()
