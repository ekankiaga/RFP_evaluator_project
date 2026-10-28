"""Generate polished fictional supplier proposals and importable scoring templates."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import pymupdf as fitz
import yaml
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

INK = colors.HexColor("#17324D")
TEAL = colors.HexColor("#1F6B64")
PALE = colors.HexColor("#EAF2F0")
MUTED = colors.HexColor("#607180")
LINE = colors.HexColor("#D7E0E5")

SUPPLIERS = {
    "Apex Systems": {
        "profile": "Large enterprise platform vendor with a mature implementation practice and premium pricing.",
        "experience": "12 comparable enterprise deployments in the past five years",
        "price": "$1.42 million over five years",
        "summary": "A complete, well-evidenced offer with strong assurance, operations, and exit commitments. The main tradeoff is a higher five-year price.",
        "it": {
            "solution": "The platform supports 2 million named users, REST APIs, SCIM provisioning, and tested connectors for Okta and Workday. The production design uses separate US and EU regions and a documented 99.95% monthly availability target.",
            "security": "The response includes a current SOC 2 Type II report dated February 15, 2026, and an ISO 27001 certificate valid through June 30, 2027. Data is encrypted with AES-256 at rest and TLS 1.2 or later in transit. The incident plan commits to customer notice within 24 hours of a confirmed material incident.",
            "delivery": "A named program director and migration lead own a 16-week rollout. The plan includes source data mapping, two migration rehearsals, role-based user testing, a rollback checkpoint, and administrator training before go-live.",
            "operations": "The service target is 99.95% monthly uptime. Priority 1 support is staffed 24 by 7 with a 15-minute response target. The continuity plan states a four-hour recovery time objective and a one-hour recovery point objective. Service credits apply when monthly uptime falls below the contracted target.",
            "exit": "At contract end, the customer may export records and relationships in CSV and JSON without an extraction fee. The offer includes 90 days of transition assistance and a deletion certificate after the retention period.",
            "commercial": "Five-year total is $1.42 million, including implementation, subscription, standard support, and two migration rehearsals. Optional premium analytics are excluded and priced separately.",
            "risk": "The proposal does not identify the number of EU-based support engineers. Confirm regional support coverage during negotiation.",
        },
        "health": {
            "solution": "The clinical operations platform supports FHIR R4 Patient, Encounter, and Observation resources plus HL7 v2 ADT and ORU interfaces. The interface package includes a conformance test report and a named interoperability lead.",
            "security": "A Business Associate Agreement is included. The proposal supplies a current SOC 2 Type II report dated February 15, 2026, and an ISO 27001 certificate valid through June 30, 2027. Patient data is encrypted at rest and in transit, with role-based access and immutable audit events.",
            "delivery": "The 20-week implementation includes workflow validation scripts, a validation traceability matrix, migration reconciliation, clinical super-user training, and a controlled go-live with a two-week hypercare period.",
            "operations": "Priority 1 clinical system incidents receive a 15-minute response at all hours. Recovery time is four hours and recovery point is one hour. Downtime procedures and quarterly continuity exercises are included.",
            "exit": "Patient and study records can be exported in documented FHIR and CSV formats. Transition assistance is included for 90 days; deletion is recorded after the agreed retention period.",
            "commercial": "Five-year total is $1.58 million, including the BAA, implementation, validation support, standard interfaces, and 24 by 7 critical incident support.",
            "risk": "The offer includes a complete control package but is the highest priced response. Validate the scope of the included interface maintenance.",
        },
    },
    "BrightPath Tech": {
        "profile": "Mid-sized specialist with a collaborative delivery model and competitive pricing.",
        "experience": "8 comparable deployments, including three migrations from legacy platforms",
        "price": "$1.08 million over five years",
        "summary": "The clearest implementation plan and a competitive price. Independent security assurance is incomplete, so the buyer should treat the certification gap as a material risk.",
        "it": {
            "solution": "The service supports 600,000 users, REST APIs, SAML single sign-on, and standard CSV import. The proposal lists connectors for Okta and Microsoft Entra ID but leaves the Workday connector as a later change request. The uptime target is 99.9%.",
            "security": "AES-256 at rest and TLS 1.2 in transit are described. The SOC 2 Type II assessment is in progress; the proposal confirms there is no current SOC 2 report, and no ISO 27001 certificate is supplied. The production hosting region and subprocessor locations are not identified in this proposal. The security lead will provide a remediation tracker each month.",
            "delivery": "A named project manager and data migration lead own a 12-week rollout. The schedule includes weekly decision meetings, three data rehearsals, acceptance criteria for each milestone, and two weeks of post-launch support.",
            "operations": "Priority 1 incidents receive a 30-minute response during 24 by 7 coverage. The recovery time objective is 12 hours and recovery point objective is four hours. Service credits are offered below 99.9% uptime.",
            "exit": "A CSV export is available at termination. The proposal does not describe exporting user permissions or linked records, and transition support is limited to 30 days.",
            "commercial": "Five-year total is $1.08 million, including implementation and standard support. Workday integration, data archive storage, and after-hours change requests are excluded.",
            "risk": "No current independent security report is provided. Workday integration and full data portability need contractual clarification.",
        },
        "health": {
            "solution": "The platform supports FHIR R4 Patient and Encounter resources and HL7 v2 ADT. A standard BAA is included. The proposal describes three EHR integrations but provides no conformance test results for Observation resources.",
            "security": "The SOC 2 Type II assessment is in progress and no current report is available. AES-256 at rest and TLS 1.2 in transit are described. The BAA is included, with a named privacy contact and a 48-hour breach notification commitment.",
            "delivery": "A named clinical implementation manager leads a 14-week rollout. The plan includes data reconciliation, role-based workflow testing, validation scripts, clinical super-user training, and two weeks of post-launch support.",
            "operations": "Priority 1 support is staffed 24 by 7 with a 30-minute response target. Recovery time is 12 hours and recovery point is four hours. The proposal includes a manual downtime workflow but does not include quarterly continuity exercises.",
            "exit": "Patient records are exportable in CSV; FHIR export is a priced option. The standard contract includes 30 days of transition support and no stated export fee for the CSV package.",
            "commercial": "Five-year total is $1.24 million, including implementation, standard BAA, and HL7 ADT interface. FHIR Observation, extended validation support, and after-hours change requests are priced separately.",
            "risk": "A current independent security report and broader FHIR conformance evidence are not supplied. Confirm those items before award.",
        },
    },
    "NexaWorks": {
        "profile": "High-growth provider with modern APIs, rapid releases, and the lowest price in this demonstration.",
        "experience": "5 comparable deployments; two use the same subcontracted migration team",
        "price": "$930,000 over five years",
        "summary": "The lowest-cost offer has promising API depth but leaves ownership, security assurance, and transition details unresolved.",
        "it": {
            "solution": "The product offers REST and GraphQL APIs, webhooks, and a monthly release cadence. The proposal does not specify a tested user limit or a committed production availability target. Three critical connectors are delivered by subcontractors.",
            "security": "AES-256 at rest and TLS 1.2 in transit are stated. The company has no current SOC 2 Type II report or ISO 27001 certificate; the SOC 2 audit is planned for the fourth quarter. Hosting region and subprocessor locations are not listed.",
            "delivery": "The estimated rollout is 10 weeks, but the plan does not name a customer-side migration owner. Data mapping and acceptance criteria are described as to be agreed after contract signature. The proposal uses three subcontractors for integration work.",
            "operations": "The service target is 99.7% monthly uptime. Priority 1 support is available 24 by 5 with a one-hour response target. Recovery objectives and service credits are not stated.",
            "exit": "The vendor offers a basic CSV extract. Exporting linked records, configuration, and audit history is not described; transition assistance is not included in the fixed price.",
            "commercial": "Five-year total is $930,000, the lowest offer. The price excludes premium support, data egress, subcontractor changes, and any additional migration rehearsals.",
            "risk": "No current security certificate, unspecified hosting region, missing recovery targets, and an incomplete exit plan create significant delivery risk.",
        },
        "health": {
            "solution": "The platform supports REST APIs and a FHIR R4 Patient endpoint. The proposal does not include a BAA, HL7 interface conformance report, or evidence that clinical workflows were validated.",
            "security": "The vendor states encryption at rest and in transit but supplies no current SOC 2 report, ISO certificate, or BAA. Hosting region and subprocessor locations are not disclosed. The security audit is planned for the fourth quarter.",
            "delivery": "The 10-week estimate has no named validation owner. Workflow acceptance criteria and migration reconciliation are to be agreed after signature. Three subcontractors are proposed for interfaces, without named clinical validation roles.",
            "operations": "Priority 1 support is available 24 by 5 with a one-hour response target. Recovery time, recovery point, clinical downtime procedure, and continuity exercise evidence are not supplied.",
            "exit": "Only a basic CSV extract is described. FHIR export, audit history, transition assistance, and verified deletion are not included in the fixed price.",
            "commercial": "Five-year total is $1.12 million. BAA negotiation, validation support, premium support, and additional interfaces are excluded or separately priced.",
            "risk": "The offer has no BAA and no current independent security report. Validation, continuity, and subcontractor ownership require substantial clarification.",
        },
    },
    "Orbit Digital": {
        "profile": "Established regional provider focused on dependable operations, practical delivery, and local support.",
        "experience": "10 comparable deployments, including four public-sector organizations",
        "price": "$1.19 million over five years",
        "summary": "A balanced offer with strong local support and credible assurance. The smaller specialist bench and fewer advanced analytics are the main tradeoffs.",
        "it": {
            "solution": "The platform supports 400,000 users, REST APIs, SAML, and standard connectors for Microsoft Entra ID and ServiceNow. Hosting is available in the US and EU. The production availability target is 99.9%.",
            "security": "A current ISO 27001 certificate is valid through May 31, 2027. AES-256 at rest, TLS 1.2 in transit, quarterly access reviews, and a 24-hour incident notification target are documented. The proposal does not include a SOC 2 Type II report.",
            "delivery": "A local delivery director owns a 15-week rollout. The plan includes process workshops, a staged migration, one full rehearsal, weekly risk review, and administrator training. Advanced analytics are limited to the standard reporting package.",
            "operations": "Priority 1 support receives a 20-minute response at all hours. Recovery time is eight hours and recovery point is two hours. Monthly service reports and quarterly continuity tests are included.",
            "exit": "Data is exportable in CSV and JSON with linked records. A 60-day transition package is included; custom report definitions require a separate statement of work.",
            "commercial": "Five-year total is $1.19 million, including the standard reporting package, implementation, and 24 by 7 critical support. Custom analytics and non-standard integrations are excluded.",
            "risk": "The regional team is accessible, but the proposal has fewer specialist analytics resources and a less generous recovery target than the enterprise leader.",
        },
        "health": {
            "solution": "The platform supports HL7 v2 ADT and FHIR R4 Patient and Encounter resources. The proposal includes an interface inventory and test scripts, but not FHIR Observation support in the base package.",
            "security": "A current ISO 27001 certificate is valid through May 31, 2027. A standard BAA is offered. AES-256 at rest, TLS 1.2 in transit, role-based access, and quarterly access reviews are documented.",
            "delivery": "A local clinical delivery director leads a 15-week deployment. The plan includes workflow mapping, migration reconciliation, one validation rehearsal, clinical user training, and a two-week go-live support window.",
            "operations": "Priority 1 incidents receive a 20-minute response at all hours. Recovery time is eight hours and recovery point is two hours. Monthly service reporting and quarterly continuity tests are included.",
            "exit": "Patient and study records can be exported in CSV and supported FHIR resources. Transition support is included for 60 days; custom reports require separate work.",
            "commercial": "Five-year total is $1.36 million, including the BAA, standard interfaces, validation rehearsal, and critical incident support. FHIR Observation and advanced analytics are priced separately.",
            "risk": "The offer has practical local support and a BAA, but has fewer specialist clinical resources and a narrower FHIR package than the enterprise leader.",
        },
    },
}

DOMAINS = {
    "it_software_saas": {
        "title": "Enterprise SaaS Platform and Implementation Services",
        "need": "A secure cloud platform with implementation, migration, training, integrations, and five years of support.",
        "sections": [
            ("Platform and integration", "solution"), ("Security and assurance", "security"),
            ("Implementation approach", "delivery"), ("Service levels and support", "operations"),
            ("Data exit and portability", "exit"), ("Commercial offer", "commercial"),
        ],
        "gate": "Current independent security assurance",
    },
    "healthcare_life_sciences": {
        "title": "Clinical Operations and Healthcare Data Coordination Platform",
        "need": "A privacy-protective platform with validated workflows, healthcare interoperability, implementation, and dependable support.",
        "sections": [
            ("Clinical workflow and interoperability", "solution"), ("Privacy and security assurance", "security"),
            ("Implementation and validation", "delivery"), ("Service continuity and support", "operations"),
            ("Data export and transition", "exit"), ("Commercial offer", "commercial"),
        ],
        "gate": "Business Associate Agreement and healthcare safeguards",
    },
}


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("ProposalTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=23, leading=28, textColor=INK, alignment=TA_LEFT, spaceAfter=10),
        "eyebrow": ParagraphStyle("Eyebrow", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=11, textColor=TEAL, spaceAfter=8),
        "h1": ParagraphStyle("Section", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=INK, spaceBefore=2, spaceAfter=9),
        "h2": ParagraphStyle("Subsection", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=TEAL, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=14, textColor=INK, spaceAfter=8),
        "small": ParagraphStyle("Small", parent=base["BodyText"], fontName="Helvetica", fontSize=8.5, leading=12, textColor=MUTED),
        "cell": ParagraphStyle("Cell", parent=base["BodyText"], fontName="Helvetica", fontSize=8.5, leading=12, textColor=INK),
        "cell_head": ParagraphStyle("CellHead", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=8.5, leading=12, textColor=INK),
    }


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _footer(canvas, doc):
    canvas.saveState()
    width, _ = letter
    canvas.setStrokeColor(LINE)
    canvas.line(doc.leftMargin, 0.55 * inch, width - doc.rightMargin, 0.55 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(doc.leftMargin, 0.36 * inch, "SYNTHETIC DEMO PROPOSAL - fictional supplier and claims")
    canvas.drawRightString(width - doc.rightMargin, 0.36 * inch, f"Page {doc.page}")
    canvas.restoreState()


def _criterion_response(domain_id: str, supplier_name: str, profile: dict[str, str], criterion_name: str) -> str:
    domain_key = "health" if domain_id == "healthcare_life_sciences" else "it"
    answers = profile[domain_key]
    if domain_id == "it_software_saas":
        solution = answers["solution"]
        security = answers["security"]
        operations = answers["operations"]
        specific = {
            "Technical Capability": {
                "Apex Systems": "The platform supports 2 million named users.",
                "BrightPath Tech": "The service supports 600,000 users.",
                "NexaWorks": "The proposal does not specify a tested user limit or a committed production availability target.",
                "Orbit Digital": "The platform supports 400,000 users.",
            },
            "API & Integration Depth": {
                "Apex Systems": "REST APIs, SCIM provisioning, and tested connectors for Okta and Workday.",
                "BrightPath Tech": "REST APIs, SAML single sign-on, and standard CSV import. The proposal lists connectors for Okta and Microsoft Entra ID but leaves the Workday connector as a later change request.",
                "NexaWorks": "The product offers REST and GraphQL APIs, webhooks, and a monthly release cadence. Three critical connectors are delivered by subcontractors.",
                "Orbit Digital": "REST APIs, SAML, and standard connectors for Microsoft Entra ID and ServiceNow.",
            },
            "Data Residency & Privacy": {
                "Apex Systems": "The production design uses separate US and EU regions.",
                "BrightPath Tech": "The production hosting region and subprocessor locations are not identified in this proposal.",
                "NexaWorks": "Hosting region and subprocessor locations are not listed.",
                "Orbit Digital": "Hosting is available in the US and EU.",
            },
            "Exit & Portability": "exit",
            "Security Certification": {
                "Apex Systems": "The response includes a current SOC 2 Type II report dated February 15, 2026, and an ISO 27001 certificate valid through June 30, 2027.",
                "BrightPath Tech": "The SOC 2 Type II assessment is in progress; the proposal confirms there is no current SOC 2 report, and no ISO 27001 certificate is supplied.",
                "NexaWorks": "The company has no current SOC 2 Type II report or ISO 27001 certificate; the SOC 2 audit is planned for the fourth quarter.",
                "Orbit Digital": "A current ISO 27001 certificate is valid through May 31, 2027.",
            },
        }
        if criterion_name in specific:
            selected = specific[criterion_name]
            if selected == "exit":
                return answers["exit"]
            return selected[supplier_name]
        if criterion_name == "Security & Compliance":
            sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", security)
                         if part.strip() and not any(term in part.casefold() for term in ("soc 2", "iso 27001", "certificate"))]
            return " ".join(sentences) or security
        if criterion_name == "Support & Experience":
            support_sentence = next((part.strip() for part in re.split(r"(?<=[.!?])\s+", operations)
                                     if "support" in part.casefold() or "priority 1" in part.casefold()), operations)
            return support_sentence + " Relevant experience: " + profile["experience"] + "."
        if criterion_name == "Service Levels & Availability":
            sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", operations)
                         if any(term in part.casefold() for term in ("uptime", "recovery time", "recovery objectives", "service credit"))]
            return " ".join(sentences) or operations

    generic_map = {
        "Technical Capability": "solution", "Implementation Plan": "delivery",
        "Commercial Value": "commercial", "Security & Compliance": "security",
        "Support & Experience": "operations",
    }
    healthcare_map = {
        "HIPAA & GxP Controls": "security", "Clinical Validation": "delivery",
        "HL7/FHIR Interoperability": "solution", "Patient Data Governance": "security",
        "Safety & Quality Management": "delivery",
    }
    key = generic_map.get(criterion_name)
    if domain_id == "healthcare_life_sciences":
        key = key or healthcare_map.get(criterion_name)
    if key:
        response = answers[key]
        if criterion_name in {"Technical Capability", "Support & Experience"}:
            response += " Relevant experience: " + profile["experience"] + "."
        return response
    return "No response was supplied for this requirement."


def make_pdf(path: Path, title: str, domain_id: str, supplier_name: str, profile: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    domain = DOMAINS[domain_id]
    evidence = profile["health" if domain_id == "healthcare_life_sciences" else "it"]
    pack_path = ROOT / "domain_packs" / f"{domain_id}.yaml"
    pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
    styles = _styles()
    doc = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=0.72 * inch, leftMargin=0.72 * inch,
        topMargin=0.7 * inch, bottomMargin=0.78 * inch, title=title, author=supplier_name)
    story = [
        _p("FICTIONAL PROCUREMENT RESPONSE | DEMO DATA", styles["eyebrow"]),
        _p(title, styles["title"]),
        _p(f"Submitted by {supplier_name}", styles["h2"]),
        Spacer(1, 8),
    ]
    snapshot = [
        [_p("Procurement need", styles["cell_head"]), _p(domain["need"], styles["cell"])],
        [_p("Relevant experience", styles["cell_head"]), _p(profile["experience"], styles["cell"])],
        [_p("Five-year offer", styles["cell_head"]), _p(profile["price"], styles["cell"])],
    ]
    table = Table(snapshot, colWidths=[1.35 * inch, 5.7 * inch], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), PALE), ("BACKGROUND", (1, 0), (1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [table, Spacer(1, 18), _p("Executive summary", styles["h1"]), _p(profile["summary"], styles["body"]),
        _p("Supplier profile", styles["h2"]), _p(profile["profile"], styles["body"]),
        _p("This is fictional demonstration material. Supplier names, customers, certifications, prices, performance figures, and proposal claims are invented.", styles["small"]),
        PageBreak(), _p("Response to scoring criteria", styles["h1"]),
        _p("The response sections use the same criterion names as the matching RFP Compass template. Statements below are the supplier’s fictional claims for evaluation.", styles["small"]),
        Spacer(1, 8)]
    groups = [("General criteria", pack.get("generic_criteria", [])),
              ("Domain-specific criteria", pack.get("domain_criteria", []))]
    for group_index, (group_title, criteria) in enumerate(groups):
        if group_index:
            story += [PageBreak(), _p("Response to scoring criteria · continued", styles["h1"]), _p(group_title, styles["h2"])]
        else:
            story.append(_p(group_title, styles["h2"]))
        for criterion in criteria:
            answer = _criterion_response(domain_id, supplier_name, profile, criterion["name"])
            story += [_p(criterion["name"], styles["h2"]), _p(answer, styles["body"])]
    story += [Spacer(1, 6), _p("Key exception / clarification", styles["h2"]),
        _p(evidence["risk"], styles["body"]), _p("All response claims are fictional and included only for software demonstration. Do not use them as real procurement evidence.", styles["small"])]
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)


def _resolved_criteria(pack: dict) -> list[dict]:
    generic = [dict(item) for item in pack.get("generic_criteria", [])]
    domain = [dict(item) for item in pack.get("domain_criteria", [])]
    split = pack.get("weight_split", {})
    if not domain:
        groups = [(generic, 100.0)]
    else:
        groups = [(generic, float(split.get("generic", 60))), (domain, float(split.get("domain", 40)))]
    result = []
    for items, target in groups:
        total = sum(float(item.get("weight", 0)) for item in items)
        consumed = 0.0
        for index, item in enumerate(items):
            if index == len(items) - 1:
                item["weight"] = round(target - consumed, 6)
            else:
                item["weight"] = round(float(item["weight"]) * target / total, 6) if total else 0.0
                consumed += item["weight"]
            item["is_active"] = True
            result.append(item)
    return result


def _write_sample_templates() -> int:
    output_dir = ROOT / "sample_data" / "templates"
    output_dir.mkdir(parents=True, exist_ok=True)
    for pack_path in sorted((ROOT / "domain_packs").glob("*.yaml")):
        pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
        criteria = []
        for item in _resolved_criteria(pack):
            criteria.append({key: item.get(key, default) for key, default in (
                ("name", ""), ("description", ""), ("weight", 0), ("max_score", 10),
                ("what_to_inspect", ""), ("red_flags", []), ("evidence_hints", []),
                ("is_mandatory_gate", False))})
        sample = {"criteria": criteria}
        (output_dir / f"{pack['domain_id']}.json").write_text(json.dumps(sample, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(list(output_dir.glob("*.json")))


def _write_validation_fixtures() -> None:
    fixtures = ROOT / "sample_data" / "pdfs" / "validation_fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    blank = fitz.open()
    blank.new_page()
    blank.save(fixtures / "valid_but_empty.pdf")
    blank.close()
    (fixtures / "corrupted.pdf").write_bytes(b"%PDF-1.7\nnot-a-valid-xref\x00broken")
    source = fitz.open()
    page = source.new_page(width=595, height=842)
    page.insert_text((50, 80), "Scanned proposal fixture - image only", fontsize=18)
    page.insert_textbox(fitz.Rect(50, 120, 540, 600), "This page contains rasterized text only. OCR is not enabled in the demo pipeline.", fontsize=14)
    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
    image_pdf = fitz.open()
    image_page = image_pdf.new_page(width=595, height=842)
    image_page.insert_image(image_page.rect, stream=pix.tobytes("png"))
    image_pdf.save(fixtures / "image_only_scanned.pdf")
    source.close()
    image_pdf.close()


def main() -> None:
    for domain_id, domain in DOMAINS.items():
        for supplier_name, profile in SUPPLIERS.items():
            filename = supplier_name.lower().replace(" ", "_") + ".pdf"
            make_pdf(ROOT / "sample_data" / "pdfs" / domain_id / filename,
                domain["title"], domain_id, supplier_name, profile)
    _write_validation_fixtures()
    template_count = _write_sample_templates()
    print(f"Generated {len(DOMAINS) * len(SUPPLIERS)} polished synthetic proposals, 3 validation fixtures, and {template_count} valid domain templates.")


if __name__ == "__main__":
    main()
