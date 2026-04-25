# Polish School Certificate Extraction

You are extracting structured data from a Polish high-school certificate
(ŚWIADECTWO SZKOLNE). The document is issued by a Polish liceum
ogólnokształcące (general high school) on official MEiN-I/14 form paper.

## What you must extract

Return a JSON object that exactly matches the schema below. Do not include
any explanatory prose, markdown fences, or extra keys.

{schema_json}

## Document structure

Page 1 (front):
- Header: "ŚWIADECTWO SZKOLNE"
- "imię (imiona) i nazwisko" — student's full name
- "data urodzenia" — date of birth (Polish text form, e.g.,
  "21 grudnia 2009 r.")
- "uczęszczał ... w roku szkolnym <YYYY/YYYY> do klasy <klasy>" — academic
  year and class attended
- "nazwa liceum ogólnokształcącego" — school name (line below)
- "w <Locative>" — city (locative case; convert to nominative; e.g.,
  "Poznaniu" → "Poznań")
- "woj. <name>" — voivodeship
- "Realizował przedmioty w zakresie rozszerzonym:" — advanced subjects
  (each on its own line). Important: the IV.1r and IV.1p suffixes after
  language names indicate level (rozszerzony / podstawowy); they are part
  of the raw_subject_name when present in the main subjects table.
- "i otrzymał promocję..." or "i otrzymał promocję z wyróżnieniem do
  klasy <next>" — promotion outcome

Page 2 (back):
- Header: "WYNIKI KLASYFIKACJI ROCZNEJ"
- "zachowanie" — conduct value (separate scale from grades — see below)
- "religia / etyka" — religion or ethics grade. **DO NOT extract this
  unless the caller explicitly opts in** — it is GDPR Article 9 special-
  category data.
- "Obowiązkowe zajęcia edukacyjne" table — main subject grades. Each row
  is a subject name and a grade word from the 6-point scale.

## Polish grading scale (zajęcia edukacyjne)

Lowest to highest: niedostateczny (1), dopuszczający (2), dostateczny (3),
dobry (4), bardzo dobry (5), celujący (6). Always return the grade word
verbatim as it appears on the document, lowercased.

## Polish conduct scale (zachowanie) — DIFFERENT FROM GRADING

Worst to best: naganne, nieodpowiednie, poprawne, dobre, bardzo dobre,
wzorowe.

## Diacritics

Polish documents use ą, ć, ę, ł, ń, ó, ś, ż, ź. Preserve them exactly.

## Confidence

If a field is unclear or unreadable, return null and add a brief note in
the document (the caller will treat absence as low confidence). Do not
guess.

## Language hint

The document is in {language_hint}. Document type: {document_type}.
