"""Generate a sample contract PDF for demo and testing purposes."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from io import BytesIO

SAMPLE_CONTRACT_TEXT = """MASTER SERVICES AGREEMENT

This Master Services Agreement ("Agreement") is made effective as of March 1, 2026 ("Effective Date"), by and between NovaTech Solutions Inc ("Client") and CloudBridge Systems LLC ("Vendor").

This Agreement shall be governed by and construed in accordance with the laws of the State of Delaware.


ARTICLE 1: SERVICES AND SCOPE

1.1 Vendor shall provide cloud infrastructure management, DevOps consulting, and 24/7 monitoring services as described in applicable Statements of Work ("SOWs").
1.2 Client shall provide Vendor with necessary access credentials, documentation, and infrastructure topology information.
1.3 Vendor shall assign a dedicated Technical Account Manager within five (5) business days of execution.


ARTICLE 2: FEES AND PAYMENT

2.1 Client shall pay all undisputed invoices within thirty (30) days of receipt (Net 30).
2.2 The base monthly service fee is $45,000 USD, subject to annual CPI adjustment not to exceed 5%.
2.3 Late payments shall bear interest at 1.5% per month on the outstanding balance.
2.4 Vendor shall submit itemized invoices on the first business day of each calendar month.


ARTICLE 3: TERM AND TERMINATION

3.1 This Agreement shall commence on the Effective Date and remain in effect for two (2) years, with automatic annual renewal unless either party provides sixty (60) days written notice prior to the renewal date.
3.2 Either party may terminate this Agreement without cause upon giving ninety (90) days prior written notice to the other party.
3.3 Either party may terminate immediately if the other party breaches any material term and fails to cure within thirty (30) days after receiving written notice specifying the breach.
3.4 Upon termination, Vendor shall provide a transition plan within ten (10) business days and cooperate with Client's successor vendor for a period not to exceed ninety (90) days.


ARTICLE 4: CONFIDENTIALITY

4.1 Each party shall maintain the confidentiality of all proprietary and confidential information received from the other party.
4.2 Confidentiality obligations shall survive termination of this Agreement for a period of three (3) years.
4.3 Notwithstanding the foregoing, confidential information shall not include information that: (a) is or becomes publicly available; (b) is received from a third party without restriction; or (c) is independently developed.


ARTICLE 5: LIMITATION OF LIABILITY

5.1 Aggregate Cap: Except for breach of confidentiality under Article 4 or indemnification under Article 6, each party's aggregate liability shall be limited to the total fees paid under this Agreement in the twelve (12) months preceding the incident giving rise to the claim.
5.2 Exclusion of Consequential Damages: In no event shall either party be liable for any indirect, incidental, special, consequential, or punitive damages, including lost profits, data loss, or business interruption.


ARTICLE 6: INDEMNIFICATION

6.1 Vendor shall indemnify, defend, and hold harmless Client against any third-party claims arising from: (a) Vendor's gross negligence or willful misconduct; (b) infringement of intellectual property rights; or (c) breach of applicable data protection laws.
6.2 Client shall indemnify Vendor against claims arising from Client's misuse of delivered services or unauthorized modification of vendor-provided systems.


ARTICLE 7: DATA PROTECTION AND SECURITY

7.1 Vendor shall implement and maintain industry-standard security controls including SOC 2 Type II certification.
7.2 Vendor shall notify Client of any data breach within twenty-four (24) hours of discovery.
7.3 Upon termination, Vendor shall securely delete or return all Client data within thirty (30) calendar days and provide written certification of destruction.


ARTICLE 8: GENERAL PROVISIONS

8.1 This Agreement constitutes the entire agreement between the parties and supersedes all prior oral or written communications.
8.2 Any modification to this Agreement must be in writing and signed by authorized representatives of both parties.
8.3 Neither party may assign this Agreement without prior written consent of the other party, except in connection with a merger or acquisition.

IN WITNESS WHEREOF, the parties have executed this Agreement as of the Effective Date.


NovaTech Solutions Inc                    CloudBridge Systems LLC

By: _________________________             By: _________________________
Name: Sarah Chen                          Name: Marcus Rivera
Title: Chief Technology Officer           Title: VP of Professional Services
Date: March 1, 2026                       Date: March 1, 2026
"""


def generate_sample_pdf(output_path: str):
    """Generate a multi-page sample contract PDF using reportlab."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.units import inch

    try:

        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=letter)
        width, height = letter

        margin = 72  # 1 inch
        y = height - margin
        line_height = 14
        max_width = width - 2 * margin

        for line in SAMPLE_CONTRACT_TEXT.split("\n"):
            if y < margin:
                c.showPage()
                y = height - margin

            stripped = line.strip()
            if stripped.startswith("ARTICLE") or stripped == "MASTER SERVICES AGREEMENT":
                c.setFont("Helvetica-Bold", 12)
            elif stripped.startswith("IN WITNESS"):
                c.setFont("Helvetica-Bold", 11)
            else:
                c.setFont("Helvetica", 10)

            if stripped:
                # Word-wrap long lines
                words = stripped.split()
                current_line = ""
                for word in words:
                    test_line = f"{current_line} {word}".strip()
                    if c.stringWidth(test_line, c._fontname, c._fontsize) < max_width:
                        current_line = test_line
                    else:
                        c.drawString(margin, y, current_line)
                        y -= line_height
                        if y < margin:
                            c.showPage()
                            y = height - margin
                            c.setFont("Helvetica", 10)
                        current_line = word
                if current_line:
                    c.drawString(margin, y, current_line)
                    y -= line_height
            else:
                y -= line_height * 0.5

        c.save()
        buf.seek(0)

        with open(output_path, "wb") as f:
            f.write(buf.getvalue())

        print(f"Sample PDF generated: {output_path}")
        return True

    except Exception as e:
        print(f"Error generating PDF: {e}")
        return False


if __name__ == "__main__":
    output = os.path.join(os.path.dirname(__file__), "samples", "sample_msa.pdf")
    os.makedirs(os.path.dirname(output), exist_ok=True)
    generate_sample_pdf(output)
