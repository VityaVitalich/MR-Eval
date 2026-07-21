# LitmusValues value classes → ModelRaisingConstitution v0.2

Hand mapping used to interpret the constitution-in-context Elo shifts: for each
of the 16 AIRiskDilemmas value classes, the constitution sections that promote
it and how strongly the constitution emphasises it. Directional prediction: if
models actually take the constitution on board, classes with **strong**
constitutional backing should gain Elo relative to the **absent** ones
(Creativity, Adaptability), which act as built-in controls.

| value class | constitution sections | emphasis |
|---|---|---|
| Truthfulness | 3.1 Factual Accuracy; 3.2 Epistemic Honesty; 3.3 Non-Deception; 4.5 Honesty in Relationships | **strong** (whole Domain 3) |
| Protection | Domain 2 (2.1 Physical Safety, 2.4 Exploitation, 2.5 Dangerous Capabilities); 5.2 Vulnerable Populations | **strong** |
| Privacy | 1.5 Privacy | **strong** (dedicated section) |
| Care | 4.3 Care and Compassion; 5.1 Individual Wellbeing; 5.3 Mental Health | **strong** |
| Justice | 4.4 Fairness and Justice; 6.1 Rule of Law and Due Process; 6.3 Accountability | **strong** |
| Equal Treatment | 1.3 Equality and Non-Discrimination; 4.4 Fairness | **strong** |
| Freedom | 1.4 Autonomy and Self-Determination; 1.2 Human Rights; 6.2 Democratic Norms | **strong** |
| Respect | 4.1 Respect; 1.1 Human Dignity | **strong** |
| Sustainability | 5.5 Environmental and Intergenerational Wellbeing | moderate (one dedicated section) |
| Cooperation | 5.6 Community and Social Cohesion | moderate |
| Communication | 3.3 Non-Deception (transparent framing); 4.2 Tone and Register | moderate/indirect |
| Wisdom | 3.6 Intellectual Humility and Calibration; 3.5 Epistemic Autonomy | moderate/indirect |
| Learning | 1.2 Human Rights (right to education); 3.5 Epistemic Autonomy | weak/indirect |
| Professionalism | 4.2 Tone and Register | weak/indirect |
| Creativity | — | **absent** (control) |
| Adaptability | — | **absent** (control) |

Notes:
- The constitution also pushes *against* the dataset's risky behaviors
  directly: Deception (3.1–3.4), Privacy Violation (1.5), Power-Seeking (6.4
  Concentration of Power), manipulation (3.4). Prediction: risky-choice rates
  (especially Deception / Privacy Violation / Power-Seeking discriminating
  rates) should drop under both constitution conditions.
- "Corrigibility Failures", "Alignment Faking" and "Self-Preservation" have no
  direct constitutional section (the constitution is about content values, not
  AI-agent conduct) — weaker predictions there.
